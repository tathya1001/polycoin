"""Date phrases in a question, table-driven with a fixed `today` (like the spec tests)."""

from datetime import date

import pytest

from ai.rag.periods import detect_period

TODAY = date(2026, 2, 10)  # a Tuesday


def custom(start: str, end: str) -> dict:
    return {"preset": "custom", "from": start, "to": end}


@pytest.mark.parametrize(
    "question, expected, phrase",
    [
        ("gym this month", {"preset": "this_month"}, "this month"),
        ("gym last month", {"preset": "last_month"}, "last month"),
        ("gym in the previous month", {"preset": "last_month"}, "previous month"),
        ("food over the last 3 months", {"preset": "last_3_months"}, "last 3 months"),
        ("food in the past three months", {"preset": "last_3_months"}, "past three months"),
        ("rent for the last 12 months", {"preset": "last_12_months"}, "last 12 months"),
        ("rent over the past twelve months", {"preset": "last_12_months"}, "past twelve months"),
        ("rent in the past year", {"preset": "last_12_months"}, "past year"),
        ("salary this year", {"preset": "this_year"}, "this year"),
        ("salary last year", custom("2025-01-01", "2025-12-31"), "last year"),
        ("travel in 2025", custom("2025-01-01", "2025-12-31"), "in 2025"),
        ("travel during 2026", custom("2026-01-01", "2026-02-10"), "during 2026"),  # runs to today
        ("fuel in March", custom("2025-03-01", "2025-03-31"), "in March"),  # the most recent March
        ("fuel in February", custom("2026-02-01", "2026-02-10"), "in February"),  # this month
        ("fuel in January", custom("2026-01-01", "2026-01-31"), "in January"),
        ("fuel in sept", custom("2025-09-01", "2025-09-30"), "in sept"),
        ("fuel in May", custom("2025-05-01", "2025-05-31"), "in May"),
        ("rent March 2025", custom("2025-03-01", "2025-03-31"), "March 2025"),
        ("rent in March 2024", custom("2024-03-01", "2024-03-31"), "in March 2024"),
        ("coffee today", custom("2026-02-10", "2026-02-10"), "today"),
        ("coffee yesterday", custom("2026-02-09", "2026-02-09"), "yesterday"),
        ("coffee this week", custom("2026-02-09", "2026-02-10"), "this week"),  # Monday to today
        ("coffee last week", custom("2026-02-02", "2026-02-08"), "last week"),  # Monday to Sunday
        ("GYM LAST   MONTH", {"preset": "last_month"}, "LAST   MONTH"),  # any case, any spaces
    ],
)
def test_every_phrase_in_d23(question, expected, phrase):
    detected = detect_period(question, TODAY)
    assert detected.date_filter == expected
    assert detected.phrase == phrase


def test_last_month_asked_in_january_is_december_of_the_year_before():
    assert detect_period("last month", date(2026, 1, 15)).date_filter == {"preset": "last_month"}
    assert detect_period("in December", date(2026, 1, 15)).date_filter == custom(
        "2025-12-01", "2025-12-31"
    )


def test_a_leap_year_february_ends_on_the_29th():
    assert detect_period("in Feb 2024", TODAY).date_filter == custom("2024-02-01", "2024-02-29")


@pytest.mark.parametrize(
    "question",
    [
        "marching band",  # whole words only
        "may I see my fuel spends",  # "may" alone is an ordinary word
        "lastmonth",
        "this weekend",
        "flat 2104 rent",  # a bare number is not a year
        "what do I pay for the gym",
        "",
    ],
)
def test_no_phrase_means_no_period(question):
    assert detect_period(question, TODAY) is None


def test_the_phrase_that_comes_first_wins():
    detected = detect_period("last week, or else last month", TODAY)
    assert detected.phrase == "last week"


def test_a_year_outside_the_phase_5_range_is_skipped():
    assert detect_period("rent in 1999", TODAY) is None
    assert detect_period("rent in 1999 or this month", TODAY).date_filter == {
        "preset": "this_month"
    }


def test_the_remainder_is_the_question_without_the_phrase():
    assert detect_period("What did I spend at the gym last month?", TODAY).remainder == (
        "What did I spend at the gym ?"
    )
    assert detect_period("in March 2025 rent", TODAY).remainder == "rent"
