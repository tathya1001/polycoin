"""HTTP-level tests for the panel endpoints under /api/dashboards/{id}/."""

import uuid

import pytest
from rest_framework.test import APIClient

from insights import services
from insights.models import MAX_PANELS_PER_DASHBOARD, Panel
from insights.test_models import CONFIG, SEARCH_TEXT, TITLE, make_dashboard, make_panel
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

URL = "/api/dashboards/"
FULL = {"title": TITLE, "config": CONFIG, "x": 0, "y": 0, "w": 6, "h": 4}


def panels_url(dashboard):
    return f"{URL}{dashboard.id}/panels/"


def panel_url(dashboard, panel):
    return f"{URL}{dashboard.id}/panels/{panel.id}/"


def layout_url(dashboard):
    return f"{URL}{dashboard.id}/layout/"


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def new_panel(user, dashboard, **extra):
    body = {"title": TITLE, "config": CONFIG, **extra}
    return as_user(user).post(panels_url(dashboard), body, format="json")


def put_layout(user, dashboard, items):
    return as_user(user).put(layout_url(dashboard), items, format="json")


def item(panel, **grid):
    return {"panel": str(panel.id), "x": 0, "y": 0, "w": 6, "h": 4, **grid}


def grid_of(panel):
    panel.refresh_from_db()
    return (panel.x, panel.y, panel.w, panel.h)


def stored_config(user, panel):
    panel.refresh_from_db()
    return services.decrypt_config(UserCipher(user), panel.config_enc)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


# --- auth ---------------------------------------------------------------------


def test_every_endpoint_requires_login(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    api = APIClient()
    assert api.post(panels_url(dashboard), FULL, format="json").status_code == 401
    assert api.patch(panel_url(dashboard, panel), {"title": "x"}, format="json").status_code == 401
    assert api.delete(panel_url(dashboard, panel)).status_code == 401
    assert api.put(layout_url(dashboard), [item(panel)], format="json").status_code == 401


# --- create -------------------------------------------------------------------


def test_create_with_an_explicit_grid(alice):
    dashboard = make_dashboard(alice)

    response = new_panel(alice, dashboard, x=6, y=2, w=6, h=3)

    assert response.status_code == 201
    body = response.json()
    assert (body["x"], body["y"], body["w"], body["h"]) == (6, 2, 6, 3)
    assert body["title"] == TITLE
    assert body["config"]["y"] == {"measure": "spend", "agg": "sum"}  # defaults filled in
    assert dashboard.panels.count() == 1


def test_create_without_a_grid_goes_to_the_bottom(alice):
    dashboard = make_dashboard(alice)

    first = new_panel(alice, dashboard).json()
    second = new_panel(alice, dashboard).json()

    assert (first["x"], first["y"], first["w"], first["h"]) == (0, 0, 6, 4)
    assert (second["x"], second["y"]) == (0, 4)


def test_the_bottom_is_below_the_lowest_edge_of_any_panel(alice):
    dashboard = make_dashboard(alice)
    make_panel(dashboard, x=0, y=0, w=6, h=10)  # ends at row 10
    make_panel(dashboard, x=6, y=2, w=6, h=3)  # ends at row 5

    assert new_panel(alice, dashboard).json()["y"] == 10


def test_title_and_config_are_stored_encrypted(alice):
    dashboard = make_dashboard(alice)
    filters = {"merchant_contains": SEARCH_TEXT}
    config = {"chart": "kpi", "y": {"measure": "spend"}, "filters": filters}

    new_panel(alice, dashboard, title="Secret title", config=config)

    panel = Panel.objects.get()
    for blob in (panel.title_enc, panel.config_enc):
        assert b"Secret title" not in bytes(blob)
        assert SEARCH_TEXT.encode() not in bytes(blob)


def test_a_blank_title_is_allowed(alice):
    response = new_panel(alice, make_dashboard(alice), title="")
    assert response.status_code == 201
    assert response.json()["title"] == ""


def test_the_title_is_tidied(alice):
    response = new_panel(alice, make_dashboard(alice), title="  Spend   by  merchant ")
    assert response.json()["title"] == "Spend by merchant"


@pytest.mark.parametrize(
    "body",
    [
        {"config": CONFIG},  # no title
        {"title": TITLE},  # no config
        {"title": TITLE, "config": "nope"},
        {"title": TITLE, "config": {"chart": "nope"}},
        {"title": TITLE, "config": {**CONFIG, "surprise": 1}},  # unknown key
        {"title": "x" * 81, "config": CONFIG},
        {**FULL, "x": None, "y": None, "w": None, "h": None},
        {"title": TITLE, "config": CONFIG, "x": 0},  # a grid must be all four or none
        {**FULL, "w": 0},
        {**FULL, "w": 13},
        {**FULL, "h": 1},
        {**FULL, "h": 31},
        {**FULL, "x": -1},
        {**FULL, "y": -1},
        {**FULL, "x": 7, "w": 6},  # hangs off the right edge
    ],
)
def test_create_rejects_bad_input(alice, body):
    dashboard = make_dashboard(alice)
    response = as_user(alice).post(panels_url(dashboard), body, format="json")
    assert response.status_code == 400
    assert Panel.objects.count() == 0


def test_a_bad_config_explains_itself(alice):
    response = new_panel(alice, make_dashboard(alice), config={"chart": "nope"})
    assert response.status_code == 400
    assert response.json()["config"]  # a message under the config key


def test_the_panel_cap_is_per_dashboard(alice):
    full = make_dashboard(alice, name="Full")
    other = make_dashboard(alice, name="Other")
    for index in range(MAX_PANELS_PER_DASHBOARD):
        make_panel(full, y=index * 2)

    assert new_panel(alice, full).status_code == 400
    assert full.panels.count() == MAX_PANELS_PER_DASHBOARD
    assert new_panel(alice, other).status_code == 201


def test_a_created_panel_shows_up_when_the_dashboard_is_fetched(alice):
    dashboard = make_dashboard(alice)
    created = new_panel(alice, dashboard).json()

    body = as_user(alice).get(f"{URL}{dashboard.id}/").json()

    assert [panel["id"] for panel in body["panels"]] == [created["id"]]


# --- patch --------------------------------------------------------------------


def test_patch_the_title_keeps_the_config(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)

    response = as_user(alice).patch(panel_url(dashboard, panel), {"title": "New"}, format="json")

    assert response.status_code == 200
    assert response.json()["title"] == "New"
    assert response.json()["config"]["chart"] == "bar"


def test_patch_the_config_keeps_the_title_and_grid(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard, x=2, y=3, w=4, h=5)
    config = {"chart": "kpi", "y": {"measure": "income"}}

    response = as_user(alice).patch(panel_url(dashboard, panel), {"config": config}, format="json")

    assert response.status_code == 200
    assert response.json()["title"] == TITLE
    assert stored_config(alice, panel)["chart"] == "kpi"
    assert grid_of(panel) == (2, 3, 4, 5)


def test_an_invalid_config_patch_leaves_the_panel_unchanged(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)

    response = as_user(alice).patch(
        panel_url(dashboard, panel), {"config": {"chart": "nope"}}, format="json"
    )

    assert response.status_code == 400
    assert stored_config(alice, panel)["chart"] == "bar"


def test_patch_cannot_move_a_panel(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard, x=0, y=0, w=6, h=4)

    response = as_user(alice).patch(
        panel_url(dashboard, panel), {"x": 5, "w": 2, "title": "Same"}, format="json"
    )

    assert response.status_code == 200
    assert grid_of(panel) == (0, 0, 6, 4)


def test_an_empty_patch_changes_nothing(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    response = as_user(alice).patch(panel_url(dashboard, panel), {}, format="json")
    assert response.status_code == 200
    assert response.json()["title"] == TITLE


# --- delete -------------------------------------------------------------------


def test_delete_removes_only_that_panel(alice):
    dashboard = make_dashboard(alice)
    doomed = make_panel(dashboard, y=0)
    kept = make_panel(dashboard, y=4)

    assert as_user(alice).delete(panel_url(dashboard, doomed)).status_code == 204

    assert list(Panel.objects.values_list("id", flat=True)) == [kept.id]


def test_an_unknown_or_malformed_panel_id_is_a_404(alice):
    dashboard = make_dashboard(alice)
    api = as_user(alice)
    assert api.delete(f"{URL}{dashboard.id}/panels/{uuid.uuid4()}/").status_code == 404
    assert api.delete(f"{URL}{dashboard.id}/panels/not-a-uuid/").status_code == 404
    dashes = f"{URL}{dashboard.id}/panels/{'-' * 36}/"
    assert api.patch(dashes, {}, format="json").status_code == 404


def test_a_panel_cannot_be_reached_through_a_different_dashboard(alice):
    home = make_dashboard(alice, name="Home")
    elsewhere = make_dashboard(alice, name="Elsewhere")
    panel = make_panel(home)
    api = as_user(alice)

    assert api.patch(panel_url(elsewhere, panel), {"title": "x"}, format="json").status_code == 404
    assert api.delete(panel_url(elsewhere, panel)).status_code == 404
    assert Panel.objects.filter(pk=panel.pk).exists()


# --- layout -------------------------------------------------------------------


def test_layout_moves_and_resizes_panels(alice):
    dashboard = make_dashboard(alice)
    first = make_panel(dashboard, x=0, y=0, w=6, h=4)
    second = make_panel(dashboard, x=6, y=0, w=6, h=4)

    response = put_layout(
        alice,
        dashboard,
        [item(first, x=0, y=5, w=12, h=3), item(second, x=3, y=0, w=4, h=6)],
    )

    assert response.status_code == 204
    assert grid_of(first) == (0, 5, 12, 3)
    assert grid_of(second) == (3, 0, 4, 6)


def test_layout_may_name_only_the_panels_that_moved(alice):
    dashboard = make_dashboard(alice)
    moved = make_panel(dashboard, x=0, y=0, w=6, h=4)
    still = make_panel(dashboard, x=6, y=0, w=6, h=4)

    assert put_layout(alice, dashboard, [item(moved, y=8)]).status_code == 204

    assert grid_of(moved)[1] == 8
    assert grid_of(still) == (6, 0, 6, 4)


def test_layout_is_shown_when_the_dashboard_is_fetched(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    put_layout(alice, dashboard, [item(panel, x=2, y=7, w=5, h=6)])

    [shown] = as_user(alice).get(f"{URL}{dashboard.id}/").json()["panels"]

    assert (shown["x"], shown["y"], shown["w"], shown["h"]) == (2, 7, 5, 6)


def test_one_foreign_panel_rejects_the_whole_layout(alice, bob):
    dashboard = make_dashboard(alice)
    mine = make_panel(dashboard, x=0, y=0, w=6, h=4)
    other_dashboard_of_mine = make_dashboard(alice, name="Elsewhere")
    elsewhere = make_panel(other_dashboard_of_mine)
    theirs = make_panel(make_dashboard(bob))

    for stranger in (elsewhere, theirs, None):
        stranger_item = item(stranger) if stranger else {**item(mine), "panel": str(uuid.uuid4())}
        response = put_layout(alice, dashboard, [item(mine, y=9), stranger_item])
        assert response.status_code == 400
        assert grid_of(mine) == (0, 0, 6, 4)  # the valid half was not applied either


def test_layout_rejects_the_same_panel_twice(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    response = put_layout(alice, dashboard, [item(panel, y=1), item(panel, y=2)])
    assert response.status_code == 400
    assert grid_of(panel) == (0, 0, 6, 4)


@pytest.mark.parametrize(
    "grid",
    [
        {"w": 0},
        {"w": 13},
        {"h": 1},
        {"h": 31},
        {"x": -1},
        {"x": 12},
        {"y": -1},
        {"x": 7, "w": 6},  # hangs off the right edge
        {"w": "wide"},
        {"x": None},
    ],
)
def test_layout_rejects_bad_numbers(alice, grid):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    assert put_layout(alice, dashboard, [item(panel, **grid)]).status_code == 400
    assert grid_of(panel) == (0, 0, 6, 4)


def test_layout_rejects_malformed_bodies(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    incomplete = {key: value for key, value in item(panel).items() if key != "h"}
    too_many = [item(panel) for _ in range(MAX_PANELS_PER_DASHBOARD + 1)]

    for body in ([], {"panel": str(panel.id)}, "nope", [incomplete], [{"x": 0}], too_many):
        assert put_layout(alice, dashboard, body).status_code == 400


# --- another user's dashboard -------------------------------------------------


def test_another_users_dashboard_is_a_404_for_every_panel_call(alice, bob):
    theirs = make_dashboard(bob)
    their_panel = make_panel(theirs)
    api = as_user(alice)

    assert api.post(panels_url(theirs), FULL, format="json").status_code == 404
    patched = api.patch(panel_url(theirs, their_panel), {"title": "x"}, format="json")
    assert patched.status_code == 404
    assert api.delete(panel_url(theirs, their_panel)).status_code == 404
    moved = api.put(layout_url(theirs), [item(their_panel, y=9)], format="json")
    assert moved.status_code == 404

    assert theirs.panels.count() == 1
    assert grid_of(their_panel) == (0, 0, 6, 4)


def test_a_panel_with_a_table_calculation_saves_and_reads_back_encrypted():
    alice = make_user("calc@example.com")
    dashboard = make_dashboard(alice)
    config = {
        "chart": "line",
        "x": {"field": "date", "granularity": "month"},
        "y": {"measure": "spend"},
        "calc": {"type": "moving_average", "window": 4},
    }

    created = new_panel(alice, dashboard, config=config)
    assert created.status_code == 201, created.content
    assert created.json()["config"]["calc"] == {"type": "moving_average", "window": 4}

    stored = Panel.objects.get(pk=created.json()["id"])
    assert b"moving_average" not in bytes(stored.config_enc)  # encrypted at rest
    assert services.decrypt_config(UserCipher(alice), stored.config_enc)["calc"]["window"] == 4

    refused = new_panel(
        alice, dashboard, config={**config, "calc": {"type": "running_total", "window": 2}}
    )
    assert refused.status_code == 400


# --- showing the title ----------------------------------------------------------------------


def test_a_new_panel_shows_its_title_unless_told_not_to(alice):
    dashboard = make_dashboard(alice)
    assert new_panel(alice, dashboard).json()["show_title"] is True
    hidden = new_panel(alice, dashboard, show_title=False).json()
    assert hidden["show_title"] is False
    assert Panel.objects.get(pk=hidden["id"]).show_title is False


def test_the_title_can_be_hidden_and_shown_again_without_losing_it(alice):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    url = panel_url(dashboard, panel)

    hidden = as_user(alice).patch(url, {"show_title": False}, format="json").json()
    assert hidden["show_title"] is False and hidden["title"] == TITLE

    shown = as_user(alice).patch(url, {"show_title": True}, format="json").json()
    assert shown["show_title"] is True and shown["title"] == TITLE


def test_hiding_the_title_works_for_a_note_too(alice):
    dashboard = make_dashboard(alice)
    note = {"chart": "text", "text": "Remember the rent"}
    created = new_panel(alice, dashboard, config=note, show_title=False).json()
    assert created["show_title"] is False and created["config"]["chart"] == "text"


def test_show_title_is_part_of_the_dashboard(alice):
    dashboard = make_dashboard(alice)
    new_panel(alice, dashboard, show_title=False)
    body = as_user(alice).get(f"{URL}{dashboard.id}/").json()
    assert body["panels"][0]["show_title"] is False


@pytest.mark.parametrize("value", ["maybe", 5, None, [True]])
def test_show_title_must_be_true_or_false(alice, value):
    dashboard = make_dashboard(alice)
    assert new_panel(alice, dashboard, show_title=value).status_code == 400


def test_another_user_cannot_hide_a_panels_title(alice, bob):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)
    response = as_user(bob).patch(panel_url(dashboard, panel), {"show_title": False}, format="json")
    assert response.status_code == 404
    panel.refresh_from_db()
    assert panel.show_title is True
