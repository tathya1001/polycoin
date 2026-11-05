"""Statement file builders shared by the test modules. Everything is built in memory."""
import io
from datetime import date, datetime

import xlwt


def make_xls(rows) -> bytes:
    """An old-format (.xls) workbook. date/datetime cells are written as real date cells."""
    book = xlwt.Workbook()
    sheet = book.add_sheet("Statement")
    date_style = xlwt.easyxf(num_format_str="DD/MM/YYYY")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is None:
                continue
            if isinstance(value, (date, datetime)):
                sheet.write(r, c, value, date_style)
            else:
                sheet.write(r, c, value)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# --- finding rows by their encrypted core (Phase 12.2) -----------------------------------------
# The database can't filter on a transaction's date, type, category or source any more, so tests
# ask transactions/index.py, as the app does. The owner's key must be unlocked.


def txns(user, *, data_source=None, txn_type=None, category=None, day=None, order="oldest"):
    """The user's transactions, filtered on their decrypted core, oldest (or newest) first."""
    from .index import keep, load_in_order, newest_first, oldest_first, rows_of
    from .models import Transaction

    rows = keep(
        rows_of(user),
        start=day,
        end=day,
        types=[txn_type] if txn_type else None,
        categories=[category.pk] if category is not None else None,
        sources=[data_source.pk] if data_source is not None else None,
    )
    rows = newest_first(rows) if order == "newest" else oldest_first(rows)
    return load_in_order(Transaction.objects.filter(user=user), [row.id for row in rows])


def rows_in(source):
    """The transactions held by this data source, oldest first."""
    return txns(source.user, data_source=source)
