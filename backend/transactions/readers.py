"""Statement file readers. Pure Python: no Django, no database.

Each reader turns one upload into rows of cell values for importer.detect_header and
importer.parse_rows. Row N of the file is rows[N-1]. Blank rows in the middle are kept (as [])
so error row numbers match what the user sees; trailing blank rows are dropped.

The format comes from the file's first bytes, and the extension must agree with them. PDFs never
reach the server: the import page turns them into a CSV table in the browser.
"""
import codecs
import csv
import io
import os
from zipfile import BadZipFile, is_zipfile

import msoffcrypto
import openpyxl
import xlrd
from openpyxl.utils.exceptions import InvalidFileException

from .importer import MAX_ROWS, ImportFileError, PasswordRequired, WrongPassword, is_blank

SNIFF_BYTES = 1024
CSV_SNIFF_CHARS = 16 * 1024

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # old Office files, and encrypted .xlsx
_PDF_MAGIC = b"%PDF-"
_MARKUP_STARTS = (b"<!doctype", b"<html", b"<table", b"<?xml")
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_CSV_DELIMITERS = ",;\t|"

SUPPORTED = "Only .xlsx, .xls, .csv and .pdf files are supported."


# --- format detection ---------------------------------------------------------

def _looks_like_text(head: bytes) -> bool:
    return head.startswith(_UTF16_BOMS) or b"\x00" not in head


def sniff_format(head: bytes, filename: str) -> str:
    """'xlsx', 'xls' or 'csv' from the first bytes of the file, checked against its extension."""
    extension = os.path.splitext(filename.lower())[1]
    if extension == ".pdf" or head.startswith(_PDF_MAGIC):
        raise ImportFileError("PDF statements are read in the browser. Upload them on the import page.")
    if extension not in (".xlsx", ".xls", ".csv"):
        raise ImportFileError(SUPPORTED)

    mismatch = ImportFileError(f"The file's content doesn't match its {extension} extension.")
    if head.startswith(_ZIP_MAGIC):
        if extension != ".xlsx":
            raise mismatch
        return "xlsx"
    if head.startswith(_OLE_MAGIC):
        if extension not in (".xlsx", ".xls"):
            raise mismatch
        return extension[1:]  # an encrypted .xlsx is an OLE container too
    if _looks_like_text(head) and extension in (".csv", ".xls"):
        # Some banks label a text or HTML export ".xls". Text is read as CSV; markup is refused
        # rather than parsed (a web page is a lot of untrusted surface for a table).
        if extension == ".xls" and head.lstrip().lower().startswith(_MARKUP_STARTS):
            raise ImportFileError(
                "This .xls file is really a web page. Open it in a spreadsheet program and save "
                "it as .xlsx or .csv."
            )
        return "csv"
    raise mismatch


def read_statement(file, filename: str, password: str | None = None) -> list[list]:
    """Rows of the statement's first sheet, whatever the format.

    `file` is a binary file-like object. `password` is only used if the file is encrypted;
    it is never stored or logged."""
    head = file.read(SNIFF_BYTES)
    file.seek(0)
    file_format = sniff_format(head, filename)
    if file_format == "xlsx":
        return read_xlsx(file, password)
    if file_format == "xls":
        return read_xls(file, password)
    return read_csv(file)


def _collect(raw_rows) -> list[list]:
    rows: list[list] = []
    blanks = 0
    for raw in raw_rows:
        if is_blank(raw):
            blanks += 1  # only materialised if a real row follows: trailing blanks are dropped
            continue
        rows.extend([] for _ in range(blanks))
        blanks = 0
        rows.append(list(raw))
        if len(rows) > MAX_ROWS:
            # Refuse rather than silently truncate: dropped rows = missing transactions.
            raise ImportFileError(f"Too many rows (limit {MAX_ROWS}). Split the statement.")
    return rows


# --- Office files ---------------------------------------------------------------
#
# The parsing libraries below read untrusted binary formats, and a damaged or hostile file can
# make them fail with almost any exception type (struct.error, AssertionError, IndexError...).
# Where that is the case the code catches Exception on purpose: a bad upload is a 400, never a 500.

def _office_file(file, label: str):
    try:
        return msoffcrypto.OfficeFile(file)
    except Exception as exc:
        raise ImportFileError(f"This isn't a valid {label} file.") from exc


def _decrypt(office, password: str | None, *, unlocked) -> io.BytesIO:
    """Decrypt a password-protected Office file into memory (nothing touches disk).
    `unlocked(buffer)` says whether the output is a real file, i.e. the password was right."""
    if not password:
        raise PasswordRequired("This file is password-protected.")

    decrypted = io.BytesIO()
    try:
        # No verify_password pre-check: it can reject the RIGHT password on files that
        # bank software (not a spreadsheet program) encrypted. Judge by the output instead.
        office.load_key(password=password)
        office.decrypt(decrypted)
    except (msoffcrypto.exceptions.InvalidKeyError, msoffcrypto.exceptions.DecryptionError) as exc:
        raise WrongPassword("That password is incorrect.") from exc
    except Exception as exc:
        raise ImportFileError("This file couldn't be decrypted.") from exc

    # A wrong key "decrypts" into noise; the right one yields a file the library can open.
    if not unlocked(decrypted):
        raise WrongPassword("That password is incorrect.")
    decrypted.seek(0)
    return decrypted


def read_xlsx(file, password: str | None = None) -> list[list]:
    # A password-protected .xlsx is an encrypted OLE container, not a zip: openpyxl can't open it.
    office = _office_file(file, ".xlsx")
    try:
        encrypted = office.is_encrypted()
    except Exception as exc:
        raise ImportFileError("This isn't a valid .xlsx file.") from exc
    if encrypted:
        file = _decrypt(office, password, unlocked=is_zipfile)
    else:
        file.seek(0)

    try:
        workbook = openpyxl.load_workbook(file, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        # ValueError also covers defusedxml's XML-bomb rejections.
        raise ImportFileError("This isn't a valid .xlsx file.") from exc

    try:
        return _collect(workbook.worksheets[0].iter_rows(min_row=1, values_only=True))
    except IndexError as exc:
        raise ImportFileError("The workbook has no sheets.") from exc
    finally:
        workbook.close()


class _EncryptedXls(ImportFileError):
    pass


def _open_xls(data: bytes):
    try:
        return xlrd.open_workbook(file_contents=data, on_demand=True)
    except xlrd.XLRDError as exc:
        # xlrd spots the encryption record itself; msoffcrypto's own check can crash on valid,
        # unencrypted files written by spreadsheet libraries, so xlrd decides.
        if "encrypted" in str(exc).lower():
            raise _EncryptedXls("This file is password-protected.") from exc
        raise ImportFileError("This isn't a valid .xls file.") from exc
    except Exception as exc:
        raise ImportFileError("This isn't a valid .xls file.") from exc


def _xls_opens(buffer) -> bool:
    try:
        _open_xls(buffer.getvalue()).release_resources()
    except ImportFileError:
        return False
    return True


def _xls_value(cell, datemode):
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode)
        except (ValueError, OverflowError):  # xlrd's date errors are ValueErrors
            return cell.value  # a broken date stays a number; parse_rows reports it
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)  # stored as 0/1; must not read as an amount
    return cell.value


def read_xls(file, password: str | None = None) -> list[list]:
    data = file.read()
    try:
        book = _open_xls(data)
    except _EncryptedXls:
        office = _office_file(io.BytesIO(data), ".xls")
        book = _open_xls(_decrypt(office, password, unlocked=_xls_opens).getvalue())
    try:
        if book.nsheets == 0:
            raise ImportFileError("The workbook has no sheets.")
        sheet = book.sheet_by_index(0)
        return _collect(
            [_xls_value(cell, book.datemode) for cell in sheet.row(index)]
            for index in range(sheet.nrows)
        )
    finally:
        book.release_resources()


# --- CSV ------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    """Byte-order mark first, then UTF-8, then the usual Windows code page."""
    if data.startswith(codecs.BOM_UTF8):
        encodings = ("utf-8-sig",)
    elif data.startswith(_UTF16_BOMS):
        encodings = ("utf-16",)
    else:
        encodings = ("utf-8", "cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("The file's text encoding isn't supported. Save it as UTF-8.")


def _dialect(text: str):
    sample = text[:CSV_SNIFF_CHARS]
    if len(text) > CSV_SNIFF_CHARS and "\n" in sample:
        sample = sample[: sample.rindex("\n")]  # whole lines only, or the sniffer guesses badly
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CSV_DELIMITERS)
    except csv.Error:
        return csv.excel  # one column, or no clear pattern: assume plain commas


def read_csv(file) -> list[list]:
    """Cells stay text (blank -> None); parse_date and parse_amount read text already."""
    text = _decode(file.read())
    if "\x00" in text:
        raise ImportFileError("This doesn't look like a text file.")
    reader = csv.reader(io.StringIO(text, newline=""), _dialect(text))
    try:
        return _collect([cell.strip() or None for cell in raw] for raw in reader)
    except csv.Error as exc:
        raise ImportFileError(f"This CSV file couldn't be read ({exc}).") from exc
