from __future__ import annotations

import threading

import pytest

from opencode_talk_bridge.bridge import Bridge
from opencode_talk_bridge.config import Config
from opencode_talk_bridge.opencode import OpenCodeDownError, PermissionAsk, PromptResult
from opencode_talk_bridge.sessions import SessionStore
from opencode_talk_bridge.status import StatusWriter
from opencode_talk_bridge.talk import IncomingMessage

TOKEN = "tok"


class FakeGateway:
    own_user = "bot"

    def __init__(self):
        self.sent: list[str] = []
        self.shared: list[tuple[str, str]] = []

    def send(self, token, text, reply_to=None):
        self.sent.append(text)

    def share_file(self, token, path, caption=None):
        self.shared.append((path, caption))

    def latest_message_id(self, token):
        return 0

    def list_conversations(self):
        return []


class FakeOpenCode:
    def __init__(self):
        self.aborted: list[str] = []
        self.replies: list[tuple[str, str]] = []
        self.down = False
        self.result = PromptResult(text="done", aborted=False, error=None)
        self._sid = 0

    def health(self):
        return not self.down

    def create_session(self, title=None):
        self._sid += 1
        return f"ses_{self._sid}"

    def prompt(self, session_id, text, model=None):
        if self.down:
            raise OpenCodeDownError("down")
        return self.result

    def abort(self, session_id):
        self.aborted.append(session_id)
        return True

    def reply_permission(self, request_id, reply, message=None):
        if self.down:
            raise OpenCodeDownError("down")
        self.replies.append((request_id, reply))
        return True

    def iter_events(self):
        return iter(())

    def close(self):
        pass


@pytest.fixture
def bridge(tmp_path, talk_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_USERS", "jdoe")
    monkeypatch.setenv("TALK_CONVERSATIONS", TOKEN)
    cfg = Config.from_env()
    gw = FakeGateway()
    oc = FakeOpenCode()
    store = SessionStore(str(tmp_path / "b.sqlite3"))
    status = StatusWriter(str(tmp_path / "status.json"))
    b = Bridge(cfg, gw, oc, store, status)
    b.gw, b.oc, b.store = gw, oc, store  # expose for assertions
    yield b
    store.close()


def _msg(text, actor_id="jdoe", actor_type="users", is_system=False, mid=1):
    return IncomingMessage(
        id=mid,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_display_name=actor_id,
        text=text,
        timestamp=0,
        is_system=is_system,
    )


def _join_workers(bridge):
    for t in list(bridge._busy.values()):
        if isinstance(t, threading.Thread):
            t.join(timeout=5)


def test_foreign_user_ignored(bridge):
    bridge._handle_message(TOKEN, _msg("hello", actor_id="mallory"))
    _join_workers(bridge)
    assert bridge.gw.sent == []


def test_system_message_ignored(bridge):
    bridge._handle_message(TOKEN, _msg("x joined", is_system=True))
    assert bridge.gw.sent == []


def test_own_message_ignored(bridge):
    bridge._handle_message(TOKEN, _msg("loop?", actor_id="bot"))
    assert bridge.gw.sent == []


def test_plain_prompt_runs_and_delivers(bridge):
    bridge._handle_message(TOKEN, _msg("fix the bug"))
    _join_workers(bridge)
    # working notice + final answer
    assert any("arbeitet" in m for m in bridge.gw.sent)
    assert "done" in bridge.gw.sent
    assert bridge.store.session_id_for(TOKEN) == "ses_1"


def test_help_command(bridge):
    bridge._handle_message(TOKEN, _msg("/help"))
    assert any("opencode-talk-bridge" in m for m in bridge.gw.sent)


def test_stop_command_aborts_session(bridge):
    bridge.store.set_session(TOKEN, "ses_42", now=1)
    bridge._handle_message(TOKEN, _msg("/stop"))
    assert bridge.oc.aborted == ["ses_42"]


def test_model_command_sets_model(bridge):
    bridge._handle_message(TOKEN, _msg("/model anthropic/claude"))
    assert bridge.store.get(TOKEN).model == "anthropic/claude"


def test_permission_reply_path(bridge):
    bridge._pending.set(
        TOKEN, PermissionAsk.from_request({"id": "perm_1", "sessionID": "ses_1", "permission": "bash"})
    )
    bridge._handle_message(TOKEN, _msg("ja"))
    assert bridge.oc.replies == [("perm_1", "once")]
    assert bridge._pending.has(TOKEN) is False


def test_permission_non_reply_falls_through_to_prompt(bridge):
    bridge._pending.set(
        TOKEN, PermissionAsk.from_request({"id": "perm_1", "sessionID": "ses_1", "permission": "bash"})
    )
    bridge._handle_message(TOKEN, _msg("actually do something else"))
    _join_workers(bridge)
    assert bridge.oc.replies == []  # not interpreted as a permission answer
    assert "done" in bridge.gw.sent


def test_opencode_down_notice(bridge):
    bridge.oc.down = True
    bridge._handle_message(TOKEN, _msg("do work"))
    _join_workers(bridge)
    assert any("nicht erreichbar" in m for m in bridge.gw.sent)


def test_attachment_used_for_large_output(bridge, tmp_path):
    share = tmp_path / "share"
    # Config is a frozen dataclass; bypass for the test.
    object.__setattr__(bridge._cfg, "share_dir", str(share))
    object.__setattr__(bridge._cfg, "share_webdav_root", "/Bridge")
    bridge.oc.result = PromptResult(text="```\n" + "x" * 4000 + "\n```", aborted=False, error=None)
    bridge._handle_message(TOKEN, _msg("give me code"))
    _join_workers(bridge)
    assert len(bridge.gw.shared) == 1
    path, caption = bridge.gw.shared[0]
    assert path.startswith("/Bridge/opencode-")


def test_permission_asked_event_routes_to_conversation(bridge):
    bridge.store.set_session(TOKEN, "ses_9", now=1)
    bridge._load_session_map()
    bridge._handle_event(
        {
            "type": "permission.asked",
            "properties": {
                "id": "perm_x",
                "sessionID": "ses_9",
                "permission": "edit",
                "patterns": ["foo.py"],
            },
        }
    )
    assert bridge._pending.has(TOKEN) is True
    assert any("OpenCode möchte" in m for m in bridge.gw.sent)
