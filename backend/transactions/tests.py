from datetime import date
from decimal import Decimal

import pytest
from cryptography.exceptions import InvalidTag
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import Client

from accounts.models import User
from categories.models import Category
from categories.services import get_default_category, seed_default_categories
from transactions.models import Transaction
from transactions.services import create_transaction
from vault.services import UserCipher, create_user_key

pytestmark = pytest.mark.django_db

NAME = "TASTYBITES-MARKER"
DESCRIPTION = "UPI/TASTYBITES/DESC-MARKER"


def make_user(email):
    user = User.objects.create_user(email=email, password="x-Str0ng-pass!")
    create_user_key(user)
    seed_default_categories(user)
    return user


def make_txn(user, **overrides):
    values = dict(
        date=date(2026, 1, 5), txn_type="debit", name=NAME, description=DESCRIPTION,
        amount=Decimal("4.50"), balance=Decimal("100.00"),
        category=get_default_category(user),
    )
    values.update(overrides)
    return create_transaction(UserCipher(user), user, **values)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


# --- encryption proof ---------------------------------------------------------

def test_plaintext_never_appears_in_the_raw_row(alice):
    txn = make_txn(alice)
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM transactions_transaction WHERE id = %s", [txn.id])
        row = cursor.fetchone()

    for value in row:
        raw = bytes(value) if isinstance(value, (bytes, memoryview)) else str(value).encode()
        for secret in (NAME, DESCRIPTION, "4.50", "100.00"):
            assert secret.encode() not in raw


def test_admin_changelist_shows_no_plaintext(alice):
    make_txn(alice)
    admin = User.objects.create_superuser(email="admin@example.com", password="x-Str0ng-pass!")
    client = Client()
    client.force_login(admin)

    response = client.get("/admin/transactions/transaction/")

    assert response.status_code == 200
    assert NAME.encode() not in response.content
    assert DESCRIPTION.encode() not in response.content


def test_owner_can_decrypt_every_field(alice):
    txn = make_txn(alice)
    cipher = UserCipher(alice)
    assert cipher.decrypt(bytes(txn.name_enc), "txn.name").decode() == NAME
    assert cipher.decrypt(bytes(txn.description_enc), "txn.description").decode() == DESCRIPTION
    assert Decimal(cipher.decrypt(bytes(txn.amount_enc), "txn.amount").decode()) == Decimal("4.50")
    assert Decimal(cipher.decrypt(bytes(txn.balance_enc), "txn.balance").decode()) == Decimal("100.00")


def test_wrong_context_cannot_decrypt(alice):
    txn = make_txn(alice)
    with pytest.raises(InvalidTag):
        UserCipher(alice).decrypt(bytes(txn.name_enc), "txn.description")


def test_another_user_cannot_decrypt(alice, bob):
    txn = make_txn(alice)
    with pytest.raises(InvalidTag):
        UserCipher(bob).decrypt(bytes(txn.name_enc), "txn.name")


# --- create_transaction -------------------------------------------------------

def test_balance_is_optional(alice):
    txn = make_txn(alice, balance=None)
    assert txn.balance_enc is None


def test_amount_must_be_positive(alice):
    with pytest.raises(ValueError):
        make_txn(alice, amount=Decimal("-5"))


# --- dedupe -------------------------------------------------------------------

def test_same_transaction_twice_is_rejected_for_one_user(alice):
    make_txn(alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_txn(alice)


def test_decimal_formatting_does_not_defeat_dedupe(alice):
    make_txn(alice, amount=Decimal("4.5"))
    with pytest.raises(IntegrityError), transaction.atomic():
        make_txn(alice, amount=Decimal("4.50"))


def test_different_balance_is_not_a_duplicate(alice):
    make_txn(alice, balance=Decimal("100.00"))
    make_txn(alice, balance=Decimal("95.50"))  # two identical coffees, same day
    assert Transaction.objects.filter(user=alice).count() == 2


def test_two_users_can_hold_the_same_transaction(alice, bob):
    a, b = make_txn(alice), make_txn(bob)
    assert a.fingerprint != b.fingerprint


# --- category protection ------------------------------------------------------

def test_category_in_use_cannot_be_deleted(alice):
    txn = make_txn(alice)
    with pytest.raises(ProtectedError):
        txn.category.delete()


# --- API ----------------------------------------------------------------------

from rest_framework.test import APIClient  # noqa: E402

URL = "/api/transactions/"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_unauthenticated_gets_401():
    assert APIClient().get(URL).status_code == 401


def test_owner_lists_decrypted_plaintext(alice):
    make_txn(alice)
    response = client_for(alice).get(URL)

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["name"] == NAME
    assert row["description"] == DESCRIPTION
    assert row["amount"] == "4.50"
    assert row["balance"] == "100.00"


def test_list_only_contains_own_transactions(alice, bob):
    make_txn(alice)
    make_txn(bob)
    assert client_for(alice).get(URL).json()["count"] == 1


def test_other_users_transaction_is_404_for_get_patch_delete(alice, bob):
    txn = make_txn(bob)
    client = client_for(alice)
    url = f"{URL}{txn.id}/"

    assert client.get(url).status_code == 404
    assert client.patch(url, {"name": "hacked"}, format="json").status_code == 404
    assert client.delete(url).status_code == 404

    txn.refresh_from_db()
    assert UserCipher(bob).decrypt(bytes(txn.name_enc), "txn.name").decode() == NAME


def test_patch_with_another_users_category_is_400(alice, bob):
    txn = make_txn(alice)
    foreign = get_default_category(bob)

    response = client_for(alice).patch(f"{URL}{txn.id}/", {"category": str(foreign.id)}, format="json")

    assert response.status_code == 400
    txn.refresh_from_db()
    assert txn.category == get_default_category(alice)


def test_patch_name_round_trips_and_is_re_encrypted(alice):
    txn = make_txn(alice)
    old_blob = bytes(txn.name_enc)

    response = client_for(alice).patch(f"{URL}{txn.id}/", {"name": "Tastybites Dinner"}, format="json")

    assert response.status_code == 200
    assert response.json()["name"] == "Tastybites Dinner"
    txn.refresh_from_db()
    assert bytes(txn.name_enc) != old_blob
    assert b"Tastybites Dinner" not in bytes(txn.name_enc)


def test_patch_own_category_works(alice):
    txn = make_txn(alice)
    food = alice.category_set.get(name="Food")

    response = client_for(alice).patch(f"{URL}{txn.id}/", {"category": str(food.id)}, format="json")

    assert response.status_code == 200
    txn.refresh_from_db()
    assert txn.category == food


# --- notes --------------------------------------------------------------------

NOTE = "NOTE-MARKER dinner with Rahul"


def set_notes(user, txn, notes):
    return client_for(user).patch(f"{URL}{txn.id}/", {"notes": notes}, format="json")


def test_a_new_transaction_has_no_notes(alice):
    txn = make_txn(alice)

    assert txn.notes_enc is None
    assert client_for(alice).get(f"{URL}{txn.id}/").json()["notes"] == ""


def test_notes_round_trip_and_are_stored_encrypted(alice):
    txn = make_txn(alice)

    response = set_notes(alice, txn, NOTE)

    assert response.status_code == 200
    assert response.json()["notes"] == NOTE
    assert client_for(alice).get(URL).json()["results"][0]["notes"] == NOTE
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM transactions_transaction WHERE id = %s", [txn.id])
        row = cursor.fetchone()
    for value in row:
        raw = bytes(value) if isinstance(value, (bytes, memoryview)) else str(value).encode()
        assert b"NOTE-MARKER" not in raw


def test_admin_changelist_shows_no_plaintext_notes(alice):
    set_notes(alice, make_txn(alice), NOTE)
    admin = User.objects.create_superuser(email="admin@example.com", password="x-Str0ng-pass!")
    client = Client()
    client.force_login(admin)

    response = client.get("/admin/transactions/transaction/")

    assert response.status_code == 200
    assert b"NOTE-MARKER" not in response.content


def test_notes_are_bound_to_their_own_field_and_owner(alice, bob):
    txn = make_txn(alice)
    set_notes(alice, txn, NOTE)
    txn.refresh_from_db()

    assert UserCipher(alice).decrypt(bytes(txn.notes_enc), "txn.notes").decode() == NOTE
    with pytest.raises(InvalidTag):
        UserCipher(alice).decrypt(bytes(txn.notes_enc), "txn.name")  # wrong field
    with pytest.raises(InvalidTag):
        UserCipher(bob).decrypt(bytes(txn.notes_enc), "txn.notes")  # wrong owner


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_note_clears_it_back_to_null(alice, blank):
    txn = make_txn(alice)
    set_notes(alice, txn, NOTE)

    response = set_notes(alice, txn, blank)

    assert response.status_code == 200
    assert response.json()["notes"] == ""
    txn.refresh_from_db()
    assert txn.notes_enc is None


def test_a_note_is_limited_to_500_characters(alice):
    txn = make_txn(alice)
    set_notes(alice, txn, "short")

    too_long = set_notes(alice, txn, "x" * 501)
    exactly = set_notes(alice, txn, "x" * 500)

    assert too_long.status_code == 400
    assert exactly.status_code == 200


def test_editing_notes_never_changes_the_fingerprint(alice):
    txn = make_txn(alice)
    before = bytes(txn.fingerprint)

    set_notes(alice, txn, NOTE)

    txn.refresh_from_db()
    assert bytes(txn.fingerprint) == before


def test_editing_other_fields_leaves_the_note_alone(alice):
    txn = make_txn(alice)
    set_notes(alice, txn, NOTE)

    client_for(alice).patch(f"{URL}{txn.id}/", {"name": "Tastybites Dinner"}, format="json")

    assert client_for(alice).get(f"{URL}{txn.id}/").json()["notes"] == NOTE


def test_another_users_transaction_notes_cannot_be_edited(alice, bob):
    txn = make_txn(bob)

    assert set_notes(alice, txn, "hacked").status_code == 404
    txn.refresh_from_db()
    assert txn.notes_enc is None


def test_bank_facts_can_be_edited(alice):
    txn = make_txn(alice)

    response = client_for(alice).patch(
        f"{URL}{txn.id}/",
        {"amount": "999.5", "balance": "1.00", "date": "2000-01-01", "txn_type": "credit"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["amount"], body["balance"], body["date"], body["txn_type"]) == (
        "999.50", "1.00", "2000-01-01", "credit",
    )
    txn.refresh_from_db()
    assert b"999.50" not in bytes(txn.amount_enc)  # still encrypted at rest


def test_editing_keeps_the_original_fingerprint(alice):
    txn = make_txn(alice)
    original = bytes(txn.fingerprint)

    client_for(alice).patch(f"{URL}{txn.id}/", {"amount": "1.00", "date": "2000-01-01"}, format="json")

    txn.refresh_from_db()
    assert bytes(txn.fingerprint) == original  # re-importing the statement must still dedupe


def test_balance_can_be_cleared(alice):
    txn = make_txn(alice)
    client_for(alice).patch(f"{URL}{txn.id}/", {"balance": None}, format="json")
    txn.refresh_from_db()
    assert txn.balance_enc is None


def test_invalid_amounts_and_types_are_400(alice):
    txn = make_txn(alice)
    client = client_for(alice)
    url = f"{URL}{txn.id}/"
    assert client.patch(url, {"amount": "0"}, format="json").status_code == 400
    assert client.patch(url, {"amount": "-5"}, format="json").status_code == 400
    assert client.patch(url, {"amount": "abc"}, format="json").status_code == 400
    assert client.patch(url, {"txn_type": "sideways"}, format="json").status_code == 400


def test_put_is_not_allowed(alice):
    txn = make_txn(alice)
    assert client_for(alice).put(f"{URL}{txn.id}/", {}, format="json").status_code == 405


def test_owner_can_delete(alice):
    txn = make_txn(alice)
    assert client_for(alice).delete(f"{URL}{txn.id}/").status_code == 204
    assert not Transaction.objects.filter(id=txn.id).exists()


def test_filters(alice):
    food = alice.category_set.get(name="Food")
    make_txn(alice, date=date(2026, 1, 5), txn_type="debit", description="a")
    make_txn(alice, date=date(2026, 2, 10), txn_type="credit", description="b", category=food)
    client = client_for(alice)

    def count(query):
        return client.get(URL + query).json()["count"]

    assert count("?type=credit") == 1
    assert count("?from=2026-02-01") == 1
    assert count("?to=2026-01-31") == 1
    assert count(f"?category={food.id}") == 1
    assert count("?type=debit&from=2026-01-01&to=2026-12-31") == 1


def test_bad_filter_values_are_400_not_500(alice):
    client = client_for(alice)
    assert client.get(URL + "?from=nope").status_code == 400
    assert client.get(URL + "?type=sideways").status_code == 400
    assert client.get(URL + "?category=nope").status_code == 400


# --- import endpoints ---------------------------------------------------------

import io  # noqa: E402
import json  # noqa: E402

import openpyxl  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

IMPORT_URL = "/api/transactions/import/"
PREVIEW_URL = "/api/transactions/import/preview/"

SAMPLE_HEADER = [
    "Date", "Narration", "Chq./Ref.No.", "Value Dt",
    "Withdrawal Amt.", "Deposit Amt.", "Closing Balance",
]
SAMPLE_ROWS = [
    ["Example Bank", None, None, None, None, None, None],  # junk above the header
    [],
    SAMPLE_HEADER,
    ["01/04/2026", "UPI/DR/412345678901/TASTYBITES/TSTB/x@tstb", "412345678901", "01/04/2026", "250.00", None, "9,750.00"],
    ["02/04/2026", "BY TRANSFER-NEFT*TSTC0001234*N1234*ACME LTD", "N1234", "02/04/2026", None, "5,000.00", "14,750.00"],
    ["03/04/2026", "ATM WDL", "", "03/04/2026", "1,000.00", 0, "13,750.00"],
    ["not a date", "Total", None, None, None, None, None],  # footer: skipped
]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()  # the "import" throttle is 10/hour; don't let tests eat each other's quota


def make_xlsx(rows, name="statement.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def post_import(user, rows=SAMPLE_ROWS, url=IMPORT_URL, **extra):
    data = {"file": make_xlsx(rows), **extra}
    return client_for(user).post(url, data, format="multipart")


def test_import_requires_auth():
    assert APIClient().post(IMPORT_URL).status_code == 401
    assert APIClient().post(PREVIEW_URL).status_code == 401


def test_preview_detects_sample_columns_and_writes_nothing(alice):
    response = post_import(alice, url=PREVIEW_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["detected_mapping"] == {
        "date": 0, "description": 1, "debit": 4, "credit": 5, "balance": 6,
    }
    assert body["headers"][4] == "Withdrawal Amt."
    assert body["row_count"] == 3
    assert body["sample"][0]["amount"] == "250.00"
    assert body["sample"][0]["name"] == "TASTYBITES"
    assert Transaction.objects.count() == 0


def test_import_saves_encrypted_rows_as_others(alice):
    response = post_import(alice)

    assert response.status_code == 200
    assert response.json()["imported"] == 3
    assert response.json()["duplicates"] == 0
    txns = Transaction.objects.filter(user=alice).order_by("date")
    assert [t.txn_type for t in txns] == ["debit", "credit", "debit"]
    assert all(t.category == get_default_category(alice) for t in txns)
    assert UserCipher(alice).decrypt(bytes(txns[0].amount_enc), "txn.amount").decode() == "250.00"


def test_importing_the_same_file_twice_gives_all_duplicates(alice):
    post_import(alice)
    second = post_import(alice).json()

    assert (second["imported"], second["duplicates"]) == (0, 3)
    assert Transaction.objects.filter(user=alice).count() == 3


def test_imported_rows_belong_only_to_the_uploader(alice, bob):
    post_import(alice)
    assert Transaction.objects.filter(user=bob).count() == 0
    assert post_import(bob).json()["imported"] == 3  # same file, other user: no clash


def test_user_mapping_overrides_detection(alice):
    rows = [["Date", "Narration", "Debit", "Credit"], ["01/04/2026", "Coffee", "10", None]]
    # Deliberately wrong: read the description from the date column.
    mapping = json.dumps({"date": 0, "description": 0, "debit": 2, "credit": 3})

    body = post_import(alice, rows, url=PREVIEW_URL, mapping=mapping).json()

    assert body["detected_mapping"]["description"] == 1  # detection is still reported
    assert body["sample"][0]["description"] == "01/04/2026"  # but the user's mapping was applied


def test_unrecognisable_headers_are_400_no_header(alice):
    rows = [["when", "what", "out", "in"], ["01/04/2026", "Coffee", "10", None]]
    assert post_import(alice, rows, url=PREVIEW_URL).json()["code"] == "no_header"


def test_bad_row_is_reported_but_not_fatal(alice):
    rows = [
        ["Date", "Narration", "Debit", "Credit"],
        ["01/04/2026", "Good", "10", None],
        ["31/02/2026", "Impossible date", "10", None],
        ["02/04/2026", "Good too", "20", None],
    ]
    body = post_import(alice, rows).json()

    assert body["imported"] == 2
    assert [e["row"] for e in body["errors"]] == [3]


def test_unsupported_extension_is_400(alice):
    file = SimpleUploadedFile("statement.docx", b"a,b,c")
    response = client_for(alice).post(IMPORT_URL, {"file": file}, format="multipart")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_file"


def test_pdf_is_refused_by_the_server(alice):
    # The import page turns a PDF into a CSV table in the browser; the server never parses one.
    file = SimpleUploadedFile("statement.pdf", b"%PDF-1.7\n...")
    response = client_for(alice).post(PREVIEW_URL, {"file": file}, format="multipart")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_file"


def test_renamed_non_xlsx_content_is_400(alice):
    file = SimpleUploadedFile("statement.xlsx", b"definitely not a zip")
    response = client_for(alice).post(IMPORT_URL, {"file": file}, format="multipart")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_file"


def test_oversized_file_is_400(alice):
    file = SimpleUploadedFile("statement.xlsx", b"x" * (4 * 1024 * 1024 + 1))
    response = client_for(alice).post(IMPORT_URL, {"file": file}, format="multipart")
    assert response.status_code == 400
    assert response.json()["code"] == "file_too_large"


def test_a_file_of_exactly_the_limit_gets_past_the_size_check(alice):
    file = SimpleUploadedFile("statement.xlsx", b"x" * (4 * 1024 * 1024))
    response = client_for(alice).post(IMPORT_URL, {"file": file}, format="multipart")
    assert response.json()["code"] != "file_too_large"


def test_missing_file_is_400(alice):
    response = client_for(alice).post(IMPORT_URL, {}, format="multipart")
    assert response.json()["code"] == "missing_file"


def test_bad_mapping_is_400(alice):
    assert post_import(alice, mapping="{not json").json()["code"] == "invalid_mapping"
    assert post_import(alice, mapping=json.dumps({"date": 0})).json()["code"] == "invalid_mapping"
    assert post_import(alice, mapping=json.dumps({"bogus": 1})).json()["code"] == "invalid_mapping"


def test_import_does_not_get_swallowed_by_the_transaction_router(alice):
    # "import" must not be read as a transaction id.
    assert client_for(alice).get(IMPORT_URL).status_code == 405


# --- name cleaning ------------------------------------------------------------

from transactions.importer import clean_name  # noqa: E402


@pytest.mark.parametrize(
    "description, expected",
    [
        ("WDL TFR UPI/DR/408808671136/Quickmart/TSTB/paywave-blin/ Blink 009", "Quickmart"),
        ("UPI/DR/412345678901/TASTYBITES/TSTB/tastybites@tstb", "TASTYBITES"),
        ("BY TRANSFER-NEFT*TSTC0001234*N123456789012*ACME LTD", "ACME LTD"),
        ("", "Transaction"),
    ],
)
def test_clean_name(description, expected):
    assert clean_name(description) == expected


# --- password-protected files -------------------------------------------------

import msoffcrypto  # noqa: E402

FILE_PASSWORD = "Secret#123"


def make_encrypted_xlsx(rows, password=FILE_PASSWORD):
    plain = io.BytesIO(make_xlsx(rows).read())
    encrypted = io.BytesIO()
    msoffcrypto.OfficeFile(plain).encrypt(password, encrypted)
    return SimpleUploadedFile("statement.xlsx", encrypted.getvalue())


def post_encrypted(user, url=PREVIEW_URL, **extra):
    data = {"file": make_encrypted_xlsx(SAMPLE_ROWS), **extra}
    return client_for(user).post(url, data, format="multipart")


def test_encrypted_file_without_password_asks_for_one(alice):
    assert post_encrypted(alice).json()["code"] == "password_required"


def test_encrypted_file_with_wrong_password(alice):
    assert post_encrypted(alice, password="nope").json()["code"] == "wrong_password"


def test_encrypted_file_with_right_password_previews(alice):
    response = post_encrypted(alice, password=FILE_PASSWORD)
    assert response.status_code == 200, response.content
    assert response.json()["row_count"] == 3


def test_encrypted_file_with_right_password_imports(alice):
    response = post_encrypted(alice, url=IMPORT_URL, password=FILE_PASSWORD)
    assert response.status_code == 200, response.content
    assert response.json()["imported"] == 3


# --- CSV and old .xls files ---------------------------------------------------

import csv  # noqa: E402

from rest_framework.throttling import ScopedRateThrottle  # noqa: E402

from transactions.testing import make_xls  # noqa: E402


def make_csv(rows, name="statement.csv", delimiter=","):
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter).writerows(rows)
    return SimpleUploadedFile(name, buffer.getvalue().encode())


def post_file(user, file, url=IMPORT_URL, **extra):
    return client_for(user).post(url, {"file": file, **extra}, format="multipart")


def test_csv_preview_detects_the_same_columns_as_xlsx(alice):
    body = post_file(alice, make_csv(SAMPLE_ROWS), url=PREVIEW_URL).json()

    assert body["detected_mapping"] == {
        "date": 0, "description": 1, "debit": 4, "credit": 5, "balance": 6,
    }
    assert body["row_count"] == 3
    assert body["sample"][1]["amount"] == "5000.00"
    assert body["sample"][1]["description"] == "BY TRANSFER-NEFT*TSTC0001234*N1234*ACME LTD"


def test_semicolon_csv_imports(alice):
    response = post_file(alice, make_csv(SAMPLE_ROWS, delimiter=";"))
    assert response.status_code == 200, response.content
    assert response.json()["imported"] == 3


def test_same_statement_as_xlsx_then_csv_gives_all_duplicates(alice):
    # Same cells, same fingerprints: the format a statement came in doesn't matter.
    post_import(alice)
    second = post_file(alice, make_csv(SAMPLE_ROWS)).json()

    assert (second["imported"], second["duplicates"]) == (0, 3)


def test_xls_imports(alice):
    rows = [
        ["Date", "Narration", "Debit", "Credit", "Balance"],
        [date(2026, 4, 1), "UPI/DR/412345678901/TASTYBITES/TSTB/x@tstb", 250, None, 9750],
        ["02/04/2026", "BY TRANSFER-NEFT*TSTC0001234*N1234*ACME LTD", None, 5000, 14750],
    ]
    file = SimpleUploadedFile("statement.xls", make_xls(rows))

    response = post_file(alice, file)

    assert response.status_code == 200, response.content
    assert response.json()["imported"] == 2
    txns = Transaction.objects.filter(user=alice).order_by("date")
    assert [t.date for t in txns] == [date(2026, 4, 1), date(2026, 4, 2)]


def test_csv_bad_row_reports_its_file_row_number(alice):
    rows = [["Date", "Narration", "Debit", "Credit"], ["31/02/2026", "Impossible", "10", None]]
    assert post_file(alice, make_csv(rows)).json()["errors"] == [
        {"row": 2, "reason": "Unrecognised date: '31/02/2026'."}
    ]


def test_preview_has_its_own_rate_limit(alice, monkeypatch):
    # Every mapping change sends another preview, so preview is limited separately from import.
    monkeypatch.setattr(
        ScopedRateThrottle, "THROTTLE_RATES", {"import": "1/hour", "import_preview": "100/hour"}
    )
    for _ in range(3):
        assert post_file(alice, make_csv(SAMPLE_ROWS), url=PREVIEW_URL).status_code == 200
    assert post_file(alice, make_csv(SAMPLE_ROWS)).status_code == 200
    assert post_file(alice, make_csv(SAMPLE_ROWS)).status_code == 429


# --- deleting, then importing again -------------------------------------------

def test_a_deleted_transaction_comes_back_fresh_on_reimport(alice):
    post_import(alice)
    coffee = Transaction.objects.get(user=alice, date=date(2026, 4, 1))
    food = Category.objects.get(user=alice, name="Food")
    coffee.category = food
    coffee.save()

    assert client_for(alice).delete(f"{URL}{coffee.id}/").status_code == 204
    again = post_import(alice).json()

    assert (again["imported"], again["duplicates"]) == (1, 2)
    back = Transaction.objects.get(user=alice, date=date(2026, 4, 1))
    assert back.id != coffee.id
    assert back.category == get_default_category(alice)  # fresh, in "Others"


def test_another_users_transaction_cannot_be_deleted(alice, bob):
    txn = make_txn(alice)
    assert client_for(bob).delete(f"{URL}{txn.id}/").status_code == 404
    assert Transaction.objects.filter(pk=txn.pk).exists()
