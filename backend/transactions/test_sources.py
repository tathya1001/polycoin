"""Data sources in the transactions API: importing into one, moving rows, and transfer links."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from datasources.models import DataSource
from datasources.services import SourceError, create_source, first_source
from transactions.links import MAX_CANDIDATES, link_transactions, suggest_transfers
from transactions.models import Transaction, TransferLink
from transactions.services import remove_source
from vault.services import UserCipher

from .tests import make_txn, make_user

pytestmark = pytest.mark.django_db

D = Decimal
PREVIEW, IMPORT = "/api/transactions/import/preview/", "/api/transactions/import/"
LIST, LINKS = "/api/transactions/", "/api/transactions/links/"
STATEMENT = (
    "Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
    "05/01/2026,UPI/TASTYBITES/1,100.00,,900.00\n"
    "06/01/2026,UPI/QUICKMART/2,50.00,,850.00\n"
)


@pytest.fixture
def alice():
    user = make_user("alice@example.com")
    user.oak = first_source(user)
    user.river = create_source(user, UserCipher(user), "River Bank")
    return user


@pytest.fixture
def api(alice):
    client = APIClient()
    client.force_authenticate(alice)
    return client


def upload(api, url, source=None, **fields):
    data = {"file": SimpleUploadedFile("statement.csv", STATEMENT.encode()), **fields}
    if source is not None:
        data["data_source"] = str(source.pk)
    return api.post(url, data, format="multipart")


def add(user, source, amount="10.00", kind="debit", day=date(2026, 3, 5), name="x"):
    return make_txn(
        user,
        data_source=source,
        amount=D(amount),
        txn_type=kind,
        date=day,
        balance=None,
        name=name,
        description=f"{name}/{amount}/{kind}/{day}/{source.pk}",
    )


# --- importing into a source ---------------------------------------------------------------------


def test_a_statement_goes_into_the_chosen_source(alice, api):
    assert upload(api, IMPORT, alice.river).data["imported"] == 2
    assert Transaction.objects.filter(data_source=alice.river).count() == 2


def test_with_no_source_named_it_goes_to_the_first_one(alice, api):
    upload(api, IMPORT)
    assert Transaction.objects.filter(data_source=alice.oak).count() == 2


def test_another_users_source_is_refused(alice, api):
    bob = make_user("bob@example.com")
    response = upload(api, IMPORT, first_source(bob))
    assert response.status_code == 400
    assert response.data["code"] == "invalid_source"


def test_a_bad_source_id_is_refused(api):
    response = api.post(
        PREVIEW,
        {"file": SimpleUploadedFile("s.csv", STATEMENT.encode()), "data_source": "nope"},
        format="multipart",
    )
    assert response.data["code"] == "invalid_source"


def test_importing_twice_into_one_source_gives_duplicates(alice, api):
    upload(api, IMPORT, alice.oak)
    body = upload(api, IMPORT, alice.oak).data
    assert (body["imported"], body["duplicates"]) == (0, 2)


def test_preview_says_what_this_source_already_holds(alice, api):
    upload(api, IMPORT, alice.oak)
    body = upload(api, PREVIEW, alice.oak).data
    assert body["duplicates"] == 2
    assert body["elsewhere"] == []


def test_preview_says_which_other_source_holds_the_rows(alice, api):
    upload(api, IMPORT, alice.oak)
    body = upload(api, PREVIEW, alice.river).data
    assert body["duplicates"] == 0
    assert body["elsewhere"] == [{"data_source": str(alice.oak.pk), "name": "Main", "count": 2}]


def test_rows_held_elsewhere_are_skipped_by_default(alice, api):
    upload(api, IMPORT, alice.oak)
    body = upload(api, IMPORT, alice.river).data
    assert (body["imported"], body["skipped"], body["moved"]) == (0, 2, 0)
    assert not Transaction.objects.filter(data_source=alice.river).exists()


def test_add_keeps_a_second_copy_in_the_new_source(alice, api):
    upload(api, IMPORT, alice.oak)
    assert upload(api, IMPORT, alice.river, elsewhere="add").data["imported"] == 2
    assert Transaction.objects.filter(user=alice).count() == 4


def test_move_carries_category_and_notes_with_the_row(alice, api):
    upload(api, IMPORT, alice.oak)
    row = Transaction.objects.filter(data_source=alice.oak).first()
    row.notes_enc = UserCipher(alice).encrypt(b"lunch", "txn.notes")
    row.category = alice.category_set.get(name="Food")
    row.save()
    stamped = row.updated_at

    body = upload(api, IMPORT, alice.river, elsewhere="move").data

    assert (body["imported"], body["moved"]) == (0, 2)
    moved = Transaction.objects.get(pk=row.pk)
    assert moved.data_source == alice.river and moved.category.name == "Food"
    assert bytes(moved.notes_enc) == bytes(row.notes_enc)
    assert moved.updated_at == stamped  # the Ask index must not embed it again


def test_an_unknown_choice_is_refused(alice, api):
    assert upload(api, IMPORT, alice.oak, elsewhere="?").data["code"] == "invalid_choice"


# --- the list and bulk moves ---------------------------------------------------------------------


def test_a_row_says_its_source_and_link(alice, api):
    debit = add(alice, alice.oak)
    credit = add(alice, alice.river, kind="credit")
    link = link_transactions(alice, UserCipher(alice), debit.pk, credit.pk)

    rows = {row["id"]: row for row in api.get(LIST).data["results"]}

    assert str(rows[str(debit.pk)]["data_source"]) == str(alice.oak.pk)
    assert rows[str(debit.pk)]["link"] == {
        "id": str(link.pk),
        "partner": str(credit.pk),
        "partner_source": str(alice.river.pk),
    }
    assert rows[str(credit.pk)]["link"]["partner"] == str(debit.pk)


def test_an_unlinked_row_has_no_link(alice, api):
    add(alice, alice.oak)
    assert api.get(LIST).data["results"][0]["link"] is None


def test_the_list_filters_by_one_or_more_sources(alice, api):
    add(alice, alice.oak)
    add(alice, alice.river)
    one = api.get(LIST, {"data_source": str(alice.river.pk)}).data
    both = api.get(LIST, {"data_source": f"{alice.oak.pk},{alice.river.pk}"}).data
    assert (one["count"], both["count"]) == (1, 2)


def test_a_bad_source_filter_is_400(api):
    assert api.get(LIST, {"data_source": "nope"}).status_code == 400


def test_a_row_cant_change_source_by_patch(alice, api):
    row = add(alice, alice.oak)
    api.patch(f"{LIST}{row.pk}/", {"data_source": str(alice.river.pk)}, format="json")
    row.refresh_from_db()
    assert row.data_source == alice.oak


def test_bulk_move_moves_mine_and_reports_the_rest(alice, api):
    mine = add(alice, alice.oak)
    bob = make_user("bob@example.com")
    theirs = add(bob, first_source(bob))

    body = api.post(
        f"{LIST}bulk-source/",
        {"transactions": [str(mine.pk), str(theirs.pk)], "data_source": str(alice.river.pk)},
        format="json",
    ).data

    assert (body["moved"], body["skipped"], body["missing"]) == (1, 0, [str(theirs.pk)])
    mine.refresh_from_db()
    assert mine.data_source == alice.river


def test_a_row_the_target_already_holds_stays_where_it_is(alice, api):
    upload(api, IMPORT, alice.oak)
    upload(api, IMPORT, alice.river, elsewhere="add")
    ids = list(Transaction.objects.filter(data_source=alice.oak).values_list("pk", flat=True))

    body = api.post(
        f"{LIST}bulk-source/",
        {"transactions": [str(pk) for pk in ids], "data_source": str(alice.river.pk)},
        format="json",
    ).data

    assert (body["moved"], body["skipped"]) == (0, 2)


def test_you_cant_move_rows_to_another_users_source(alice, api):
    row = add(alice, alice.oak)
    bob = make_user("bob@example.com")
    response = api.post(
        f"{LIST}bulk-source/",
        {"transactions": [str(row.pk)], "data_source": str(first_source(bob).pk)},
        format="json",
    )
    assert response.status_code == 400


def test_moving_both_sides_into_one_source_removes_the_link(alice, api):
    debit = add(alice, alice.oak)
    credit = add(alice, alice.river, kind="credit")
    link_transactions(alice, UserCipher(alice), debit.pk, credit.pk)

    api.post(
        f"{LIST}bulk-source/",
        {"transactions": [str(credit.pk)], "data_source": str(alice.oak.pk)},
        format="json",
    )

    assert not TransferLink.objects.exists()


# --- removing a source ---------------------------------------------------------------------------


def test_removing_a_source_can_take_its_rows_with_it(alice):
    add(alice, alice.river)
    result = remove_source(alice, alice.river)
    assert result == {"moved": 0, "deleted": 1}
    assert not DataSource.objects.filter(pk=alice.river.pk).exists()


def test_removing_a_source_can_keep_its_rows(alice):
    row = add(alice, alice.river)
    assert remove_source(alice, alice.river, alice.oak) == {"moved": 1, "deleted": 0}
    row.refresh_from_db()
    assert row.data_source == alice.oak


def test_the_last_source_cant_go(alice):
    remove_source(alice, alice.river)
    with pytest.raises(SourceError, match="at least one"):
        remove_source(alice, alice.oak)


# --- links ---------------------------------------------------------------------------------------


def post_link(api, first, second):
    return api.post(LINKS, {"first": str(first.pk), "second": str(second.pk)}, format="json")


def test_two_rows_become_one_transfer_in_either_order(alice, api):
    credit = add(alice, alice.river, kind="credit")
    debit = add(alice, alice.oak)
    response = post_link(api, credit, debit)
    assert response.status_code == 201
    link = TransferLink.objects.get()
    assert (link.debit, link.credit, link.user) == (debit, credit, alice)


@pytest.mark.parametrize(
    "second, code",
    [
        (dict(kind="debit"), "same_direction"),
        (dict(kind="credit", amount="11.00"), "different_amount"),
    ],
)
def test_a_pair_that_isnt_a_transfer_is_refused(alice, api, second, code):
    first = add(alice, alice.oak)
    other = add(alice, alice.river, **second)
    assert post_link(api, first, other).data["code"] == code


def test_a_transfer_joins_two_sources(alice, api):
    first, second = add(alice, alice.oak), add(alice, alice.oak, kind="credit")
    assert post_link(api, first, second).data["code"] == "same_source"


def test_a_row_has_one_partner(alice, api):
    debit = add(alice, alice.oak)
    post_link(api, debit, add(alice, alice.river, kind="credit"))
    third = add(alice, alice.river, kind="credit", name="y")
    assert post_link(api, debit, third).data["code"] == "already_linked"


def test_a_row_of_another_user_is_as_good_as_missing(alice, api):
    bob = make_user("bob@example.com")
    theirs = add(bob, first_source(bob), kind="credit")
    assert post_link(api, add(alice, alice.oak), theirs).data["code"] == "not_found"


def test_a_link_can_be_undone(alice, api):
    post_link(api, add(alice, alice.oak), add(alice, alice.river, kind="credit"))
    link = TransferLink.objects.get()
    assert api.delete(f"{LINKS}{link.pk}/").status_code == 204
    assert not TransferLink.objects.exists()


def test_another_users_link_cant_be_undone(alice, api):
    bob = make_user("bob@example.com")
    other = create_source(bob, UserCipher(bob), "Elm")
    debit, credit = add(bob, first_source(bob)), add(bob, other, kind="credit")
    link = link_transactions(bob, UserCipher(bob), debit.pk, credit.pk)
    assert api.delete(f"{LINKS}{link.pk}/").status_code == 404


def test_a_linked_rows_amount_cant_change(alice, api):
    debit = add(alice, alice.oak)
    post_link(api, debit, add(alice, alice.river, kind="credit"))
    url = f"{LIST}{debit.pk}/"
    assert api.patch(url, {"amount": "99.00"}, format="json").status_code == 400
    assert api.patch(url, {"txn_type": "credit"}, format="json").status_code == 400
    assert api.patch(url, {"name": "Rent"}, format="json").status_code == 200


def test_candidates_are_same_amount_opposite_way_other_source_closest_first(alice, api):
    row = add(alice, alice.oak, "500.00", day=date(2026, 3, 10), name="out")
    far = add(alice, alice.river, "500.00", "credit", date(2026, 3, 15), "far")
    near = add(alice, alice.river, "500.00", "credit", date(2026, 3, 11), "near")
    add(alice, alice.river, "499.00", "credit", date(2026, 3, 11), "other amount")
    add(alice, alice.river, "500.00", "debit", date(2026, 3, 11), "same way")
    add(alice, alice.oak, "500.00", "credit", date(2026, 3, 11), "same source")
    add(alice, alice.river, "500.00", "credit", date(2026, 4, 11), "too late")

    found = api.get(f"{LIST}{row.pk}/link-candidates/").data

    assert [item["id"] for item in found] == [str(near.pk), str(far.pk)]
    assert found[0]["name"] == "near"
    assert found[0]["data_source_name"] == "River Bank"
    assert found[0]["days_apart"] == 1


def test_a_row_already_linked_is_not_a_candidate(alice, api):
    row = add(alice, alice.oak, "500.00")
    taken = add(alice, alice.river, "500.00", "credit", name="taken")
    other = add(alice, alice.oak, "500.00", name="other")
    post_link(api, other, taken)
    assert api.get(f"{LIST}{row.pk}/link-candidates/").data == []


def test_candidates_are_capped(alice, api):
    row = add(alice, alice.oak, "500.00")
    for number in range(MAX_CANDIDATES + 2):
        add(alice, alice.river, "500.00", "credit", name=f"n{number}")
    assert len(api.get(f"{LIST}{row.pk}/link-candidates/").data) == MAX_CANDIDATES


def test_a_bad_window_is_400(alice, api):
    row = add(alice, alice.oak)
    assert api.get(f"{LIST}{row.pk}/link-candidates/", {"days": "99"}).status_code == 400


def suggestions(user):
    return suggest_transfers(user, UserCipher(user), date(2026, 1, 1), date(2026, 12, 31))


def test_a_likely_transfer_is_suggested_and_nothing_is_linked(alice):
    add(alice, alice.oak, "500.00", day=date(2026, 3, 10), name="out")
    add(alice, alice.river, "500.00", "credit", date(2026, 3, 12), "in")

    body = suggestions(alice)

    assert body["total"] == 1
    [pair] = body["pairs"]
    assert (pair["amount"], pair["days_apart"]) == ("500.00", 2)
    assert (pair["debit"]["name"], pair["credit"]["name"]) == ("out", "in")
    assert not TransferLink.objects.exists()


def test_each_row_gets_one_partner_and_the_closest_pair_wins(alice):
    add(alice, alice.oak, "500.00", day=date(2026, 3, 10), name="out")
    add(alice, alice.river, "500.00", "credit", date(2026, 3, 12), "later")
    add(alice, alice.river, "500.00", "credit", date(2026, 3, 10), "same day")
    [pair] = suggestions(alice)["pairs"]
    assert pair["credit"]["name"] == "same day"


def test_a_pair_too_far_apart_or_in_one_source_is_not_suggested(alice):
    add(alice, alice.oak, "500.00", day=date(2026, 3, 10), name="out")
    add(alice, alice.river, "500.00", "credit", date(2026, 3, 20), "late")
    add(alice, alice.oak, "500.00", "credit", date(2026, 3, 10), "same source")
    assert suggestions(alice)["pairs"] == []


def test_a_linked_row_is_not_suggested_again(alice):
    debit = add(alice, alice.oak, "500.00", name="out")
    credit = add(alice, alice.river, "500.00", "credit", name="in")
    link_transactions(alice, UserCipher(alice), debit.pk, credit.pk)
    assert suggestions(alice)["pairs"] == []


def test_suggestions_only_ever_read_the_callers_rows(alice):
    bob = make_user("bob@example.com")
    add(alice, alice.oak, "500.00", name="out")
    add(bob, first_source(bob), "500.00", "credit", name="theirs")
    assert suggestions(alice)["pairs"] == []


def test_the_suggestions_endpoint_checks_its_dates(api):
    url = "/api/transactions/transfer-suggestions/"
    assert api.get(url).status_code == 200
    assert api.get(url, {"from": "nope"}).status_code == 400
    assert api.get(url, {"from": "2020-01-01", "to": "2026-01-01"}).status_code == 400


def test_approving_many_links_the_good_ones_and_reports_the_rest(alice, api):
    debit, credit = add(alice, alice.oak), add(alice, alice.river, kind="credit")
    bad = add(alice, alice.oak, name="same source", kind="credit")
    body = api.post(
        f"{LINKS}bulk/",
        {
            "pairs": [
                {"first": str(debit.pk), "second": str(credit.pk)},
                {"first": str(debit.pk), "second": str(bad.pk)},
            ]
        },
        format="json",
    ).data
    assert body["linked"] == 1
    assert body["failed"][0]["code"] == "same_source"
