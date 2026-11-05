"""Uploaded statements stay in memory: no part of one is ever written to a temporary file."""

from unittest import mock

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from rest_framework.test import APIClient

from .tests import make_user

pytestmark = pytest.mark.django_db

PREVIEW_URL = "/api/transactions/import/preview/"
MB = 1024 * 1024


@pytest.fixture
def api():
    client = APIClient()
    client.force_authenticate(make_user("alice@example.com"))
    return client


@pytest.fixture
def no_temporary_files():
    """Fail the test if Django tries to spool an upload to disk."""
    with mock.patch(
        "django.core.files.uploadedfile.TemporaryUploadedFile.__init__",
        side_effect=AssertionError("an upload was written to a temporary file"),
    ):
        yield


def upload(api, size: int):
    statement = SimpleUploadedFile("statement.csv", b"a" * size, content_type="text/csv")
    return api.post(PREVIEW_URL, {"file": statement}, format="multipart")


def test_a_3_mb_statement_is_read_from_memory(api, no_temporary_files):
    """3 MB is over Django's default 2.5 MB, where it would have gone to disk."""
    seen = []

    def spy(file, name, password=None):
        seen.append((type(file), file.size))
        return []  # no header row: the view answers 400, which is fine here

    with mock.patch("transactions.views.read_statement", side_effect=spy):
        response = upload(api, 3 * MB)

    assert response.status_code == 400
    assert seen == [(InMemoryUploadedFile, 3 * MB)]


def test_the_4_mb_limit_still_answers_from_memory(api, no_temporary_files):
    response = upload(api, 4 * MB + 1)
    assert response.status_code == 400
    assert response.data["code"] == "file_too_large"


def test_a_body_over_the_memory_limit_is_dropped_not_spooled(api, no_temporary_files):
    response = upload(api, 6 * MB)
    assert response.status_code == 400
    assert response.data["code"] == "missing_file"
