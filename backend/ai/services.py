from collections import defaultdict

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from categories.models import Category, sort_categories, sort_keywords
from categories.services import get_default_category
from transactions.index import ids, keep, load_in_order, newest_first, rows_of
from transactions.models import Transaction
from vault.services import UserCipher

from . import scoring

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
    terms = [keyword.term for keyword in sort_keywords(category.keywords.all())]
    return f"{category.name}: {', '.join(terms)}" if terms else category.name


def decrypt_fields(cipher: UserCipher, txn: Transaction) -> tuple[str, str, str]:
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


def _load_targets(user, default: Category, every_row) -> tuple[list[Transaction], bool]:
    """Newest uncategorised rows, capped, and whether the cap bit. The category and date are
    encrypted (Phase 12.2), so the rows are chosen from the decrypted cores."""
    limit = settings.AI_MAX_RUN
    chosen = newest_first(keep(every_row, categories=[default.pk]))
    targets = load_in_order(Transaction.objects.filter(user=user), ids(chosen[:limit]))
    return targets, len(chosen) > limit


def _load_examples(user, default: Category, txn_types, every_row):
    """The user's own categorised rows, newest N per (category, txn_type).

    Every row outside Others is the user's decision: they either chose it, or approved the
    AI's proposal, and an approval is just as much theirs. So all of them teach the AI.
    """
    taken = defaultdict(list)
    for row in newest_first(keep(every_row, types=txn_types)):
        group = taken[(row.category_id, row.txn_type)]
        if row.category_id != default.pk and len(group) < settings.AI_MAX_EXAMPLES_PER_CATEGORY:
            group.append(row.id)
    rows = Transaction.objects.filter(user=user)
    return {key: load_in_order(rows, row_ids) for key, row_ids in taken.items() if row_ids}


def prepare_run(user) -> dict:
    """Everything the browser needs to embed and score the user's uncategorised rows with the
    user's own Ollama, so narrations go from here to that browser and nowhere else. Makes no
    Ollama call and writes nothing.

    Every distinct text appears once in `texts`; targets and candidates point into it by index.
    The response holds decrypted text: never log or persist it.
    """
    default = get_default_category(user)
    categories = sort_categories(
        Category.objects.filter(user=user, is_default=False).prefetch_related("keywords")
    )
    every_row = rows_of(user)
    targets, capped = _load_targets(user, default, every_row)

    result = {
        "considered": len(targets),
        "capped": capped,
        "thresholds": {
            "min_score": settings.AI_MIN_SCORE,
            "min_margin": settings.AI_MIN_MARGIN,
            "blend_full_at": settings.AI_BLEND_FULL_AT,
            "blend_max_weight": settings.AI_BLEND_MAX_WEIGHT,
        },
        "texts": [],
        "candidates": {},
        "targets": [],
    }
    if not targets or not categories:
        return result

    texts: dict[str, int] = {}

    def index(text: str) -> int:
        return texts.setdefault(text, len(texts))

    cipher = UserCipher(user)
    txn_types = sorted({txn.txn_type for txn in targets})
    examples = _load_examples(user, default, txn_types, every_row)
    labels = {category.id: index(_label_text(category)) for category in categories}

    for txn in targets:
        name, description, notes = decrypt_fields(cipher, txn)
        result["targets"].append(
            {
                "transaction": str(txn.id),
                "date": txn.date.isoformat(),
                "txn_type": txn.txn_type,
                "name": name,
                "amount": cipher.decrypt(bytes(txn.amount_enc), "txn.amount").decode(),
                "text": index(scoring.prepare_text(name, description, notes)),
            }
        )

    # One list per direction with only the categories allowed for it, so a credit is never
    # compared against debit examples and a disallowed category can be neither the proposal nor
    # the runner-up. Category order keeps ties deterministic. Duplicate example texts stay in
    # the list, because each one counts toward the blend weight.
    result["candidates"] = {
        txn_type: [
            {
                "category": str(category.id),
                "name": category.name,
                "label": labels[category.id],
                "examples": [
                    index(scoring.prepare_text(*decrypt_fields(cipher, txn)))
                    for txn in examples.get((category.id, txn_type), [])
                ],
            }
            for category in categories
            if _allowed(category, txn_type)
        ]
        for txn_type in txn_types
    }
    result["texts"] = list(texts)
    return result


def apply_decisions(user, decisions: list[dict]) -> dict:
    """Commit exactly what the user saw.

    `decisions` is [{"transaction": UUID, "category": UUID}], already shape-validated by the
    view's serializer. The rows are locked first and each is checked to be still in Others and
    still mine before it is changed, so a human decision made in the meantime is never
    overwritten. (The category is encrypted since Phase 12.2, so this can't be one conditional
    UPDATE any more; the row lock gives the same guarantee.)
    """
    default = get_default_category(user)
    allowed = {c.id for c in Category.objects.filter(user=user, is_default=False)}
    applied, skipped = 0, []
    now = timezone.now()

    with db_transaction.atomic():
        wanted = [item["transaction"] for item in decisions]
        rows = Transaction.objects.select_for_update().filter(user=user, pk__in=wanted).in_bulk()
        for item in decisions:
            txn_id, category_id = item["transaction"], item["category"]
            if category_id not in allowed:
                skipped.append({"transaction": str(txn_id), "reason": "invalid_category"})
                continue
            row = rows.get(txn_id)
            if row is None or row.category_id != default.pk:
                skipped.append({"transaction": str(txn_id), "reason": "not_in_others"})
                continue
            row.category_id = category_id
            row.updated_at = now
            row.save(update_fields=["updated_at"])  # save() adds the re-sealed core
            applied += 1

    return {"applied": applied, "skipped": skipped}

