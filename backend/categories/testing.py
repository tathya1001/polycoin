"""Helpers for tests in any app: finding categories and keywords by name.

Names and terms are encrypted since Phase 12.2, so the database can't be asked for
`name="Food"`. These look them up through their keyed hashes instead, which needs the owner's
key unlocked (creating a test user unlocks it)."""

from .models import Category, CategoryKeyword
from .services import category_by_name


def category_named(user, name: str) -> Category:
    found = category_by_name(user, name)
    if found is None:
        raise Category.DoesNotExist(f"No category named {name!r}.")
    return found


def has_category(user, name: str) -> bool:
    return category_by_name(user, name) is not None


def keyword_index(category: Category, term: str) -> bytes:
    return CategoryKeyword.term.index_for(category.user_id, term)


def keyword_named(category: Category, term: str) -> CategoryKeyword:
    return category.keywords.get(term_index=keyword_index(category, term))


def category_names(categories) -> list[str]:
    return [category.name for category in categories]
