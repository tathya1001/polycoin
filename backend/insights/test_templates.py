"""Starter dashboard templates: the data, the service that builds them, and the API."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from insights import services
from insights.models import (
    GRID_COLUMNS,
    MAX_DASHBOARDS_PER_USER,
    MAX_PANEL_HEIGHT,
    MAX_PANELS_PER_DASHBOARD,
    MIN_PANEL_HEIGHT,
    Dashboard,
    Panel,
)
from insights.spec import SpecError, validate_spec
from insights.templates import TEMPLATES
from insights.test_models import make_dashboard
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

URL = "/api/dashboards/"
OVERVIEW_BODY = {"name": "Overview", "template": "overview"}


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def alice():
    return make_user("alice@example.com")


def overlaps(a, b):
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


# --- the template data --------------------------------------------------------


def test_the_overview_template_exists():
    assert "overview" in TEMPLATES


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_panel_config_is_a_valid_spec(name):
    for panel in TEMPLATES[name]:
        validate_spec(panel["config"])  # raises SpecError if the template has drifted


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_panel_fits_the_grid_and_the_size_limits(name):
    assert len(TEMPLATES[name]) <= MAX_PANELS_PER_DASHBOARD
    for panel in TEMPLATES[name]:
        assert 1 <= panel["w"] <= GRID_COLUMNS
        assert MIN_PANEL_HEIGHT <= panel["h"] <= MAX_PANEL_HEIGHT
        assert panel["x"] >= 0 and panel["x"] + panel["w"] <= GRID_COLUMNS
        assert panel["y"] >= 0


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_two_panels_overlap(name):
    panels = TEMPLATES[name]
    for index, first in enumerate(panels):
        for second in panels[index + 1 :]:
            assert not overlaps(first, second), (first["title"], second["title"])


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_titles_are_unique_within_a_template(name):
    titles = [panel["title"] for panel in TEMPLATES[name]]
    assert len(set(titles)) == len(titles)


def test_every_overview_panel_runs_against_real_transactions(alice):
    today = timezone.localdate()
    make_txn(alice, date=today, txn_type="credit", amount=Decimal("1000.00"), name="Payroll")
    make_txn(alice, date=today, txn_type="debit", amount=Decimal("40.00"), name="Tastybites")
    make_txn(alice, date=today, txn_type="debit", amount=Decimal("15.50"), name="Fuelstop")
    queries = [
        {"key": str(index), "spec": panel["config"]}
        for index, panel in enumerate(TEMPLATES["overview"])
    ]

    results = services.run_queries(alice, {}, queries)

    assert len(results) == len(queries)
    for result in results.values():
        assert "error" not in result
        assert result["rows"]  # every panel has something to draw


# --- the service --------------------------------------------------------------


def test_create_from_template_builds_the_dashboard_and_its_panels(alice):
    cipher = UserCipher(alice)

    dashboard = services.create_from_template(alice, cipher, "My overview", "overview", 3)

    dashboard = Dashboard.objects.get(pk=dashboard.pk)
    name = services.decrypt_text(cipher, dashboard.name_enc, services.DASHBOARD_NAME)
    assert name == "My overview"
    assert dashboard.position == 3
    assert dashboard.user == alice
    panels = list(dashboard.panels.all())  # grid order: top to bottom, then left to right
    assert len(panels) == len(TEMPLATES["overview"])
    first = services.decrypt_text(cipher, panels[0].title_enc, services.PANEL_TITLE)
    assert first == "Spend"
    assert services.decrypt_config(cipher, panels[0].config_enc)["kpi"]["compare"] == "previous"


def test_a_failing_template_leaves_nothing_behind(alice, monkeypatch):
    broken = [{"title": "Bad", "x": 0, "y": 0, "w": 6, "h": 4, "config": {"chart": "nope"}}]
    monkeypatch.setitem(TEMPLATES, "broken", broken)

    with pytest.raises(SpecError):
        services.create_from_template(alice, UserCipher(alice), "Broken", "broken", 0)

    assert Dashboard.objects.count() == 0
    assert Panel.objects.count() == 0


# --- the API ------------------------------------------------------------------


def test_creating_from_a_template_gives_a_full_dashboard(alice):
    response = as_user(alice).post(URL, OVERVIEW_BODY, format="json")

    assert response.status_code == 201
    assert response.json()["name"] == "Overview"
    detail = as_user(alice).get(f"{URL}{response.json()['id']}/").json()
    assert len(detail["panels"]) == len(TEMPLATES["overview"])
    for panel in detail["panels"]:
        assert panel["config"] is not None
        assert "config_error" not in panel
    assert [panel["title"] for panel in detail["panels"]][:3] == ["Spend", "Income", "Net"]


def test_a_template_dashboard_takes_the_next_tab_position(alice):
    make_dashboard(alice, position=0)
    response = as_user(alice).post(URL, OVERVIEW_BODY, format="json")
    assert response.json()["position"] == 1


def test_the_dashboard_cap_also_blocks_templates(alice):
    for index in range(MAX_DASHBOARDS_PER_USER):
        make_dashboard(alice, position=index)

    response = as_user(alice).post(URL, OVERVIEW_BODY, format="json")

    assert response.status_code == 400
    assert Panel.objects.count() == 0


def test_an_unknown_template_is_rejected(alice):
    response = as_user(alice).post(URL, {"name": "X", "template": "nope"}, format="json")
    assert response.status_code == 400
    assert Dashboard.objects.count() == 0


def test_a_template_cannot_be_applied_to_an_existing_dashboard(alice):
    dashboard = make_dashboard(alice)
    response = as_user(alice).patch(
        f"{URL}{dashboard.id}/", {"template": "overview"}, format="json"
    )
    assert response.status_code == 400
    assert dashboard.panels.count() == 0


def test_creating_without_a_template_still_makes_an_empty_dashboard(alice):
    response = as_user(alice).post(URL, {"name": "Blank"}, format="json")
    assert response.status_code == 201
    assert Panel.objects.count() == 0
