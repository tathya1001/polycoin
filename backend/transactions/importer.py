"""Bank-statement parser. Pure Python: no Django, no database.

Flow:  readers.read_statement -> detect_header -> (user may correct the mapping) -> parse_rows

Supported amount layouts, chosen from which columns are mapped:
  split   `debit` + `credit` columns. Some banks use "Withdrawal Amt." / "Deposit Amt."
          and other banks use "Debit" / "Credit"; exactly one is filled per row.
  typed   one `amount` column + a `type` (Dr/Cr) column.
  signed  one `amount` column, negative = money out.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_ROWS = 5000
HEADER_SCAN_ROWS = 30  # statements often have a logo / address block above the table

FIELDS = ("date", "description", "debit", "credit", "amount", "type", "balance")

# Normalised header text -> field. Matching is EXACT after normalisation, so
# "Value Dt" and "Chq./Ref.No." deliberately match nothing (we don't want them
# mistaken for the transaction date or the narration).
_SYNONYMS = {
    "date": ["date", "txn date", "tran date", "transaction date", "posting date"],
    "description": [
        "narration", "description", "particulars", "remarks", "details",
        "transaction remarks", "transaction details",
    ],
    "debit": [
        "debit", "dr", "debit amount", "debit amt", "withdrawal", "withdrawals",
        "withdrawal amt", "withdrawal amount",
    ],
    "credit": [
        "credit", "cr", "credit amount", "credit amt", "deposit", "deposits",
        "deposit amt", "deposit amount",
    ],
    "amount": ["amount", "txn amount", "transaction amount"],
    "type": ["dr cr", "cr dr", "type", "transaction type"],
    "balance": ["balance", "closing balance", "running balance", "available balance"],
}
_FIELD_BY_HEADER = {text: field for field, texts in _SYNONYMS.items() for text in texts}

_DEBIT_WORDS = {"dr", "debit", "d", "withdrawal"}
_CREDIT_WORDS = {"cr", "credit", "c", "deposit"}

# Day-first only. Guessing month-first would silently misread 05/01/2026.
_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
    "%d %b %Y", "%d-%b-%Y", "%d %b %y", "%d-%b-%y", "%d %B %Y", "%Y-%m-%d",
)
_TIME_SUFFIXES = ("", " %H:%M:%S", " %H:%M")

_IFSC = re.compile(r"[A-Za-z]{4}0[A-Za-z0-9]{6}")
_REFERENCE_LIKE = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9]*")
_NOISE_WORDS = {
    "upi", "dr", "cr", "imps", "neft", "rtgs", "ach", "nach", "pos", "ecom",
    "wdl", "tfr", "dep",  # bank prefixes: "WDL TFR UPI/DR/..."
}


class ImportFileError(ValueError):
    """The file or mapping as a whole is unusable (as opposed to one bad row)."""


class PasswordRequired(ImportFileError):
    """Encrypted file and no password supplied: the UI should ask for one."""


class WrongPassword(ImportFileError):
    """Encrypted file and the password didn't unlock it: the UI should ask again."""


class _SkipRow(Exception):
    """Blank line, wrapped narration, 'Opening Balance' label, footer..."""


# --- rows ---------------------------------------------------------------------

def is_blank(row) -> bool:
    return all(cell is None or str(cell).strip() == "" for cell in row)


# --- header detection ---------------------------------------------------------

def _norm(value) -> str:
    """'Withdrawal Amt.' -> 'withdrawal amt', 'Chq./Ref.No.' -> 'chq ref no'."""
    if value is None:
        return ""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def detect_header(rows) -> tuple[int | None, dict[str, int]]:
    """Find the header row in the first HEADER_SCAN_ROWS rows.

    Returns (row_index, {field: column_index}). The row recognising the most
    fields wins (earliest on ties). (None, {}) if nothing looks like a header.
    The mapping may be incomplete; parse_rows validates it, so a preview screen
    can show it and let the user fix the gaps."""
    best_index, best_mapping = None, {}
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for column, cell in enumerate(row):
            field = _FIELD_BY_HEADER.get(_norm(cell))
            if field and field not in mapping:  # first column wins if a header repeats
                mapping[field] = column
        if len(mapping) > len(best_mapping):
            best_index, best_mapping = index, mapping
    if len(best_mapping) < 2:  # one stray "Date" cell isn't a header
        return None, {}
    return best_index, best_mapping


def validate_mapping(mapping) -> dict[str, int]:
    """Clean a (possibly user-supplied) mapping and check it describes a usable layout."""
    clean: dict[str, int] = {}
    for field, column in mapping.items():
        if field not in FIELDS:
            raise ImportFileError(f"Unknown field: {field!r}.")
        try:
            clean[field] = int(column)
        except (TypeError, ValueError):
            raise ImportFileError(f"Column for {field!r} must be a number.") from None
        if clean[field] < 0:
            raise ImportFileError(f"Column for {field!r} can't be negative.")

    if "date" not in clean:
        raise ImportFileError("Map a date column.")
    if not (("debit" in clean and "credit" in clean) or "amount" in clean):
        raise ImportFileError("Map both debit and credit columns, or a single amount column.")
    return clean


def _layout(mapping: dict[str, int]) -> str:
    if "debit" in mapping and "credit" in mapping:
        return "split"
    return "typed" if "type" in mapping else "signed"


# --- cell parsing -------------------------------------------------------------

def parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = " ".join(str(value).split()) if value is not None else ""
    if not text:
        raise ValueError("Missing date.")
    for fmt in _DATE_FORMATS:
        for suffix in _TIME_SUFFIXES:
            try:
                return datetime.strptime(text, fmt + suffix).date()
            except ValueError:
                continue
    raise ValueError(f"Unrecognised date: {text!r}.")


def parse_amount(value) -> Decimal | None:
    """Cell -> Decimal (never float arithmetic). None for blank / '-'.
    Handles '1,234.50', '₹ 1,234.50', '(1,234.50)' and a trailing Cr/Dr."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))  # via str: Decimal(0.1) would carry binary noise
    else:
        text = str(value).strip()
        if text in ("", "-", "--"):
            return None
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative, text = True, text[1:-1]
        suffix = re.search(r"\s*\b(cr|dr)\.?$", text, re.IGNORECASE)
        if suffix:
            negative = negative or suffix.group(1).lower() == "dr"
            text = text[: suffix.start()]
        text = re.sub(r"(?i)₹|\brs\.?|\binr\b|,|\s", "", text)
        try:
            result = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"Not a valid amount: {value!r}.") from None
        if negative:
            result = -abs(result)
    if not result.is_finite():
        raise ValueError(f"Not a valid amount: {value!r}.")
    return result


def clean_name(description: str) -> str:
    """Short display name from a narration, e.g.
    'UPI/DR/412345678901/TASTYBITES/TSTB/tastybites@tstb' -> 'TASTYBITES'. A best-effort
    heuristic: users can rename any transaction afterwards."""
    text = re.sub(r"(?i)^(to|by)\s+transfer\s*-?\s*", "", description)
    for token in re.split(r"[/*]", text):
        # Drop noise words inside a piece too: "WDL TFR UPI" has nothing left, so it's skipped.
        token = " ".join(w for w in token.split() if w.lower() not in _NOISE_WORDS).strip(" -")
        if (
            not token
            or "@" in token
            or _IFSC.fullmatch(token)
            or (len(token) >= 6 and " " not in token and _REFERENCE_LIKE.fullmatch(token))
        ):
            continue
        return token[:60]
    return description[:60] or "Transaction"


# --- row parsing --------------------------------------------------------------

def _type_of(value) -> str:
    word = _norm(value)
    if word in _DEBIT_WORDS:
        return "debit"
    if word in _CREDIT_WORDS:
        return "credit"
    raise ValueError(f"Unknown Dr/Cr value: {value!r}.")


def _amount_and_type(cell, layout: str) -> tuple[Decimal, str] | None:
    """(positive amount, 'debit'|'credit'), or None when the row carries no amount."""
    if layout == "split":
        debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
        if debit and credit:  # a 0 in the unused column is fine; two real amounts aren't
            raise ValueError("Both debit and credit have a value.")
        if debit:
            return abs(debit), "debit"
        if credit:
            return abs(credit), "credit"
        return None

    amount = parse_amount(cell("amount"))
    if not amount:
        return None
    if layout == "typed":
        return abs(amount), _type_of(cell("type"))
    return abs(amount), "credit" if amount > 0 else "debit"


def _parse_row(row, mapping: dict[str, int], layout: str) -> dict:
    def cell(field):
        column = mapping.get(field)
        return row[column] if column is not None and column < len(row) else None

    date_error = None
    try:
        txn_date = parse_date(cell("date"))
    except ValueError as exc:
        txn_date, date_error = None, exc

    try:
        found = _amount_and_type(cell, layout)
    except ValueError:
        if txn_date is None:
            raise _SkipRow from None  # a footer / total line, not a transaction
        raise

    if txn_date is None:
        if found is None:
            raise _SkipRow  # wrapped narration, 'Opening Balance', blank date...
        raise ValueError(str(date_error))  # has an amount but no usable date: surface it
    if found is None:
        raise ValueError("No debit or credit amount.")
    amount, txn_type = found

    description = " ".join(str(cell("description") or "").split())
    return {
        "date": txn_date,
        "txn_type": txn_type,
        "amount": amount,
        "balance": parse_amount(cell("balance")),
        "description": description,
        "name": clean_name(description),
    }


def parse_rows(rows, header_index: int, mapping) -> tuple[list[dict], list[dict]]:
    """Rows below the header -> (parsed, errors).

    parsed: dicts ready for create_transaction (plus 'row', the sheet row number).
    errors: [{'row': n, 'reason': '...'}]. One bad row never aborts the rest.
    Raises ImportFileError if the mapping itself is unusable."""
    mapping = validate_mapping(mapping)
    layout = _layout(mapping)

    parsed, errors = [], []
    for index in range(header_index + 1, len(rows)):
        row = rows[index]
        if is_blank(row):
            continue
        number = index + 1
        try:
            item = _parse_row(row, mapping, layout)
        except _SkipRow:
            continue
        except ValueError as exc:
            errors.append({"row": number, "reason": str(exc)})
            continue
        item["row"] = number
        parsed.append(item)
    return parsed, errors
