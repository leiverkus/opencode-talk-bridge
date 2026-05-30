from __future__ import annotations

import os
import stat

from opencode_talk_bridge.config import Config
from opencode_talk_bridge.init import run_init


def _scripted(answers):
    """Return an ask() that pops scripted answers in order."""
    answers = list(answers)

    def ask(_prompt):
        return answers.pop(0)

    return ask


def test_init_writes_valid_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    text_answers = _scripted(
        [
            "https://cloud.example.com",  # NC_URL
            "bot",  # NC_USER
            "tok1, tok2",  # TALK_CONVERSATIONS
            "jdoe",  # ALLOWED_USERS
            "",  # OPENCODE_URL -> default
            "",  # OPENCODE_USERNAME
            "",  # SHARE_WEBDAV_DIR
            "en",  # BOT_LOCALE
        ]
    )
    secret_answers = _scripted(["app-pw-123", ""])  # NC_APP_PASSWORD, OPENCODE_PASSWORD
    out: list[str] = []

    rc = run_init(str(env), ask=text_answers, ask_secret=secret_answers, out=out.append)
    assert rc == 0
    assert env.exists()

    # The generated file must satisfy the real config loader.
    for line in env.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            monkeypatch.setenv(k.strip(), v.strip())
    cfg = Config.from_env()
    assert cfg.talk.nc_url == "https://cloud.example.com"
    assert cfg.allowed_users == {"jdoe"}
    assert cfg.opencode_url == "http://127.0.0.1:4096"  # default applied
    assert cfg.bot_locale == "en"


def test_init_file_is_chmod_600(tmp_path):
    env = tmp_path / ".env"
    run_init(
        str(env),
        ask=_scripted(["https://c.example.com", "bot", "tok", "jdoe", "", "", "", "de"]),
        ask_secret=_scripted(["pw", ""]),
        out=lambda _m: None,
    )
    mode = stat.S_IMODE(os.stat(env).st_mode)
    assert mode == 0o600


def test_init_required_field_reprompts(tmp_path):
    env = tmp_path / ".env"
    # First NC_URL empty -> reprompt; then a valid one (so one extra text read).
    ask = _scripted(["", "https://c.example.com", "bot", "tok", "jdoe", "", "", "", "de"])
    out: list[str] = []
    rc = run_init(str(env), ask=ask, ask_secret=_scripted(["pw", ""]), out=out.append)
    assert rc == 0
    assert any("required" in m for m in out)


def test_init_invalid_url_reprompts(tmp_path):
    env = tmp_path / ".env"
    ask = _scripted(["not-a-url", "https://c.example.com", "bot", "tok", "jdoe", "", "", "", "de"])
    out: list[str] = []
    rc = run_init(str(env), ask=ask, ask_secret=_scripted(["pw", ""]), out=out.append)
    assert rc == 0
    assert any("http" in m for m in out)


def test_init_aborts_if_exists_and_declined(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KEEP=me\n")
    out: list[str] = []
    rc = run_init(
        str(env), ask=_scripted([]), ask_secret=_scripted([]), out=out.append, confirm=lambda _q: False
    )
    assert rc == 1
    assert env.read_text() == "KEEP=me\n"  # untouched
