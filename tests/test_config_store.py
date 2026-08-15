"""Tests for app.config_store -- encrypted at-rest credentials store.

Covers the plaintext fallback (no master key configured), Fernet
encrypt-at-rest round trip, unreadable-without-key / wrong-key behavior,
reading a legacy plaintext store once a key is configured, and raw Fernet
key support.
"""

import json

import pytest

from app import config_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a temp file and clear the master key."""
    monkeypatch.setattr(config_store, "_store_path", lambda: tmp_path / "credentials.json")
    monkeypatch.delenv(config_store._CREDENTIALS_KEY_ENV, raising=False)
    return tmp_path / "credentials.json"


@pytest.mark.unit
def test_plaintext_fallback_without_key(store):
    config_store.save_credentials({"api_keys": {"openai": "sk-123"}})
    raw = store.read_text(encoding="utf-8")
    assert raw.lstrip().startswith("{")  # plaintext JSON (legacy behavior)
    assert "sk-123" in raw
    assert config_store.load_credentials()["api_keys"]["openai"] == "sk-123"


@pytest.mark.unit
def test_encrypts_at_rest_with_key(store, monkeypatch):
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, "correct horse battery staple")
    config_store.save_credentials({"api_keys": {"openai": "sk-secret"}})
    raw = store.read_text(encoding="utf-8")
    assert raw.lstrip().startswith(config_store._FERNET_PREFIX)  # Fernet token
    assert "sk-secret" not in raw  # not stored in plaintext
    assert config_store.load_credentials()["api_keys"]["openai"] == "sk-secret"


@pytest.mark.unit
def test_encrypted_store_unreadable_without_key(store, monkeypatch):
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, "first passphrase")
    config_store.save_credentials({"api_keys": {"openai": "sk-secret"}})
    monkeypatch.delenv(config_store._CREDENTIALS_KEY_ENV)
    assert config_store.load_credentials() == {}


@pytest.mark.unit
def test_encrypted_store_unreadable_with_wrong_key(store, monkeypatch):
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, "first passphrase")
    config_store.save_credentials({"api_keys": {"openai": "sk-secret"}})
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, "wrong passphrase")
    assert config_store.load_credentials() == {}


@pytest.mark.unit
def test_legacy_plaintext_store_reads_with_key_set(store, monkeypatch):
    # A pre-existing plaintext store keeps working once a key is configured.
    store.write_text(json.dumps({"api_keys": {"google": "ai-old"}}), encoding="utf-8")
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, "some key")
    assert config_store.load_credentials()["api_keys"]["google"] == "ai-old"


@pytest.mark.unit
def test_accepts_raw_fernet_key(store, monkeypatch):
    from cryptography.fernet import Fernet

    raw_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(config_store._CREDENTIALS_KEY_ENV, raw_key)
    config_store.save_credentials({"production": {"cf_account_id": "acc123"}})
    assert store.read_text(encoding="utf-8").lstrip().startswith(config_store._FERNET_PREFIX)
    assert config_store.load_credentials()["production"]["cf_account_id"] == "acc123"
