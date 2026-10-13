"""HTTP-level tests for /api/dashboards/."""

import pytest
from rest_framework.test import APIClient

from insights import services
from insights.models import MAX_DASHBOARDS_PER_USER, Dashboard, Panel
from insights.test_models import CONFIG, NAME, TITLE, make_dashboard, make_panel
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

URL = "/api/dashboards/"


def detail_url(dashboard_id):
    return f"{URL}{dashboard_id}/"


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def create(user, **body):
    return as_user(user).post(URL, body, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


# --- auth ---------------------------------------------------------------------


def test_every_endpoint_requires_login(alice):
    dashboard = make_dashboard(alice)
    api = APIClient()
    assert api.get(URL).status_code == 401
    assert api.post(URL, {"name": NAME}, format="json").status_code == 401
    assert api.get(detail_url(dashboard.id)).status_code == 401
    assert api.patch(detail_url(dashboard.id), {"name": "x"}, format="json").status_code == 401
    assert api.delete(detail_url(dashboard.id)).status_code == 401


# --- create and list ----------------------------------------------------------


def test_create_returns_the_decrypted_name_and_the_next_position(alice):
    first = create(alice, name="Monthly review")
    second = create(alice, name="Travel")
    assert first.status_code == 201
    assert first.json()["name"] == "Monthly review"
    assert first.json()["position"] == 0
    assert second.json()["position"] == 1


def test_create_tidies_whitespace(alice):
    assert create(alice, name="  Monthly   review ").json()["name"] == "Monthly review"


def test_create_accepts_an_explicit_position(alice):
    assert create(alice, name=NAME, position=5).json()["position"] == 5


def test_the_name_is_stored_encrypted(alice):
    create(alice, name=NAME)
    stored = bytes(Dashboard.objects.get().name_enc)
    assert NAME.encode() not in stored


def test_list_is_a_plain_array_in_tab_order_without_panels(alice):
    last = make_dashboard(alice, name="Last", position=2)
    make_dashboard(alice, name="First", position=0)
    make_panel(last)

    response = as_user(alice).get(URL)

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body] == ["First", "Last"]
    assert "panels" not in body[0]


@pytest.mark.parametrize(
    "body",
    [
        {},  # no name
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 61},
        {"name": NAME, "position": -1},
        {"name": NAME, "position": MAX_DASHBOARDS_PER_USER},
        {"name": NAME, "position": "first"},
    ],
)
def test_create_rejects_bad_input(alice, body):
    assert create(alice, **body).status_code == 400


def test_the_last_valid_position_and_a_maximum_length_name_are_accepted(alice):
    body = {"name": "x" * 60, "position": MAX_DASHBOARDS_PER_USER - 1}
    assert create(alice, **body).status_code == 201


def test_a_body_cannot_assign_the_dashboard_to_someone_else(alice, bob):
    body = {"name": NAME, "user": str(bob.id)}
    assert as_user(alice).post(URL, body, format="json").status_code == 201
    assert Dashboard.objects.filter(user=alice).count() == 1
    assert Dashboard.objects.filter(user=bob).count() == 0


def test_the_dashboard_cap_is_enforced_per_user(alice, bob):
    for index in range(MAX_DASHBOARDS_PER_USER):
        assert create(alice, name=f"Tab {index}").status_code == 201

    over = create(alice, name="One too many")

    assert over.status_code == 400
    assert Dashboard.objects.filter(user=alice).count() == MAX_DASHBOARDS_PER_USER
    assert create(bob, name=NAME).status_code == 201  # bob's budget is his own


# --- retrieve -----------------------------------------------------------------


def test_retrieve_includes_decrypted_panels_in_grid_order(alice):
    dashboard = make_dashboard(alice)
    make_panel(dashboard, title="Lower", y=4, x=0)
    make_panel(dashboard, title=TITLE, config=CONFIG, y=0, x=6, w=6, h=3)

    body = as_user(alice).get(detail_url(dashboard.id)).json()

    assert body["name"] == NAME
    assert [panel["title"] for panel in body["panels"]] == [TITLE, "Lower"]
    first = body["panels"][0]
    assert (first["x"], first["y"], first["w"], first["h"]) == (6, 0, 6, 3)
    assert first["config"]["chart"] == "bar"
    assert first["config"]["y"] == {"measure": "spend", "agg": "sum"}  # defaults filled in


def test_a_panel_with_a_broken_config_is_flagged_not_a_500(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    bad = UserCipher(alice).encrypt(b'{"chart": "nope"}', services.PANEL_CONFIG)
    Panel.objects.filter(pk=panel.pk).update(config_enc=bad)

    response = as_user(alice).get(detail_url(dashboard.id))

    assert response.status_code == 200
    broken = response.json()["panels"][0]
    assert broken["config"] is None
    assert broken["config_error"] == "invalid_spec"
    assert broken["title"] == TITLE  # the rest of the panel still works


# --- update and delete --------------------------------------------------------


def test_patch_renames_and_keeps_the_position(alice):
    dashboard = make_dashboard(alice, position=3)
    response = as_user(alice).patch(detail_url(dashboard.id), {"name": "Renamed"}, format="json")
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["position"] == 3


def test_patch_moves_and_keeps_the_name(alice):
    dashboard = make_dashboard(alice, position=3)
    response = as_user(alice).patch(detail_url(dashboard.id), {"position": 1}, format="json")
    assert response.json()["name"] == NAME
    assert response.json()["position"] == 1


def test_patch_rejects_a_blank_name(alice):
    dashboard = make_dashboard(alice)
    response = as_user(alice).patch(detail_url(dashboard.id), {"name": "  "}, format="json")
    assert response.status_code == 400


def test_patching_never_trips_the_dashboard_cap(alice):
    for index in range(MAX_DASHBOARDS_PER_USER):
        make_dashboard(alice, position=index)
    dashboard = Dashboard.objects.filter(user=alice).first()
    response = as_user(alice).patch(detail_url(dashboard.id), {"name": "Same"}, format="json")
    assert response.status_code == 200


def test_put_is_not_allowed(alice):
    dashboard = make_dashboard(alice)
    response = as_user(alice).put(detail_url(dashboard.id), {"name": "x"}, format="json")
    assert response.status_code == 405


def test_delete_removes_the_dashboard_and_its_panels(alice):
    dashboard = make_dashboard(alice)
    make_panel(dashboard)

    assert as_user(alice).delete(detail_url(dashboard.id)).status_code == 204

    assert Dashboard.objects.count() == 0
    assert Panel.objects.count() == 0


# --- another user's data ------------------------------------------------------


def test_another_users_dashboard_is_invisible(alice, bob):
    theirs = make_dashboard(bob)
    api = as_user(alice)

    assert api.get(URL).json() == []
    assert api.get(detail_url(theirs.id)).status_code == 404
    patched = api.patch(detail_url(theirs.id), {"name": "mine now"}, format="json")
    assert patched.status_code == 404
    assert api.delete(detail_url(theirs.id)).status_code == 404
    assert Dashboard.objects.filter(pk=theirs.pk).exists()
