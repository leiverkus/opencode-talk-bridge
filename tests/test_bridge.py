from __future__ import annotations

import threading

import pytest

from opencode_talk_bridge.bridge import Bridge, _parse_task_arg
from opencode_talk_bridge.config import Config
from opencode_talk_bridge.opencode import OpenCodeDownError, OpenCodeError, PermissionAsk, PromptResult
from opencode_talk_bridge.pending import PermissionPending
from opencode_talk_bridge.sessions import SessionStore
from opencode_talk_bridge.status import StatusWriter
from opencode_talk_bridge.talk import IncomingMessage

TOKEN = "tok"


class FakeGateway:
    own_user = "bot"

    def __init__(self):
        self.sent: list[str] = []
        self.edited: list[tuple[int, str]] = []
        self.shared: list[tuple[str, bytes, str]] = []
        self._mid = 0

    def send(self, token, text, reply_to=None):
        self.sent.append(text)
        self._mid += 1
        return self._mid

    def edit(self, token, message_id, text):
        self.edited.append((message_id, text))

    def upload_and_share(self, token, remote_path, content, *, caption=None, content_type="text/markdown"):
        self.shared.append((remote_path, content, caption))

    def download(self, path):
        return b"FILEBYTES"

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
        self.sessions_list: list[dict] = []
        self.models_list: list[dict] = []
        self.agents_list: list[dict] = []
        self.projects_list: list[dict] = []
        self.worktrees_list: list[str] = []
        self.commands_list: list[dict] = []
        self.skills_list: list[dict] = []
        self.messages_list: list[dict] = []
        self.mcps_dict: dict = {}
        self.created_dirs: list = []
        self.ran_commands: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.reverted: list[tuple[str, str]] = []
        self.toggled: list[tuple[str, bool]] = []
        self.prompts: list[tuple] = []
        self.listed_dirs: list[tuple] = []
        self._sid = 0

    def health(self):
        return not self.down

    def create_session(self, title=None, directory=None):
        self._sid += 1
        self.created_dirs.append(directory)
        return f"ses_{self._sid}"

    def prompt(self, session_id, text, model=None, agent=None, extra_parts=None):
        if self.down:
            raise OpenCodeDownError("down")
        self.prompts.append((text, extra_parts))
        return self.result

    def run_command(self, session_id, command, arguments=""):
        self.ran_commands.append(command)
        return self.result

    def rename_session(self, session_id, title):
        self.renamed.append((session_id, title))

    def revert(self, session_id, message_id, part_id=None):
        self.reverted.append((session_id, message_id))

    def fork(self, session_id, message_id):
        self._sid += 1
        return f"ses_fork_{self._sid}"

    def session_messages(self, session_id):
        return self.messages_list

    def list_projects(self):
        return self.projects_list

    def list_worktrees(self):
        return self.worktrees_list

    def list_commands(self, directory=None):
        self.listed_dirs.append(("commands", directory))
        return self.commands_list

    def list_skills(self, directory=None):
        self.listed_dirs.append(("skills", directory))
        return self.skills_list

    def list_mcps(self):
        return self.mcps_dict

    def toggle_mcp(self, name, enable):
        self.toggled.append((name, enable))
        return True

    def abort(self, session_id):
        self.aborted.append(session_id)
        return True

    def reply_permission(self, request_id, reply, message=None):
        if self.down:
            raise OpenCodeDownError("down")
        self.replies.append((request_id, reply))
        return True

    def reply_question(self, request_id, answer):
        if self.down:
            raise OpenCodeDownError("down")
        self.replies.append((request_id, answer))
        return True

    def list_sessions(self, directory=None):
        self.listed_dirs.append(("sessions", directory))
        return self.sessions_list

    def list_models(self):
        return self.models_list

    def list_agents(self):
        return self.agents_list

    def iter_events(self):
        return iter(())

    def close(self):
        pass


@pytest.fixture
def bridge(tmp_path, talk_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_USERS", "jdoe")
    monkeypatch.setenv("TALK_CONVERSATIONS", TOKEN)
    # Default to non-streaming so answers are posted (not edited); streaming has
    # its own dedicated tests.
    monkeypatch.setenv("RESPONSE_STREAMING", "false")
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


def _permission_pending(req_id="perm_1", session="ses_1"):
    return PermissionPending(
        PermissionAsk.from_request({"id": req_id, "sessionID": session, "permission": "bash"})
    )


def test_permission_reply_path(bridge):
    bridge._pending.set(TOKEN, _permission_pending())
    bridge._handle_message(TOKEN, _msg("ja"))
    assert bridge.oc.replies == [("perm_1", "once")]
    assert bridge._pending.has(TOKEN) is False


def test_permission_non_reply_falls_through_to_prompt(bridge):
    bridge._pending.set(TOKEN, _permission_pending())
    bridge._handle_message(TOKEN, _msg("actually do something else"))
    _join_workers(bridge)
    assert bridge.oc.replies == []  # not interpreted as a permission answer
    assert "done" in bridge.gw.sent


def test_opencode_down_notice(bridge):
    bridge.oc.down = True
    bridge._handle_message(TOKEN, _msg("do work"))
    _join_workers(bridge)
    assert any("nicht erreichbar" in m for m in bridge.gw.sent)


def test_attachment_used_for_large_output(bridge):
    # Config is a frozen dataclass; bypass for the test.
    object.__setattr__(bridge._cfg, "share_webdav_dir", "/Bridge")
    bridge.oc.result = PromptResult(text="```\n" + "x" * 4000 + "\n```", aborted=False, error=None)
    bridge._handle_message(TOKEN, _msg("give me code"))
    _join_workers(bridge)
    assert len(bridge.gw.shared) == 1
    path, content, caption = bridge.gw.shared[0]
    assert path.startswith("/Bridge/opencode-")
    assert content.startswith(b"```")


# --- Phase 1: streaming, tool messages, question, pickers -----------------

from opencode_talk_bridge.events import TextDelta, ToolEvent  # noqa: E402
from opencode_talk_bridge.opencode import QuestionAsk  # noqa: E402
from opencode_talk_bridge.pending import QuestionPending  # noqa: E402


def _bind(bridge, session_id="ses_1"):
    """Bind a session to the conversation and start a streamed turn.

    Throttle is set to 0 so every delta edits deterministically (the stream
    captures the throttle at construction time, so set it before _begin_turn).
    """
    bridge.store.set_session(TOKEN, session_id, now=1)
    bridge._load_session_map()
    object.__setattr__(bridge._cfg, "response_streaming", True)
    object.__setattr__(bridge._cfg, "stream_throttle_ms", 0)
    return bridge._begin_turn(session_id, TOKEN, msg_id=5)


def test_streaming_text_delta_edits(bridge):
    _bind(bridge)
    bridge._on_text(TextDelta("ses_1", "msg_1", "p1", "Hello"))
    bridge._on_text(TextDelta("ses_1", "msg_1", "p1", "Hello world"))
    assert bridge.gw.edited[-1] == (5, "Hello world")


def test_streaming_finalize_via_deliver(bridge):
    stream = _bind(bridge)
    bridge._deliver(TOKEN, PromptResult(text="final answer", aborted=False, error=None), stream)
    assert bridge.gw.edited[-1] == (5, "final answer")


def test_tool_message_announced_once(bridge):
    _bind(bridge)
    bridge._on_tool(ToolEvent("ses_1", "bash", "running", "c1"))
    bridge._on_tool(ToolEvent("ses_1", "bash", "completed", "c1"))  # same call -> no repeat
    bridge._on_tool(ToolEvent("ses_1", "read", "running", "c2"))
    tool_msgs = [m for m in bridge.gw.sent if "`bash`" in m or "`read`" in m]
    assert len(tool_msgs) == 2
    assert any("💻" in m for m in tool_msgs)


def test_tool_messages_hidden_when_configured(bridge):
    object.__setattr__(bridge._cfg, "hide_tool_messages", True)
    _bind(bridge)
    bridge._on_tool(ToolEvent("ses_1", "bash", "running", "c1"))
    assert not any("`bash`" in m for m in bridge.gw.sent)


def _question_pending(options, custom=False):
    return QuestionPending(
        QuestionAsk.from_request(
            {
                "id": "q1",
                "sessionID": "ses_1",
                "questions": [
                    {
                        "question": "Which?",
                        "header": "Choice",
                        "options": [{"label": o, "description": ""} for o in options],
                        "custom": custom,
                    }
                ],
            }
        )
    )


def test_question_answered_by_number(bridge):
    bridge._pending.set(TOKEN, _question_pending(["Yes", "No"]))
    bridge._handle_message(TOKEN, _msg("2"))
    assert bridge.oc.replies == [("q1", "No")]
    assert bridge._pending.has(TOKEN) is False


def test_question_custom_free_text(bridge):
    bridge._pending.set(TOKEN, _question_pending(["A"], custom=True))
    bridge._handle_message(TOKEN, _msg("my own answer"))
    assert bridge.oc.replies == [("q1", "my own answer")]


def test_sessions_picker_switches(bridge):
    bridge.oc.sessions_list = [{"id": "ses_a", "title": "Alpha"}, {"id": "ses_b", "title": "Beta"}]
    bridge._handle_message(TOKEN, _msg("/sessions"))
    assert bridge._pending.has(TOKEN) is True
    bridge._handle_message(TOKEN, _msg("2"))
    assert bridge.store.session_id_for(TOKEN) == "ses_b"
    assert bridge._pending.has(TOKEN) is False


def test_model_picker_sets_model(bridge):
    bridge.oc.models_list = [{"providerID": "anthropic", "id": "claude-x"}]
    bridge._handle_message(TOKEN, _msg("/model"))
    bridge._handle_message(TOKEN, _msg("1"))
    assert bridge.store.get(TOKEN).model == "anthropic/claude-x"


def test_agent_picker_sets_agent(bridge):
    bridge.oc.agents_list = [{"name": "plan", "description": "planning"}, {"name": "build"}]
    bridge._handle_message(TOKEN, _msg("/agent"))
    bridge._handle_message(TOKEN, _msg("1"))
    assert bridge.store.get(TOKEN).agent == "plan"


def test_agent_set_directly(bridge):
    bridge._handle_message(TOKEN, _msg("/agent build"))
    assert bridge.store.get(TOKEN).agent == "build"


def test_selection_non_number_falls_through(bridge):
    bridge.oc.sessions_list = [{"id": "ses_a", "title": "Alpha"}]
    bridge._handle_message(TOKEN, _msg("/sessions"))
    # A non-numeric message is treated as a new prompt, not a selection.
    bridge._handle_message(TOKEN, _msg("do something else"))
    _join_workers(bridge)
    assert "done" in bridge.gw.sent


# --- Phase 2: breadth commands --------------------------------------------


def test_rename_session(bridge):
    bridge.store.set_session(TOKEN, "ses_1", now=1)
    bridge._handle_message(TOKEN, _msg("/rename My Project"))
    assert bridge.oc.renamed == [("ses_1", "My Project")]


def test_detach_clears_session(bridge):
    bridge.store.set_session(TOKEN, "ses_1", now=1)
    bridge._handle_message(TOKEN, _msg("/detach"))
    assert bridge.store.session_id_for(TOKEN) is None


def test_projects_switch_sets_directory_and_clears_session(bridge):
    bridge.store.set_session(TOKEN, "ses_1", now=1)
    bridge.oc.projects_list = [
        {"name": "Repo A", "worktree": "/work/a"},
        {"name": "Repo B", "worktree": "/work/b"},
    ]
    bridge._handle_message(TOKEN, _msg("/projects"))
    bridge._handle_message(TOKEN, _msg("2"))
    state = bridge.store.get(TOKEN)
    assert state.directory == "/work/b"
    assert state.opencode_session_id is None  # session dropped for the new project


def test_new_session_uses_stored_directory(bridge):
    bridge.store.set_directory(TOKEN, "/work/b", now=1)
    bridge._handle_message(TOKEN, _msg("build something"))
    _join_workers(bridge)
    assert bridge.oc.created_dirs == ["/work/b"]


def test_sessions_listed_for_conversation_directory(bridge):
    # After /projects binds a directory, /sessions must list THAT project's
    # sessions (directory-scoped), not the global default.
    bridge.store.set_directory(TOKEN, "/work/proj-b", now=1)
    bridge.oc.sessions_list = [{"id": "ses_x", "title": "X"}]
    bridge._handle_message(TOKEN, _msg("/sessions"))
    assert ("sessions", "/work/proj-b") in bridge.oc.listed_dirs


def test_sessions_global_when_no_directory(bridge):
    # No project bound -> None -> server falls back to its default directory.
    bridge.oc.sessions_list = [{"id": "ses_x", "title": "X"}]
    bridge._handle_message(TOKEN, _msg("/sessions"))
    assert ("sessions", None) in bridge.oc.listed_dirs


def test_worktree_switch(bridge):
    bridge.oc.worktrees_list = ["/wt/main", "/wt/feature"]
    bridge._handle_message(TOKEN, _msg("/worktree"))
    bridge._handle_message(TOKEN, _msg("1"))
    assert bridge.store.get(TOKEN).directory == "/wt/main"


def test_commands_picker_runs_command(bridge):
    bridge.oc.commands_list = [{"name": "review", "description": "review code", "source": "command"}]
    bridge._handle_message(TOKEN, _msg("/commands"))
    bridge._handle_message(TOKEN, _msg("1"))
    _join_workers(bridge)
    assert bridge.oc.ran_commands == ["review"]


def test_commands_picker_excludes_skills(bridge):
    bridge.oc.commands_list = [
        {"name": "review", "source": "command"},
        {"name": "pdf", "source": "skill"},
    ]
    bridge._handle_message(TOKEN, _msg("/commands"))
    pending = bridge._pending.get(TOKEN)
    assert [i.value for i in pending.items] == ["review"]  # skill filtered out


def test_skills_picker_runs_skill(bridge):
    bridge.oc.skills_list = [{"name": "pdf", "description": "PDF skill"}]
    bridge._handle_message(TOKEN, _msg("/skills"))
    bridge._handle_message(TOKEN, _msg("1"))
    _join_workers(bridge)
    assert bridge.oc.ran_commands == ["pdf"]


def test_mcps_toggle(bridge):
    bridge.oc.mcps_dict = {"zotero": {"enabled": True}}
    bridge._handle_message(TOKEN, _msg("/mcps"))
    bridge._handle_message(TOKEN, _msg("1"))
    assert bridge.oc.toggled == [("zotero", False)]  # was enabled -> disable


def test_messages_revert_flow(bridge):
    bridge.store.set_session(TOKEN, "ses_1", now=1)
    bridge.oc.messages_list = [
        {"info": {"id": "msg_1", "role": "user"}, "parts": [{"type": "text", "text": "first request"}]},
    ]
    bridge._handle_message(TOKEN, _msg("/messages"))
    bridge._handle_message(TOKEN, _msg("1"))  # pick the message
    bridge._handle_message(TOKEN, _msg("1"))  # pick "Revert"
    assert bridge.oc.reverted == [("ses_1", "msg_1")]


def test_tts_requires_config(bridge):
    bridge._handle_message(TOKEN, _msg("/tts"))
    assert any("nicht konfiguriert" in m for m in bridge.gw.sent)


def test_tts_toggle_when_configured(bridge):
    object.__setattr__(bridge._cfg, "tts_url", "http://tts")
    object.__setattr__(bridge._cfg, "tts_key", "k")
    bridge._handle_message(TOKEN, _msg("/tts"))
    assert bridge.store.get(TOKEN).tts_enabled is True


def test_background_session_notification(bridge):
    # A mapped session going idle without an active turn -> background notice.
    bridge.store.set_session(TOKEN, "ses_bg", now=1)
    bridge._load_session_map()
    from opencode_talk_bridge.events import SessionIdle

    bridge._handle_event({"type": "session.idle", "properties": {"sessionID": "ses_bg"}})
    assert any("Hintergrund" in m or "Background" in m for m in bridge.gw.sent)
    assert isinstance(SessionIdle("x"), SessionIdle)


def test_foreground_idle_no_notification(bridge):
    bridge.store.set_session(TOKEN, "ses_fg", now=1)
    bridge._load_session_map()
    bridge._begin_turn("ses_fg", TOKEN, msg_id=None)  # active turn
    bridge._handle_event({"type": "session.idle", "properties": {"sessionID": "ses_fg"}})
    assert not any("Hintergrund" in m for m in bridge.gw.sent)


# --- Phase 3: voice, files, scheduled tasks -------------------------------

from opencode_talk_bridge.scheduler import TaskStore  # noqa: E402
from opencode_talk_bridge.talk import FileRef  # noqa: E402


class FakeSTT:
    def transcribe(self, audio, filename="audio.ogg"):
        return "transcribed prompt"


class FakeTTS:
    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        return b"AUDIO"


def _audio_msg():
    return IncomingMessage(
        id=1,
        actor_id="jdoe",
        actor_type="users",
        actor_display_name="jdoe",
        text="",
        timestamp=0,
        is_system=False,
        files=(FileRef("v.ogg", "/v.ogg", "audio/ogg"),),
    )


def _file_msg():
    return IncomingMessage(
        id=1,
        actor_id="jdoe",
        actor_type="users",
        actor_display_name="jdoe",
        text="review this",
        timestamp=0,
        is_system=False,
        files=(FileRef("a.py", "/a.py", "text/x-python"),),
    )


def test_voice_input_transcribed_into_prompt(bridge):
    bridge._stt = FakeSTT()
    bridge._handle_message(TOKEN, _audio_msg())
    _join_workers(bridge)
    assert bridge.oc.prompts[-1][0] == "transcribed prompt"


def test_file_input_becomes_part(bridge):
    bridge._handle_message(TOKEN, _file_msg())
    _join_workers(bridge)
    text, extra_parts = bridge.oc.prompts[-1]
    assert text == "review this"
    assert extra_parts and extra_parts[0]["type"] == "file"
    assert extra_parts[0]["url"].startswith("data:text/x-python;base64,")


def test_tts_shares_audio_on_delivery(bridge):
    object.__setattr__(bridge._cfg, "share_webdav_dir", "/Bridge")
    bridge._tts = FakeTTS()
    bridge.store.set_tts(TOKEN, True, now=1)
    bridge._handle_message(TOKEN, _msg("say something"))
    _join_workers(bridge)
    assert bridge._tts.calls == ["done"]
    assert any(p.endswith(".mp3") for p, _c, _cap in bridge.gw.shared)


def test_task_create_and_list_delete(bridge, tmp_path):
    bridge._task_store = TaskStore(str(tmp_path / "tasks.sqlite3"))
    bridge._handle_message(TOKEN, _msg("/task 30 run the suite"))
    assert bridge._task_store.count() == 1
    bridge._handle_message(TOKEN, _msg("/tasklist"))
    bridge._handle_message(TOKEN, _msg("1"))  # pick the task -> delete
    assert bridge._task_store.count() == 0
    bridge._task_store.close()


def test_task_recurring_parse(bridge, tmp_path):
    bridge._task_store = TaskStore(str(tmp_path / "tasks.sqlite3"))
    bridge._handle_message(TOKEN, _msg("/task every 60 ping"))
    task = bridge._task_store.list(TOKEN)[0]
    assert task.interval_s == 3600
    assert task.prompt == "ping"
    bridge._task_store.close()


def test_task_invalid_syntax(bridge, tmp_path):
    bridge._task_store = TaskStore(str(tmp_path / "tasks.sqlite3"))
    bridge._handle_message(TOKEN, _msg("/task nonsense"))
    assert bridge._task_store.count() == 0
    assert any("Nutzung" in m or "Usage" in m for m in bridge.gw.sent)
    bridge._task_store.close()


def test_no_attachment_without_webdav_dir(bridge):
    # share_webdav_dir is unset by default -> long output posted as text.
    bridge.oc.result = PromptResult(text="x" * 4000, aborted=False, error=None)
    bridge._handle_message(TOKEN, _msg("give me lots"))
    _join_workers(bridge)
    assert bridge.gw.shared == []
    assert any(len(m) > 3000 for m in bridge.gw.sent)


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


# --- review hardening: error isolation + /task validation -----------------


def test_prompt_opencode_error_does_not_leak_server_text(bridge):
    # An OpenCode HTTP error's message includes server response body; the worker
    # must post only a generic message and keep the body out of the chat.
    def boom(session_id, text, model=None, agent=None, extra_parts=None):
        raise OpenCodeError("/session/x/message -> HTTP 500: SECRET_SERVER_BODY")

    bridge.oc.prompt = boom
    bridge._handle_message(TOKEN, _msg("do work"))
    _join_workers(bridge)
    assert not any("SECRET_SERVER_BODY" in m for m in bridge.gw.sent)
    assert any("OpenCode-Fehler" in m or "OpenCode error" in m for m in bridge.gw.sent)


def test_session_setup_opencode_error_does_not_leak(bridge):
    def boom(title=None, directory=None):
        raise OpenCodeError("/session -> HTTP 503: ANOTHER_SECRET")

    bridge.oc.create_session = boom
    bridge._handle_message(TOKEN, _msg("hi there"))
    _join_workers(bridge)
    assert not any("ANOTHER_SECRET" in m for m in bridge.gw.sent)
    assert any("OpenCode-Fehler" in m or "OpenCode error" in m for m in bridge.gw.sent)


def test_command_opencode_error_does_not_escape(bridge):
    # An OpenCode HTTP 4xx/5xx in a command handler must be caught (not kill the
    # poll thread) and surface a clean message.
    def boom(_directory=None):
        raise OpenCodeError("HTTP 500")

    bridge.oc.list_sessions = boom
    # Drive it the way the poll loop does (through the isolation wrapper).
    try:
        bridge._handle_message(TOKEN, _msg("/sessions"))
    except Exception as exc:  # pragma: no cover - must not happen
        raise AssertionError(f"command error escaped: {exc}") from exc
    assert any("OpenCode-Fehler" in m or "OpenCode error" in m for m in bridge.gw.sent)


def test_poll_loop_isolates_unexpected_errors(bridge):
    # Drive the REAL _poll_loop: a non-OpenCode bug while handling a message must
    # not kill the poll thread — it logs, notifies, and keeps polling.
    def kaboom(_directory=None):
        raise RuntimeError("unexpected bug")

    bridge.oc.list_sessions = kaboom

    calls = {"n": 0}

    def fake_poll(token, last_id, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_msg("/sessions", mid=5)]
        bridge._stop.set()  # end the loop after the second poll
        return []

    bridge.gw.poll = fake_poll
    bridge._poll_loop(TOKEN)  # must return cleanly, not raise

    assert calls["n"] >= 2  # kept polling after the bad message
    assert any("Unerwartet" in x or "Unexpected" in x for x in bridge.gw.sent)


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("30 do the thing", (1800, 0, "do the thing")),
        ("every 60 ping", (3600, 3600, "ping")),
        ("0 now please", None),  # 0 minutes rejected
        ("every 0 loop", None),  # 0-minute interval rejected
        ("5", None),  # no prompt
        ("nonsense prompt", None),  # non-numeric minutes
        ("every 5", None),  # recurring without prompt
    ],
)
def test_parse_task_arg(arg, expected):
    assert _parse_task_arg(arg) == expected


def test_task_zero_minutes_rejected(bridge, tmp_path):
    from opencode_talk_bridge.scheduler import TaskStore

    bridge._task_store = TaskStore(str(tmp_path / "t.sqlite3"))
    bridge._handle_message(TOKEN, _msg("/task 0 immediately"))
    assert bridge._task_store.count() == 0
    bridge._task_store.close()
