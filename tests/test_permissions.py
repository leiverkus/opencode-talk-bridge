from __future__ import annotations

import pytest

from opencode_talk_bridge.opencode import PermissionAsk
from opencode_talk_bridge.permissions import (
    PendingPermissions,
    format_prompt,
    interpret_reply,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ja", "once"),
        ("Yes", "once"),
        ("y", "once"),
        ("ok", "once"),
        ("immer", "always"),
        ("always", "always"),
        ("nein", "reject"),
        ("no", "reject"),
        ("reject", "reject"),
        ("maybe later", None),
        ("", None),
    ],
)
def test_interpret_reply(text, expected):
    assert interpret_reply(text) == expected


def _ask(**kw) -> PermissionAsk:
    base = dict(id="perm_1", sessionID="ses_1", permission="bash", patterns=["git status*"], tool={})
    base.update(kw)
    return PermissionAsk.from_request(base)


def test_format_prompt_includes_kind_and_pattern():
    text = format_prompt(_ask())
    assert "bash" in text
    assert "git status*" in text
    assert "ja" in text and "nein" in text


def test_format_prompt_truncates_long_pattern():
    text = format_prompt(_ask(patterns=["x" * 500]))
    assert "…" in text
    assert len(text) < 300


def test_pending_registry_roundtrip():
    p = PendingPermissions()
    assert p.has("tok") is False
    ask = _ask()
    p.set("tok", ask)
    assert p.has("tok") is True
    assert p.get("tok") is ask
    assert p.pop("tok") is ask
    assert p.has("tok") is False
    assert p.pop("tok") is None


def test_newer_ask_replaces_older():
    p = PendingPermissions()
    p.set("tok", _ask(id="perm_1"))
    p.set("tok", _ask(id="perm_2"))
    assert p.get("tok").request_id == "perm_2"
