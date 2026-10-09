from collections import defaultdict

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from categories.models import Category
from categories.services import get_default_category
from transactions.models import Transaction
from vault.services import UserCipher

from . import scoring
from .client import AIError

# Which directions the AI may PROPOSE each seed category for. A debit is never auto-labelled
# Salary and a credit is never auto-labelled Food. Categories not listed here (Transfer, and
# anything custom or renamed) are allowed in both. This limits proposals only: the user can
# still put any transaction in any category by hand, and apply_decisions honours that.
ALLOWED_TYPES = {
    "salary": {"credit"},
    "food": {"debit"},
    "groceries": {"debit"},
    "transport": {"debit"},
    "shopping": {"debit"},
    "bills": {"debit"},
    "rent": {"debit"},
    "entertainment": {"debit"},
    "health": {"debit"},
}


def _allowed(category: Category, txn_type: str) -> bool:
    return txn_type in ALLOWED_TYPES.get(category.name.lower(), {"credit", "debit"})


def _label_text(category: Category) -> str:
    """What represents the category before it has any examples: its name (always, so a new or
    renamed category is searchable at once) plus the user's own keywords. Callers prefetch
    `keywords`, which the model already orders, so the text is stable between runs."""
    terms = [keyword.term for keyword in category.keywords.all()]
    return f"{category.name}: {', '.join(terms)}" if terms else category.name


def validate_model(client, model: str) -> None:
    """A request-supplied string only reaches Ollama if it's an installed embedding model."""
    if model not in {entry["name"] for entry in client.list_models()}:
        raise AIError("model_not_found", f"'{model}' isn't an installed embedding model.")


def _decrypt_fields(cipher: UserCipher, txn: Transaction) -> tuple[str, str, str]:
    """(name, description, notes), in the order scoring.prepare_text takes them. Plaintext
    lives only in memory for the length of a run: never log or persist it."""
    notes = (
        cipher.decrypt(bytes(txn.notes_enc), "txn.notes").decode()
        if txn.notes_enc is not None
        else ""
    )
    return (
        cipher.decrypt(bytes(txn.name_enc), "txn.name").decode(),
        cipher.decrypt(bytes(txn.description_enc), "txn.description").decode(),
        notes,
    )


def _load_targets(user, default: Category) -> tuple[list[Transaction], bool]:
    """Newest uncategorised rows, capped. Fetches one extra row to learn if the cap bit."""
    limit = settings.AI_MAX_RUN
    rows = list(
        Transaction.objects.filter(user=user, category=default).order_by("-date", "-created_at")[
            : limit + 1
        ]
    )
    return rows[:limit], len(rows) > limit


def _load_examples(user, default: Category, txn_types):
    """The user's own categorised rows, newest N per (category, txn_type), in one query.

    Every row outside Others is the user's decision: they either chose it, or approved the
    AI's proposal, and an approval is just as much theirs. So all of them teach the AI.
    """
    queryset = Transaction.objects.filter(user=user, txn_type__in=txn_types).exclude(
        category=default
    )

    ranked = queryset.annotate(
        rank=Window(
            RowNumber(),
            partition_by=[F("category_id"), F("txn_type")],
            order_by=[F("date").desc(), F("created_at").desc()],
        )
    ).filter(rank__lte=settings.AI_MAX_EXAMPLES_PER_CATEGORY)

    groups = defaultdict(list)
    for txn in ranked:
        groups[(txn.category_id, txn.txn_type)].append(txn)
    return groups


def build_proposals(user, model: str, client) -> dict:
    """Dry run: scores the user's uncategorised rows and writes nothing."""
    default = get_default_category(user)
    categories = list(
        Category.objects.filter(user=user, is_default=False).prefetch_related("keywords")
    )
    names = {category.id: category.name for category in categories}
    targets, capped = _load_targets(user, default)

    result = {
        "model": model,
        "considered": len(targets),
        "proposed": 0,
        "skipped": 0,
        "capped": capped,
        "proposals": [],
    }
    if not targets or not categories:
        return result

    cipher = UserCipher(user)
    plain = {txn.id: _decrypt_fields(cipher, txn) for txn in targets}
    txn_types = {txn.txn_type for txn in targets}
    examples = _load_examples(user, default, txn_types)

    label_texts = {category.id: _label_text(category) for category in categories}
    target_texts = {txn.id: scoring.prepare_text(*plain[txn.id]) for txn in targets}
    example_texts = {
        key: [scoring.prepare_text(*_decrypt_fields(cipher, txn)) for txn in rows]
        for key, rows in examples.items()
    }

    # Embed every distinct text once, in one batched call set, then look vectors up by text.
    wanted = list(
        dict.fromkeys(
            [
                *label_texts.values(),
                *target_texts.values(),
                *(text for texts in example_texts.values() for text in texts),
            ]
        )
    )
    vectors = dict(zip(wanted, client.embed(model, wanted)))

    # A prototype per (txn_type, category): a credit is never compared against debit examples,
    # and a category that doesn't allow this direction isn't a candidate at all (so it can be
    # neither the proposal nor the runner-up).
    prototypes = {
        txn_type: {
            category.id: scoring.build_prototype(
                vectors[label_texts[category.id]],
                [vectors[text] for text in example_texts.get((category.id, txn_type), [])],
                settings.AI_BLEND_FULL_AT,
                settings.AI_BLEND_MAX_WEIGHT,
            )
            for category in categories
            if _allowed(category, txn_type)
        }
        for txn_type in txn_types
    }

    for txn in targets:
        decision = scoring.decide(
            vectors[target_texts[txn.id]],
            prototypes[txn.txn_type],
            settings.AI_MIN_SCORE,
            settings.AI_MIN_MARGIN,
        )
        result["proposals"].append(
            {
                "transaction": str(txn.id),
                "date": txn.date.isoformat(),
                "txn_type": txn.txn_type,
                "name": plain[txn.id][0],
                "amount": cipher.decrypt(bytes(txn.amount_enc), "txn.amount").decode(),
                "category": str(decision.category_id) if decision.category_id else None,
                "category_name": names.get(decision.category_id),
                "score": round(decision.score, 4) if decision.score is not None else None,
                "runner_up": str(decision.runner_up_id) if decision.runner_up_id else None,
                "runner_up_name": names.get(decision.runner_up_id),
                "runner_up_score": (
                    round(decision.runner_up_score, 4)
                    if decision.runner_up_score is not None
                    else None
                ),
                "decision": decision.decision,
            }
        )

    result["proposed"] = sum(row["decision"] == "propose" for row in result["proposals"])
    result["skipped"] = result["considered"] - result["proposed"]
    return result

def apply_decisions(user, decisions: list[dict]) -> dict:
    """Commit exactly what the user saw. Makes no Ollama call.

    `decisions` is [{"transaction": UUID, "category": UUID}], already shape-validated by the
    view's serializer. Each row is moved by ONE conditional UPDATE, so "still in Others and
    still mine" is checked atomically with the write: no race, and a human decision made in
    the meantime is never overwritten.
    """
    default = get_default_category(user)
    allowed = {c.id for c in Category.objects.filter(user=user, is_default=False)}
    applied, skipped = 0, []
    now = timezone.now()

    with db_transaction.atomic():
        for item in decisions:
            txn_id, category_id = item["transaction"], item["category"]
            if category_id not in allowed:
                skipped.append({"transaction": str(txn_id), "reason": "invalid_category"})
                continue
            updated = Transaction.objects.filter(
                pk=txn_id, user=user, category=default
            ).update(
                category_id=category_id,
                updated_at=now,  # .update() bypasses auto_now
            )
            if updated:
                applied += 1
            else:
                skipped.append({"transaction": str(txn_id), "reason": "not_in_others"})

    return {"applied": applied, "skipped": skipped}

