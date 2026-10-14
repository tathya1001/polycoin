from .colors import CATEGORY_COLORS, OTHERS_COLOR
from .models import Category, CategoryKeyword

DEFAULT_CATEGORY = "Others"
SEED_CATEGORIES = [
    DEFAULT_CATEGORY, "Food", "Groceries", "Transport", "Shopping", "Bills",
    "Rent", "Salary", "Transfer", "Entertainment", "Health",
]

# Starter vocabulary, copied into each user's own CategoryKeyword rows at registration. After
# that the user's rows are the single source of truth: they can add and delete freely, and
# nothing here is read again. Keyed by lower-cased category name. English / India-flavoured.
DEFAULT_KEYWORDS = {
    "food": ["restaurant", "food delivery", "cafe", "dining", "takeaway", "lunch"],
    "groceries": ["supermarket", "grocery", "vegetables", "fruits", "provisions", "milk"],
    "transport": ["taxi", "cab", "metro", "bus", "train", "fuel", "petrol", "parking"],
    "shopping": ["online shopping", "clothes", "electronics", "footwear", "mall"],
    "bills": ["electricity", "water", "mobile recharge", "internet", "gas", "utility bill"],
    "rent": ["house rent", "rent payment", "landlord"],
    "salary": ["salary credit", "payroll", "income"],
    "transfer": ["bank transfer", "money transfer", "sent to friend", "self transfer"],
    "entertainment": ["movies", "streaming", "music", "concert", "games"],
    "health": ["hospital", "pharmacy", "doctor", "medicine", "insurance"],
}


def _seed_color(index: int) -> str:
    """Seed categories after "Others" take the palette in order: index 1 gets the first colour."""
    return CATEGORY_COLORS[(index - 1) % len(CATEGORY_COLORS)]


def seed_default_categories(user) -> None:
    """Idempotent: re-running (or racing) never duplicates or errors.

    Only meant for a new user. Re-running it would bring back starter keywords the user
    has since deleted.
    """
    Category.objects.bulk_create(
        [
            Category(
                user=user,
                name=name,
                is_default=(name == DEFAULT_CATEGORY),
                color=OTHERS_COLOR if name == DEFAULT_CATEGORY else _seed_color(index),
            )
            for index, name in enumerate(SEED_CATEGORIES)
        ],
        ignore_conflicts=True,
    )
    # bulk_create(ignore_conflicts=True) doesn't return usable ids, so read the rows back.
    by_name = {c.name.lower(): c for c in Category.objects.filter(user=user)}
    CategoryKeyword.objects.bulk_create(
        [
            CategoryKeyword(category=by_name[name], term=term)
            for name, terms in DEFAULT_KEYWORDS.items()
            if name in by_name
            for term in terms
        ],
        ignore_conflicts=True,
    )


def get_default_category(user) -> Category:
    """What every imported transaction starts as."""
    return Category.objects.get(user=user, is_default=True)
