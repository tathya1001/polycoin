"""Statement file readers: format sniffing, CSV, old .xls, and .xlsx through the dispatcher.
Pure Python, no database. Every fixture is built in memory."""
import codecs
import io
from datetime import datetime

import openpyxl
import pytest

from transactions import readers
from transactions.importer import ImportFileError, PasswordRequired, WrongPassword
from transactions.readers import read_csv, read_statement, sniff_format
from transactions.testing import make_xls

ZIP = b"PK\x03\x04rest"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"
TEXT = b"Date,Narration,Debit\n"


def read(data: bytes, name: str, password=None):
    return read_statement(io.BytesIO(data), name, password)


# --- format sniffing ------------------------------------------------------------

@pytest.mark.parametrize(
    "head, name, expected",
    [
        (ZIP, "statement.xlsx", "xlsx"),
        (OLE, "statement.xlsx", "xlsx"),  # an encrypted .xlsx is an OLE container
        (OLE, "statement.xls", "xls"),
        (TEXT, "statement.csv", "csv"),
        (TEXT, "STATEMENT.CSV", "csv"),
        (TEXT, "statement.xls", "csv"),  # a text export labelled .xls
        (codecs.BOM_UTF16_LE + "Date".encode("utf-16-le"), "statement.csv", "csv"),
    ],
)
def test_sniff_format_accepts(head, name, expected):
    assert sniff_format(head, name) == expected


@pytest.mark.parametrize(
    "head, name, message",
    [
        (ZIP, "statement.csv", "doesn't match"),
        (ZIP, "statement.xls", "doesn't match"),
        (TEXT, "statement.xlsx", "doesn't match"),
        (b"\x00\x01binary", "statement.csv", "doesn't match"),
        (b"<html><table>", "statement.xls", "web page"),
        (b"  <!DOCTYPE html>", "statement.xls", "web page"),
        (b"%PDF-1.7", "statement.pdf", "browser"),
        (b"%PDF-1.7", "statement.csv", "browser"),
        (TEXT, "statement.docx", "Only .xlsx"),
        (TEXT, "statement", "Only .xlsx"),
    ],
)
def test_sniff_format_refuses(head, name, message):
    with pytest.raises(ImportFileError, match=message):
        sniff_format(head, name)


# --- CSV ------------------------------------------------------------------------

def test_csv_cells_are_text_and_blanks_are_none():
    rows = read(b"Date,Narration,Debit,Credit\n01/04/2026, Coffee ,10.50,\n", "s.csv")
    assert rows == [["Date", "Narration", "Debit", "Credit"], ["01/04/2026", "Coffee", "10.50", None]]


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_csv_delimiter_is_detected(delimiter):
    lines = [["Date", "Narration", "Debit"], ["01/04/2026", "Coffee, large", "10"]]
    data = "\n".join(delimiter.join(line) for line in lines).encode()
    assert read(data, "s.csv")[1] == ["01/04/2026", "Coffee, large", "10"]


def test_csv_quoted_commas_and_line_breaks_stay_in_one_cell():
    data = b'Date,Narration,Debit\n01/04/2026,"UPI/TASTYBITES, CAFE\nSECOND LINE","1,250.00"\n'
    assert read(data, "s.csv")[1] == ["01/04/2026", "UPI/TASTYBITES, CAFE\nSECOND LINE", "1,250.00"]


def test_csv_blank_rows_in_the_middle_are_kept_and_trailing_ones_dropped():
    rows = read(b"Example Bank\n\n,,\nDate,Debit\n01/04/2026,10\n\n\n", "s.csv")
    assert rows == [["Example Bank"], [], [], ["Date", "Debit"], ["01/04/2026", "10"]]


def test_csv_utf8_bom_is_not_part_of_the_first_header():
    assert read(codecs.BOM_UTF8 + TEXT, "s.csv")[0][0] == "Date"


def test_csv_utf16_with_bom():
    data = "Date\tNarration\n01/04/2026\tCafé\n".encode("utf-16")
    assert read(data, "s.csv") == [["Date", "Narration"], ["01/04/2026", "Café"]]


def test_csv_falls_back_to_windows_code_page():
    data = "Date,Narration\n01/04/2026,Café €5\n".encode("cp1252")
    assert read(data, "s.csv")[1] == ["01/04/2026", "Café €5"]


def test_csv_undecodable_text_is_refused():
    with pytest.raises(ImportFileError, match="encoding"):
        read_csv(io.BytesIO(b"Date,Narration\n\x81\x8d\x8f\n"))


def test_csv_nul_bytes_are_refused():
    with pytest.raises(ImportFileError, match="text file"):
        read_csv(io.BytesIO(b"Date,Narration\n01/04/2026,Co\x00ffee\n"))


def test_csv_single_column_falls_back_to_commas():
    assert read(b"Date\n01/04/2026\n", "s.csv") == [["Date"], ["01/04/2026"]]


def test_csv_text_in_an_xls_file_is_read_as_csv():
    data = b"Date\tNarration\tDebit\n01/04/2026\tCoffee\t10\n"
    assert read(data, "statement.xls")[1] == ["01/04/2026", "Coffee", "10"]


def test_too_many_rows_is_refused_not_truncated(monkeypatch):
    monkeypatch.setattr(readers, "MAX_ROWS", 3)
    with pytest.raises(ImportFileError, match="Too many rows"):
        read(b"a\nb\nc\nd\n", "s.csv")


# --- .xlsx through the dispatcher -------------------------------------------------

def test_xlsx_is_read_through_read_statement():
    workbook = openpyxl.Workbook()
    for row in (["Date", "Debit"], [], ["01/04/2026", 10]):
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    assert read(buffer.getvalue(), "statement.xlsx") == [["Date", "Debit"], [], ["01/04/2026", 10]]


@pytest.mark.parametrize("name", ["statement.xlsx", "statement.xls"])
def test_damaged_ole_container_is_refused_not_crashed(name):
    with pytest.raises(ImportFileError):
        read(OLE + b"\x00" * 600, name)


# --- old .xls -------------------------------------------------------------------

XLS_ROWS = [
    ["Example Bank"],
    [],
    ["Date", "Narration", "Debit", "Credit", "Flag"],
    [datetime(2026, 4, 1), "UPI/TASTYBITES", 250.5, None, True],
    ["02/04/2026", "NEFT ACME LTD", None, 5000, False],
]


def test_xls_reads_dates_numbers_text_and_blanks():
    rows = read(make_xls(XLS_ROWS), "statement.xls")

    assert rows[0] == ["Example Bank", None, None, None, None]  # padded to the sheet's width
    assert rows[1] == []  # blank row in the middle kept, so row numbers match the sheet
    assert rows[2] == ["Date", "Narration", "Debit", "Credit", "Flag"]
    assert rows[3] == [datetime(2026, 4, 1), "UPI/TASTYBITES", 250.5, None, True]
    assert rows[4] == ["02/04/2026", "NEFT ACME LTD", None, 5000.0, False]


def test_damaged_xls_is_refused():
    data = make_xls(XLS_ROWS)
    damaged = data[:600] + b"\xff" * (len(data) - 600)
    with pytest.raises(ImportFileError):
        read(damaged, "statement.xls")


def test_xls_too_many_rows_is_refused(monkeypatch):
    monkeypatch.setattr(readers, "MAX_ROWS", 3)
    with pytest.raises(ImportFileError, match="Too many rows"):
        read(make_xls([["a"], ["b"], ["c"], ["d"]]), "statement.xls")


ENCRYPTED_XLS = OLE + b"stand-in for an encrypted workbook"


class FakeEncryptedOffice:
    """Nothing can create an encrypted .xls in a test (msoffcrypto only encrypts .xlsx), so both
    ends are faked: xlrd reports the stand-in bytes as encrypted, exactly as it does for a real
    file, and decryption with the right password yields a real workbook, with any other noise
    (as a wrong RC4 key does)."""

    password = "Secret#123"
    plain = make_xls(XLS_ROWS)

    def __init__(self, file):
        self.key = None

    def load_key(self, password):
        self.key = password

    def decrypt(self, out):
        out.write(self.plain if self.key == self.password else b"\x13\x37" * 2048)


@pytest.fixture
def encrypted_xls(monkeypatch):
    real_open = readers.xlrd.open_workbook

    def open_workbook(*, file_contents, **kwargs):
        if file_contents == ENCRYPTED_XLS:
            raise readers.xlrd.XLRDError("Workbook is encrypted")
        return real_open(file_contents=file_contents, **kwargs)

    monkeypatch.setattr(readers.xlrd, "open_workbook", open_workbook)
    monkeypatch.setattr(readers.msoffcrypto, "OfficeFile", FakeEncryptedOffice)
    return ENCRYPTED_XLS


def test_encrypted_xls_without_password_asks_for_one(encrypted_xls):
    with pytest.raises(PasswordRequired):
        read(encrypted_xls, "statement.xls")


def test_encrypted_xls_with_wrong_password(encrypted_xls):
    with pytest.raises(WrongPassword):
        read(encrypted_xls, "statement.xls", password="nope")


def test_encrypted_xls_with_right_password(encrypted_xls):
    rows = read(encrypted_xls, "statement.xls", password=FakeEncryptedOffice.password)
    assert rows[3][1] == "UPI/TASTYBITES"
