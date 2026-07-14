"""TLS verification default + env gate — finding [2]/[23]."""

from engine.runtime import ssl_verify_enabled


def test_ssl_verify_secure_by_default(monkeypatch):
    monkeypatch.delenv("LITELLM_SSL_VERIFY", raising=False)
    assert ssl_verify_enabled() is True


def test_ssl_verify_can_be_disabled(monkeypatch):
    for value in ("false", "0", "no", "FALSE", " No "):
        monkeypatch.setenv("LITELLM_SSL_VERIFY", value)
        assert ssl_verify_enabled() is False


def test_ssl_verify_enabled_for_truthy(monkeypatch):
    for value in ("true", "1", "yes", "anything-else"):
        monkeypatch.setenv("LITELLM_SSL_VERIFY", value)
        assert ssl_verify_enabled() is True
