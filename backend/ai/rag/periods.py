"""Date phrases in a question set the period searched.

"What did I spend at the gym last month?" should search last month, not the period select.
Standard pipelines extract filters like this ("self-query"), usually with an LLM. Here it is
done with rules instead: deterministic, testable, instant, and no extra model call on the user's
machine. Only the phrases below are understood; anything else falls back to the select, and the
page always shows which period was searched.

Every result goes through insights.spec.validate_date_filter, so periods follow the same rules as
the dashboards.
"""

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from insights.spec import SpecError, validate_date_filter

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    # Short forms, except "may", which is the full name already.
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
# Longest first, so "sept" wins over "sep" and "june" over "jun".
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"


@dataclass(frozen=True)
class DetectedPeriod:
    date_filter: dict  # validated: {"preset": ...}, or a custom {"preset", "from", "to"}
    phrase: str  # exactly as written in the question
    remainder: str  # the question without the phrase, so "march" never matches narration text


def _custom(start: date, end: date) -> dict:
    return {"preset": "custom", "from": start.isoformat(), "to": end.isoformat()}


def _span(start: date, last_day: date, today: date) -> dict:
    """A calendar span that ends today if it is still running."""
    return _custom(start, min(last_day, today) if start <= today else last_day)


def _month(month: int, year: int | None, today: date) -> dict:
    if year is None:  # the most recent such month, up to today
        year = today.year if month <= today.month else today.year - 1
    start = date(year, month, 1)
    return _span(start, date(year, month, calendar.monthrange(year, month)[1]), today)


def _year(year: int, today: date) -> dict:
    return _span(date(year, 1, 1), date(year, 12, 31), today)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


Rule = Callable[[re.Match, date], dict]


def _rule(pattern: str, resolve: Rule) -> tuple[re.Pattern, Rule]:
    # Whole words only ("marching" is not "march"); any run of spaces between words.
    words = pattern.replace(" ", r"\s+")
    return re.compile(rf"\b{words}\b", re.IGNORECASE), resolve


_RULES = [
    _rule("this month", lambda m, today: {"preset": "this_month"}),
    _rule("(?:last|previous) month", lambda m, today: {"preset": "last_month"}),
    _rule("(?:last|past) (?:3|three) months", lambda m, today: {"preset": "last_3_months"}),
    _rule(
        "(?:(?:last|past) (?:12|twelve) months|past year)",
        lambda m, today: {"preset": "last_12_months"},
    ),
    _rule("this year", lambda m, today: {"preset": "this_year"}),
    _rule("last year", lambda m, today: _year(today.year - 1, today)),
    _rule(
        f"(?:in|during) (?P<month>{_MONTH})(?: (?P<year>{_YEAR}))?",
        lambda m, today: _month(
            _MONTHS[m["month"].lower()], int(m["year"]) if m["year"] else None, today
        ),
    ),
    # A bare month name only counts with a year after it: "may" is also an ordinary word.
    _rule(
        f"(?P<month>{_MONTH}) (?P<year>{_YEAR})",
        lambda m, today: _month(_MONTHS[m["month"].lower()], int(m["year"]), today),
    ),
    _rule(f"(?:in|during) (?P<year>{_YEAR})", lambda m, today: _year(int(m["year"]), today)),
    _rule("today", lambda m, today: _custom(today, today)),
    _rule("yesterday", lambda m, today: _custom(today - timedelta(1), today - timedelta(1))),
    _rule("this week", lambda m, today: _custom(_monday(today), today)),  # Monday to today
    _rule(
        "last week",
        lambda m, today: _custom(
            _monday(today) - timedelta(7), _monday(today) - timedelta(1)
        ),  # the previous Monday to Sunday
    ),
]


def detect_period(question: str, today: date) -> DetectedPeriod | None:
    """The first date phrase in the question, as a validated date filter; None if there is none.

    The phrase that starts first wins (the longer one on a tie). A phrase whose period fails
    validation, such as a year before 2000, is skipped.
    """
    found = [
        (match.start(), -len(match[0]), match, resolve)
        for pattern, resolve in _RULES
        for match in pattern.finditer(question)
    ]
    for _, _, match, resolve in sorted(found, key=lambda item: item[:2]):
        try:
            date_filter = validate_date_filter(resolve(match, today))
        except SpecError:
            continue
        remainder = f"{question[: match.start()]} {question[match.end() :]}"
        return DetectedPeriod(date_filter, match[0], " ".join(remainder.split()))
    return None
