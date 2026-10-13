import pytest
from cryptography.exceptions import InvalidTag
from django.db import IntegrityError, connection, transaction

from insights import services
from insights.models import Dashboard, Panel
from insights.spec import SpecError
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

CONFIG = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
NAME = "Monthly review"
TITLE = "Spend by merchant"
SEARCH_TEXT = "tastybites"


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def make_dashboard(user, name=NAME, **extra):
    blob = services.encrypt_text(UserCipher(user), name, services.DASHBOARD_NAME)
    return Dashboard.objects.create(user=user, name_enc=blob, **extra)


def make_panel(dashboard, config=CONFIG, title=TITLE, **grid):
    cipher = UserCipher(dashboard.user)
    values = {"x": 0, "y": 0, "w": 6, "h": 4, **grid}
    return Panel.objects.create(
        dashboard=dashboard,
        title_enc=services.encrypt_text(cipher, title, services.PANEL_TITLE),
        config_enc=services.encrypt_config(cipher, config),
        **values,
    )


# --- encryption helpers -------------------------------------------------------


def test_text_round_trips_through_the_database(alice):
    dashboard = Dashboard.objects.get(pk=make_dashboard(alice).pk)  # fresh read: a memoryview
    text = services.decrypt_text(UserCipher(alice), dashboard.name_enc, services.DASHBOARD_NAME)
    assert text == NAME


def test_config_round_trips_with_defaults_filled_in(alice):
    panel = Panel.objects.get(pk=make_panel(make_dashboard(alice)).pk)
    config = services.decrypt_config(UserCipher(alice), panel.config_enc)
    assert config["chart"] == "bar"
    assert config["y"] == {"measure": "spend", "agg": "sum"}
    assert config["v"] == 1
    assert config["filters"]["date"] == {"preset": "inherit"}


def test_encrypt_config_rejects_an_invalid_spec(alice):
    with pytest.raises(SpecError):
        services.encrypt_config(UserCipher(alice), {"chart": "nope"})


def test_decrypt_config_validates_again(alice):
    cipher = UserCipher(alice)
    # A config an older version might have saved: valid JSON, but no longer a valid spec.
    blob = cipher.encrypt(b'{"chart": "nope"}', services.PANEL_CONFIG)
    with pytest.raises(SpecError):
        services.decrypt_config(cipher, blob)


def test_a_blob_only_decrypts_under_its_own_context(alice):
    blob = services.encrypt_text(UserCipher(alice), NAME, services.DASHBOARD_NAME)
    with pytest.raises(InvalidTag):
        services.decrypt_text(UserCipher(alice), blob, services.PANEL_TITLE)


def test_another_users_cipher_cannot_decrypt(alice, bob):
    blob = services.encrypt_text(UserCipher(alice), NAME, services.DASHBOARD_NAME)
    with pytest.raises(InvalidTag):
        services.decrypt_text(UserCipher(bob), blob, services.DASHBOARD_NAME)


# --- encryption proof ---------------------------------------------------------


def contains(value, text):
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        return text.encode() in value
    return text in str(value)


def test_plaintext_never_appears_in_the_raw_rows(alice):
    dashboard = make_dashboard(alice)
    config = {**CONFIG, "filters": {"merchant_contains": SEARCH_TEXT}}
    panel = make_panel(dashboard, config=config)

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM insights_dashboard WHERE id = %s", [dashboard.id])
        dashboard_row = cursor.fetchone()
        cursor.execute("SELECT * FROM insights_panel WHERE id = %s", [panel.id])
        panel_row = cursor.fetchone()

    for value in dashboard_row:
        assert not contains(value, NAME)
    for value in panel_row:
        assert not contains(value, TITLE)
        assert not contains(value, SEARCH_TEXT)
        assert not contains(value, "category")  # nothing of the config JSON is readable


# --- grid constraints ---------------------------------------------------------


@pytest.mark.parametrize(
    "grid",
    [
        {"w": 0},  # too narrow
        {"w": 13},  # wider than the grid
        {"h": 1},  # too short
        {"h": 31},  # too tall
        {"x": 7, "w": 6},  # hangs off the right edge: 7 + 6 > 12
    ],
)
def test_the_database_rejects_a_bad_grid_position(alice, grid):
    dashboard = make_dashboard(alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_panel(dashboard, **grid)


@pytest.mark.parametrize(
    "grid",
    [
        {"x": 0, "w": 12, "h": 2},  # full width, shortest
        {"x": 6, "w": 6, "h": 30},  # flush to the right edge, tallest
        {"x": 11, "w": 1, "h": 4},  # narrowest panel in the last column
    ],
)
def test_the_database_accepts_the_edges_of_the_grid(alice, grid):
    make_panel(make_dashboard(alice), **grid)


# --- ordering and deletes -----------------------------------------------------


def test_panels_come_back_top_to_bottom_then_left_to_right(alice):
    dashboard = make_dashboard(alice)
    make_panel(dashboard, y=4, x=0)
    make_panel(dashboard, y=0, x=6)
    make_panel(dashboard, y=0, x=0)
    assert [(panel.y, panel.x) for panel in dashboard.panels.all()] == [(0, 0), (0, 6), (4, 0)]


def test_dashboards_come_back_in_tab_order(alice):
    make_dashboard(alice, position=2)
    first = make_dashboard(alice, position=0)
    make_dashboard(alice, position=1)
    assert Dashboard.objects.filter(user=alice).first() == first


def test_deleting_a_dashboard_deletes_its_panels(alice):
    dashboard = make_dashboard(alice)
    make_panel(dashboard)
    dashboard.delete()
    assert Panel.objects.count() == 0


def test_deleting_a_user_deletes_their_dashboards_and_panels(alice):
    make_panel(make_dashboard(alice))
    alice.delete()
    assert Dashboard.objects.count() == 0
    assert Panel.objects.count() == 0
