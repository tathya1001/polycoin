"""Builds the categorisation evaluation input: real prepare_run payloads, embedded once.

The browser categorises with frontend/lib/scoring.ts on what prepare_run sends it. To evaluate that
exact code, this module produces exactly that input. For each split and fold, a throwaway user
gets the fold's rows uncategorised (the rows to categorise) and, from the other folds, up to N
categorised rows per category (the user's own examples). prepare_run then builds the payload the
browser would receive. Everything runs in one transaction that is always rolled back, so nothing
stays in the database.

Rows whose true category is the default ("Others") are only ever targets: in the app, a row in the
default category is uncategorised, so the right outcome for one is no proposal.

The output replaces ids with stable names (corpus row ids, category names), so a rebuild with the
same data and model gives the same file. The texts are embedded once each, with no prefix, as the
Categorise page embeds them.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from categories.models import Category
from categories.services import category_by_name, get_default_category
from transactions.models import Transaction
from transactions.services import create_transaction
from vault.services import UserCipher

from .. import services
from . import dataset, embed, stats

FOLDS = 5
# Examples per category the user has given; the server takes at most AI_MAX_EXAMPLES_PER_CATEGORY.
CURVE = (0, 1, 3, 5, 10, 20)
EMAIL = "categorize-eval@example.invalid"


class _Rollback(Exception):
    pass


def _insert(user, cipher, rows: list[dict], categorised: bool) -> dict:
    """Creates the rows; returns {transaction id: corpus row id}."""
    default = get_default_category(user)
    made = {}
    for row in rows:
        category = category_by_name(user, row["category"]) if categorised else default
        txn = create_transaction(
            cipher,
            user,
            date=date.fromisoformat(row["date"]),
            txn_type=row["txn_type"],
            name=row["name"],
            description=row["description"],
            amount=Decimal(row["amount"]),
            balance=None,
            category=category,
        )
        if row["notes"]:
            txn.notes_enc = cipher.encrypt(row["notes"].encode(), "txn.notes")
            txn.save(update_fields=["notes_enc"])
        made[str(txn.id)] = row["id"]
    return made


def _examples(rows: list[dict], count: int) -> list[dict]:
    """The newest `count` rows of each category except the default."""
    chosen = []
    for name in sorted({row["category"] for row in rows} - {"Others"}):
        group = sorted(
            (row for row in rows if row["category"] == name),
            key=lambda row: (row["date"], row["id"]),
            reverse=True,
        )
        chosen += group[:count]
    return chosen


def _stable(run: dict, txn_ids: dict, category_names: dict) -> dict:
    """The payload with database ids replaced by corpus row ids and category names."""
    run = {
        **run,
        "targets": [{**t, "transaction": txn_ids[t["transaction"]]} for t in run["targets"]],
    }
    run["candidates"] = {
        txn_type: [{**c, "category": category_names[c["category"]]} for c in candidates]
        for txn_type, candidates in run["candidates"].items()
    }
    return run


def build_runs(make_user, model: str = "") -> list[dict]:
    """Every run's payload and true categories. `make_user(email)` creates a user with the
    default categories and an unlocked key (the tests' factory). `model` picks the thresholds
    prepare_run sends, as the browser's request does."""
    runs = []
    try:
        with transaction.atomic():
            user = make_user(EMAIL)
            cipher = UserCipher(user)
            names = {str(c.pk): c.name for c in Category.objects.filter(user=user)}
            for split in dataset.SPLITS:
                corpus = dataset.corpus(split)
                folds = stats.stratified_folds(
                    [row["id"] for row in corpus], [row["category"] for row in corpus], FOLDS
                )
                curve = CURVE if split == "dev" else (settings.AI_MAX_EXAMPLES_PER_CATEGORY,)
                for number, fold in enumerate(folds):
                    held = [corpus[n] for n in fold]
                    others = [row for n, row in enumerate(corpus) if n not in set(fold)]
                    for count in curve:
                        Transaction.objects.filter(user=user).delete()
                        txn_ids = _insert(user, cipher, held, categorised=False)
                        _insert(user, cipher, _examples(others, count), categorised=True)
                        run = services.prepare_run(user, model)
                        runs.append(
                            {
                                "split": split,
                                "fold": number,
                                "examples": count,
                                "run": _stable(run, txn_ids, names),
                                "truth": {row["id"]: row["category"] for row in held},
                            }
                        )
            raise _Rollback
    except _Rollback:
        pass
    return runs


def build(make_user, url: str, model: str) -> dict:
    runs = build_runs(make_user, model)
    texts = sorted({text for run in runs for text in run["run"]["texts"]})
    base = embed.ipv4_url(url)
    info = embed.model_info(base, model)
    vectors = embed.embed(base, model, texts)
    return {
        "model": model,
        "digest": info["digest"],
        "fingerprint": {split: dataset.fingerprint(split) for split in dataset.SPLITS},
        "thresholds": runs[0]["run"]["thresholds"],
        "runs": runs,
        "vectors": dict(zip(texts, dataset.encode(vectors))),
    }
