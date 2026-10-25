"""HTTP-level tests for /api/backup/."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from accounts.services import delete_user_data
from backups import views
from backups.views import DownloadView, RestoreView
from transactions.models import Transaction
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

DOWNLOAD, RESTORE = "/api/backup/", "/api/backup/restore/"


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def alice():
    user = make_user("alice@example.com")
    make_txn(user, name="Tastybites Cafe", date=date(2026, 1, 5))
    return user


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def upload(api, content: bytes, name="backup.polycoin"):
    return api.post(RESTORE, {"file": SimpleUploadedFile(name, content)}, format="multipart")


def problem(response) -> str:
    assert response.status_code == 400, response.content
    return response.json()["code"]


def test_download_is_a_private_file_attachment(alice):
    response = as_user(alice).get(DOWNLOAD)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    today = timezone.localdate()
    assert response["Content-Disposition"] == (
        f'attachment; filename="backup-{today:%Y-%m-%d}.polycoin"'
    )
    assert "no-store" in response["Cache-Control"]
    assert response.content.startswith(b"polycoin-backup/1\n")
    assert b"Tastybites" not in response.content


def test_download_then_restore_after_deleting_the_data(alice):
    api = as_user(alice)
    content = api.get(DOWNLOAD).content
    delete_user_data(alice)
    response = upload(api, content)
    assert response.status_code == 200
    assert response.json()["transactions"] == {"added": 1, "skipped": 0}
    assert Transaction.objects.filter(user=alice).count() == 1
    assert upload(api, content).json()["transactions"] == {"added": 0, "skipped": 1}


def test_another_users_file_is_refused(alice, bob):
    content = as_user(alice).get(DOWNLOAD).content
    assert problem(upload(as_user(bob), content)) == "not_your_backup"


def test_a_file_that_is_not_a_backup_is_refused(alice):
    assert problem(upload(as_user(alice), b"PK\x03\x04", name="statement.xlsx")) == "not_a_backup"


def test_a_missing_file_is_refused(alice):
    assert problem(as_user(alice).post(RESTORE, {}, format="multipart")) == "missing_file"


def test_an_oversized_upload_is_refused_before_it_is_read(alice, settings):
    settings.BACKUP_MAX_BYTES = 10
    assert problem(upload(as_user(alice), b"x" * 11)) == "too_large"


def test_a_backup_too_big_to_restore_is_not_downloaded(alice, settings):
    settings.BACKUP_MAX_BYTES = 100
    assert problem(as_user(alice).get(DOWNLOAD)) == "too_large"


def test_a_conflicting_change_restores_nothing(alice, monkeypatch):
    def conflict(user, content):
        raise IntegrityError("duplicate key")

    monkeypatch.setattr(views, "restore_backup", conflict)
    response = upload(as_user(alice), b"anything")
    assert response.status_code == 409
    assert "Nothing was restored" in response.json()["detail"]


def test_both_endpoints_need_a_signed_in_user():
    api = APIClient()
    assert api.get(DOWNLOAD).status_code in (401, 403)
    assert upload(api, b"x").status_code in (401, 403)


def test_each_endpoint_has_its_throttle_scope_and_the_scope_has_a_rate(settings):
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    for view in (DownloadView, RestoreView):
        assert view.throttle_scope == "backup" and "backup" in rates
        assert ScopedRateThrottle in [type(t) for t in view().get_throttles()]


def test_restore_only_accepts_a_multipart_upload(alice):
    response = as_user(alice).post(RESTORE, {"file": "text"}, format="json")
    assert response.status_code == 415
