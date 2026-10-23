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


def prepare_run(user) -> dict:
    """Everything the browser needs to embed and score the user's uncategorised rows with the
    user's own Ollama, so narrations go from here to that browser and nowhere else. Makes no
    Ollama call and writes nothing.

    Every distinct text appears once in `texts`; targets and candidates point into it by index.
    The response holds decrypted text: never log or persist it.
    """
    default = get_default_category(user)
    categories = list(
        Category.objects.filter(user=user, is_default=False).prefetch_related("keywords")
    )
    targets, capped = _load_targets(user, default)

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
    examples = _load_examples(user, default, txn_types)
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

