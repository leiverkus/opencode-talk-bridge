from __future__ import annotations

import opencode_talk_bridge.__main__ as cli
from opencode_talk_bridge.opencode import OpenCodeClient


def _env(monkeypatch, tmp_path, **extra):
    monkeypatch.setenv("ALLOWED_USERS", "jdoe")
    monkeypatch.setenv("TALK_CONVERSATIONS", "tok")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.sqlite3"))
    monkeypatch.setenv("STATUS_FILE", str(tmp_path / "status.json"))
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_bad_config_returns_2(talk_env, monkeypatch):
    monkeypatch.setenv("TALK_CONVERSATIONS", "tok")
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    assert cli.main([]) == 2


def test_check_healthy_returns_0(talk_env, monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(OpenCodeClient, "health", lambda self: True)
    assert cli.main(["--check"]) == 0


def test_check_unreachable_returns_1(talk_env, monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(OpenCodeClient, "health", lambda self: False)
    assert cli.main(["--check"]) == 1


def test_init_routing(monkeypatch, tmp_path):
    called = {}

    def fake_run_init(env_path):
        called["path"] = env_path
        return 0

    monkeypatch.setattr("opencode_talk_bridge.init.run_init", fake_run_init)
    rc = cli.main(["--init", "--env-file", str(tmp_path / "x.env")])
    assert rc == 0
    assert called["path"].endswith("x.env")


def test_run_wires_up_and_starts(talk_env, monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(OpenCodeClient, "health", lambda self: True)
    started = {"n": 0}
    monkeypatch.setattr("opencode_talk_bridge.bridge.Bridge.run", lambda self: started.__setitem__("n", 1))
    assert cli.main([]) == 0
    assert started["n"] == 1
