from __future__ import annotations

import pytest

from opencode_talk_bridge.config import Config, ConfigError, load_dotenv


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_USERS", "jdoe, asmith")
    monkeypatch.setenv("TALK_CONVERSATIONS", "tok1, tok2")


def test_allowlist_required_to_start(talk_env, monkeypatch):
    monkeypatch.setenv("TALK_CONVERSATIONS", "tok1")
    monkeypatch.setenv("ALLOWED_USERS", "")
    with pytest.raises(ConfigError, match="ALLOWED_USERS"):
        Config.from_env()


def test_conversations_required(talk_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_USERS", "jdoe")
    monkeypatch.setenv("TALK_CONVERSATIONS", "")
    with pytest.raises(ConfigError, match="TALK_CONVERSATIONS"):
        Config.from_env()


def test_defaults_and_parsing(talk_env, monkeypatch):
    _base_env(monkeypatch)
    cfg = Config.from_env()
    assert cfg.allowed_users == {"jdoe", "asmith"}
    assert cfg.conversations == ("tok1", "tok2")
    assert cfg.watch_all is False
    assert cfg.opencode_url == "http://127.0.0.1:4096"
    assert cfg.opencode_username is None
    assert cfg.talk.nc_user == "bot"


def test_watch_all(talk_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_USERS", "jdoe")
    monkeypatch.setenv("TALK_CONVERSATIONS", "all")
    cfg = Config.from_env()
    assert cfg.watch_all is True
    assert cfg.conversations == ()


def test_opencode_url_trailing_slash_stripped(talk_env, monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("OPENCODE_URL", "http://127.0.0.1:4099/")
    assert Config.from_env().opencode_url == "http://127.0.0.1:4099"


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('FOO=from_file\nBAR="quoted"\n# comment\n', encoding="utf-8")
    monkeypatch.setenv("FOO", "from_env")
    load_dotenv(env_file)
    import os

    assert os.environ["FOO"] == "from_env"  # existing env wins
    assert os.environ["BAR"] == "quoted"
