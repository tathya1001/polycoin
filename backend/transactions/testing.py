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
