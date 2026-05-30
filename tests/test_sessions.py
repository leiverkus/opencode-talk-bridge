from __future__ import annotations

from opencode_talk_bridge.sessions import SessionStore


def test_get_or_create_and_defaults(tmp_path):
    store = SessionStore(str(tmp_path / "b.sqlite3"))
    state = store.get_or_create("tok")
    assert state.token == "tok"
    assert state.opencode_session_id is None
    assert state.last_known_message_id == 0
    store.close()


def test_set_and_read_back(tmp_path):
    store = SessionStore(str(tmp_path / "b.sqlite3"))
    store.get_or_create("tok")
    store.set_session("tok", "ses_1", now=10)
    store.set_model("tok", "anthropic/claude", now=11)
    store.update_last_message_id("tok", 42, now=12)
    state = store.get("tok")
    assert state.opencode_session_id == "ses_1"
    assert state.model == "anthropic/claude"
    assert state.last_known_message_id == 42
    assert store.session_id_for("tok") == "ses_1"
    store.close()


def test_clear_session_keeps_last_id(tmp_path):
    store = SessionStore(str(tmp_path / "b.sqlite3"))
    store.set_session("tok", "ses_1", now=1)
    store.update_last_message_id("tok", 99, now=2)
    store.clear_session("tok", now=3)
    state = store.get("tok")
    assert state.opencode_session_id is None
    assert state.last_known_message_id == 99
    store.close()


def test_persistence_across_reopen(tmp_path):
    path = str(tmp_path / "b.sqlite3")
    store = SessionStore(path)
    store.set_session("tok", "ses_persist", now=1)
    store.update_last_message_id("tok", 7, now=1)
    store.close()

    reopened = SessionStore(path)
    state = reopened.get("tok")
    assert state.opencode_session_id == "ses_persist"
    assert state.last_known_message_id == 7
    reopened.close()


def test_upsert_creates_row_without_get_or_create(tmp_path):
    store = SessionStore(str(tmp_path / "b.sqlite3"))
    store.update_last_message_id("fresh", 5, now=1)
    assert store.get("fresh").last_known_message_id == 5
    store.close()
