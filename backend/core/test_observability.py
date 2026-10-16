"""Sentry must be configured so request data and local variables never leave with an error."""

import sentry_sdk

from core.observability import init_sentry


def test_sentry_is_configured_to_send_no_user_data(monkeypatch):
    captured = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    init_sentry("https://key@sentry.test/1", release="abc123")

    assert captured["dsn"] == "https://key@sentry.test/1"
    assert captured["release"] == "abc123"
    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False  # decrypted values live in frames
    assert captured["max_request_body_size"] == "never"
    assert captured["traces_sample_rate"] == 0


def test_sentry_stays_off_without_a_dsn(settings):
    """settings.py only calls init_sentry when SENTRY_DSN is set; the default is empty."""
    assert settings.SENTRY_DSN == ""
