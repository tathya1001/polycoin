"""What a data source held on a given day.

Pure Python, like the engine. A statement gives the balance after each transaction, but rows
only carry a date, so the last balance of a day has to be worked out. Each source then keeps its
balance until a later row changes it, and a total is the sum across sources: a source with no
transactions this month still holds its money.
"""

from bisect import bisect_right
from collections.abc import Iterable
from datetime import date
from decimal import Decimal


def _starting_balance(row: dict) -> Decimal:
    if row["txn_type"] == "debit":
        return row["balance"] + row["amount"]
    return row["balance"] - row["amount"]


def closing_row(rows: list[dict]) -> dict | None:
    """The row that ends one day of one source, or None if no row has a balance.

    Each row starts from the balance of the row before it, so the last row is the one whose
    balance no other row starts from. This also holds for a statement listed newest first, where
    the order of import would give the wrong answer. If the rows don't settle it (money in and
    out again leaves two candidates), the row listed last wins, so `rows` come in stored order.
    """
    known = [row for row in rows if row["balance"] is not None]
    if len(known) < 2:
        return known[0] if known else None
    starts = {_starting_balance(row) for row in known}
    last = [row for row in known if row["balance"] not in starts]
    return (last or known)[-1]


def closing_balance(rows: list[dict]) -> Decimal | None:
    """The latest balance of each source in `rows`, added up. None if no row has a balance."""
    return BalanceBook(rows).at(date.max)


class BalanceBook:
    """Every source's balance at the end of each day it has rows, for looking up any day.

    `openings` holds each source's balance before the first row here. `keys` limits the sources
    a total covers, for a panel showing only some of them. `names` gives each source's label.
    Rows are dicts with the keys date, amount, txn_type and balance, plus source_key when there
    can be more than one source.
    """

    def __init__(
        self,
        rows: list[dict],
        openings: dict[str, Decimal] | None = None,
        keys: Iterable[str] | None = None,
        names: dict[str, str] | None = None,
    ):
        by_day: dict[str, dict[date, list[dict]]] = {}
        for row in rows:
            if row["balance"] is not None:
                source = by_day.setdefault(row.get("source_key"), {})
                source.setdefault(row["date"], []).append(row)

        self.openings = openings or {}
        self.keys = frozenset(keys) if keys is not None else frozenset(by_day) | set(self.openings)
        self.names = names or {}
        self._days = {key: sorted(days) for key, days in by_day.items()}
        self._balances = {
            key: [closing_row(days[day])["balance"] for day in self._days[key]]
            for key, days in by_day.items()
        }

    def of(self, key: str, day: date) -> Decimal | None:
        """One source's balance at the end of `day`: its latest row up to then."""
        days = self._days.get(key, ())
        index = bisect_right(days, day)
        return self._balances[key][index - 1] if index else self.openings.get(key)

    def at(self, day: date, keys: Iterable[str] | None = None) -> Decimal | None:
        """The total across sources at the end of `day`. None if none had a balance yet."""
        known = [self.of(key, day) for key in (self.keys if keys is None else keys)]
        values = [value for value in known if value is not None]
        return sum(values, Decimal(0)) if values else None
