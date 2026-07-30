# -*- coding: utf-8 -*-

import pytest

from app.utils.crypto import SecretBox
from app.utils.settings import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("AMADEUS_ENV", "production")
    s = Settings(_env_file=None)
    assert s.db_url == "postgresql://u:p@h/db"
    assert s.amadeus_base_url == "https://api.amadeus.com"


def test_settings_defaults_are_safe():
    s = Settings(_env_file=None, db_url="", amadeus_env="test")
    assert s.amadeus_base_url == "https://test.api.amadeus.com"
    assert s.ollama_model == "llama3"


def test_secretbox_roundtrip():
    box = SecretBox("a-sufficiently-long-secret-key")
    token = box.encrypt("sk-super-secret")
    assert token != "sk-super-secret"
    assert box.decrypt(token) == "sk-super-secret"


def test_secretbox_wrong_key_returns_none_not_garbage():
    token = SecretBox("first-secret-key-abcdef").encrypt("value")
    other = SecretBox("second-secret-key-abcdef")
    assert other.decrypt(token) is None


def test_secretbox_rejects_weak_secret():
    with pytest.raises(ValueError):
        SecretBox("short")
    with pytest.raises(ValueError):
        SecretBox("")
