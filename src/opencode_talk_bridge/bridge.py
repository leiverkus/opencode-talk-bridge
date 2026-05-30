"""Bridge orchestration: glue Nextcloud Talk polling to the OpenCode server.

Threading model (sync throughout, to match ``nextcloud-talk-core``):

  - One **poll thread per watched conversation** runs a Talk long-poll loop.
  - One **SSE thread** consumes ``/global/event`` for the whole server, routes
    permission/question asks to the bound conversation, and feeds streaming text
    deltas + tool/thinking notices into the live answer message.
  - Each prompt runs in an **ephemeral worker thread**, because
    ``POST /session/{id}/message`` blocks until the turn finishes — and that turn
    may pause for a permission/question whose reply arrives on the conversation's
    poll loop. Running the prompt inline would deadlock that handshake.

Talk has no inline buttons, so every interactive flow (permission, question,
list picker) is a **pending interaction** resolved by the next reply
(see ``pending.py``). Live streaming uses Talk message editing (``streaming.py``).
Shared in-memory maps are guarded by ``self._lock``.
"""

from __future__ import annotations

import base64
import logging
import threading
import time

from . import commands
from .allowlist import Allowlist
from .config import Config
from .events import (
    PermissionEvent,
    QuestionEvent,
    ReasoningDelta,
    SessionError,
    SessionIdle,
    TextDelta,
    ToolEvent,
    classify,
)
from .messages import translator
from .opencode import OpenCodeClient, OpenCodeDownError, PermissionAsk, PromptResult, QuestionAsk
from .pending import (
    PendingRegistry,
    PermissionPending,
    QuestionPending,
    SelectionPending,
    SelectItem,
    format_question,
    format_selection,
    parse_choice,
)
from .permissions import format_prompt, interpret_reply
from .scheduler import Scheduler, TaskStore
from .sessions import SessionStore
from .status import StatusWriter
from .streaming import StreamState
from .stt import STTClient, STTError
from .talk import FileRef, IncomingMessage, NextcloudTalkError, TalkGateway, WebDavError
from .tts import TTSClient, TTSError

log = logging.getLogger(__name__)

_TOOL_EMOJI = {
    "bash": "💻",
    "read": "📖",
    "edit": "✏️",
    "write": "✏️",
    "grep": "🔎",
    "glob": "🔎",
    "list": "📂",
    "webfetch": "🌐",
    "todowrite": "📝",
    "task": "🤖",
}


class Bridge:
    def __init__(
        self,
        config: Config,
        gateway: TalkGateway,
        opencode: OpenCodeClient,
        store: SessionStore,
        status: StatusWriter,
        *,
        stt: STTClient | None = None,
        tts: TTSClient | None = None,
        task_store: TaskStore | None = None,
    ) -> None:
        self._cfg = config
        self._talk = gateway
        self._oc = opencode
        self._store = store
        self._status = status
        self._stt = stt
        self._tts = tts
        self._task_store = task_store
        self._scheduler: Scheduler | None = None
        self._allow = Allowlist(config.allowed_users)
        self._pending = PendingRegistry()
        self._t = translator(config.bot_locale)

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._session_to_token: dict[str, str] = {}
        self._busy: dict[str, threading.Thread] = {}
        self._streams: dict[str, StreamState] = {}
        self._announced: dict[str, set[str]] = {}  # session_id -> announced tool/thinking keys
        self._threads: list[threading.Thread] = []

    # --- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Start all threads and block until stopped."""
        tokens = self._resolve_tokens()
        if not tokens:
            raise RuntimeError("no conversations to watch — check TALK_CONVERSATIONS")
        self._load_session_map()

        self._status.update(
            state="polling", since=_now(), conversations=tokens, opencode_healthy=self._oc.health()
        )

        if self._task_store is not None:
            self._scheduler = Scheduler(self._task_store, self._run_scheduled)
            self._scheduler.start()

        sse = threading.Thread(target=self._sse_loop, name="sse", daemon=True)
        sse.start()
        self._threads.append(sse)
        for token in tokens:
            t = threading.Thread(target=self._poll_loop, args=(token,), name=f"poll:{token}", daemon=True)
            t.start()
            self._threads.append(t)

        log.info("bridge running, watching %d conversation(s)", len(tokens))
        try:
            while not self._stop.is_set():
                self._stop.wait(1.0)
        finally:
            self._status.update(state="stopped")

    def stop(self) -> None:
        log.info("stopping bridge")
        self._stop.set()
        if self._scheduler is not None:
            self._scheduler.stop()
        # Closing the OpenCode client breaks the blocking SSE stream.
        self._oc.close()

    def _run_scheduled(self, token: str, prompt: str) -> None:
        self._start_prompt(token, prompt)

    def _resolve_tokens(self) -> list[str]:
        if not self._cfg.watch_all:
            return list(self._cfg.conversations)
        try:
            return [c.token for c in self._talk.list_conversations()]
        except NextcloudTalkError as exc:
            log.error("could not list conversations: %s", exc)
            return []

    def _load_session_map(self) -> None:
        # Re-bind sessionID -> token for any conversations with a stored session.
        for token in self._resolve_tokens():
            sid = self._store.session_id_for(token)
            if sid:
                with self._lock:
                    self._session_to_token[sid] = token

    # --- Talk poll loop ----------------------------------------------------

    def _poll_loop(self, token: str) -> None:
        state = self._store.get_or_create(token)
        last_id = state.last_known_message_id
        if last_id == 0:
            try:
                last_id = self._talk.latest_message_id(token)
                self._store.update_last_message_id(token, last_id, now=_now())
            except NextcloudTalkError as exc:
                log.warning("[%s] could not init cursor: %s", token, exc)

        while not self._stop.is_set():
            try:
                messages = self._talk.poll(token, last_id, timeout=self._cfg.poll_timeout)
            except NextcloudTalkError as exc:
                log.warning("[%s] poll error: %s", token, exc)
                self._stop.wait(2.0)
                continue
            for msg in messages:
                last_id = max(last_id, msg.id)
                self._store.update_last_message_id(token, last_id, now=_now())
                if self._stop.is_set():
                    break
                self._handle_message(token, msg)

    def _handle_message(self, token: str, msg: IncomingMessage) -> None:
        # Never react to system messages or our own posts (avoids loops).
        if msg.is_system or msg.actor_id == self._talk.own_user:
            return

        allowed = self._allow.is_allowed(msg.actor_id, msg.actor_type)

        # A pending interaction (permission/question/selection) takes priority:
        # an allowlisted user's reply may resolve it.
        pending = self._pending.get(token)
        if pending is not None and allowed and self._resolve_pending(token, pending, msg.text):
            return

        if not allowed:
            log.info("[%s] ignoring message from %s (%s)", token, msg.actor_id, msg.actor_type)
            return

        parsed = commands.parse(msg.text)
        if isinstance(parsed, commands.Command):
            self._handle_command(token, parsed)
        elif parsed.text or msg.files:
            self._start_prompt(token, parsed.text, msg.files)

    # --- pending interaction resolution -----------------------------------

    def _resolve_pending(self, token: str, pending: object, text: str) -> bool:
        """Try to resolve the pending interaction. Returns True if consumed."""
        if isinstance(pending, PermissionPending):
            outcome = interpret_reply(text)
            if outcome is None:
                return False
            self._pending.pop(token)
            self._answer_permission(token, pending.ask, outcome)
            return True
        if isinstance(pending, QuestionPending):
            return self._answer_question(token, pending.ask, text)
        if isinstance(pending, SelectionPending):
            idx = parse_choice(text, len(pending.items))
            if idx is None:
                return False
            self._pending.pop(token)
            pending.on_select(pending.items[idx].value)
            return True
        return False

    def _answer_permission(self, token: str, ask: PermissionAsk, outcome: str) -> None:
        try:
            self._oc.reply_permission(ask.request_id, outcome)
            self._say(
                token,
                self._t({"once": "perm_once", "always": "perm_always", "reject": "perm_reject"}[outcome]),
            )
        except OpenCodeDownError:
            self._say(token, self._t("down"))

    def _answer_question(self, token: str, ask: QuestionAsk, text: str) -> bool:
        answer: str | None = None
        if ask.options:
            idx = parse_choice(text, len(ask.options))
            if idx is not None:
                answer = ask.options[idx].label
            elif ask.custom and text.strip():
                answer = text.strip()
            else:
                return False
        else:
            answer = text.strip()
        if not answer:
            return False
        self._pending.pop(token)
        try:
            self._oc.reply_question(ask.request_id, answer)
            self._say(token, self._t("answered", answer=answer))
        except OpenCodeDownError:
            self._say(token, self._t("down"))
        return True

    # --- commands ----------------------------------------------------------

    def _handle_command(self, token: str, cmd: commands.Command) -> None:
        handlers = {
            "help": lambda: self._say(token, self._t("help")),
            "new": lambda: self._cmd_new(token),
            "session": lambda: self._cmd_session(token),
            "sessions": lambda: self._cmd_sessions(token),
            "model": lambda: self._handle_model(token, cmd.arg),
            "agent": lambda: self._handle_agent(token, cmd.arg),
            "projects": lambda: self._cmd_projects(token),
            "worktree": lambda: self._cmd_worktree(token),
            "messages": lambda: self._cmd_messages(token),
            "commands": lambda: self._cmd_commands(token),
            "mcps": lambda: self._cmd_mcps(token),
            "rename": lambda: self._cmd_rename(token, cmd.arg),
            "detach": lambda: self._cmd_detach(token),
            "tts": lambda: self._cmd_tts(token),
            "task": lambda: self._cmd_task(token, cmd.arg),
            "tasklist": lambda: self._cmd_tasklist(token),
            "stop": lambda: self._handle_stop(token),
            "status": lambda: self._handle_status(token),
        }
        handler = handlers.get(cmd.name)
        if handler:
            handler()

    def _cmd_new(self, token: str) -> None:
        self._store.clear_session(token, now=_now())
        self._say(token, self._t("new_session"))

    def _cmd_session(self, token: str) -> None:
        sid = self._store.session_id_for(token)
        self._say(token, self._t("session_is", sid=sid) if sid else self._t("no_session_yet"))

    def _cmd_sessions(self, token: str) -> None:
        try:
            sessions = self._oc.list_sessions()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        sessions = sessions[: self._cfg.list_limit]
        if not sessions:
            self._say(token, self._t("no_sessions"))
            return
        items = [
            SelectItem(
                label=(s.get("title") or s.get("id", "?")), value=s["id"], description=s.get("id", "")[:12]
            )
            for s in sessions
            if s.get("id")
        ]
        self._offer_selection(
            token, self._t("title_sessions"), items, lambda sid: self._switch_session(token, sid)
        )

    def _switch_session(self, token: str, session_id: str) -> None:
        self._store.set_session(token, session_id, now=_now())
        with self._lock:
            self._session_to_token[session_id] = token
        self._say(token, self._t("session_switched", sid=session_id))

    def _cmd_rename(self, token: str, arg: str) -> None:
        sid = self._store.session_id_for(token)
        if not sid:
            self._say(token, self._t("no_session_rename"))
            return
        if not arg:
            self._say(token, self._t("rename_usage"))
            return
        try:
            self._oc.rename_session(sid, arg.strip())
            self._say(token, self._t("renamed", title=arg.strip()))
        except OpenCodeDownError:
            self._say(token, self._t("down"))

    def _cmd_detach(self, token: str) -> None:
        self._store.clear_session(token, now=_now())
        self._say(token, self._t("detached"))

    def _cmd_tts(self, token: str) -> None:
        if not (self._cfg.tts_url and self._cfg.tts_key):
            self._say(token, self._t("tts_unconfigured"))
            return
        state = self._store.get(token)
        new_value = not (state.tts_enabled if state else False)
        self._store.set_tts(token, new_value, now=_now())
        self._say(token, self._t("tts_on" if new_value else "tts_off"))

    def _cmd_task(self, token: str, arg: str) -> None:
        if self._task_store is None:
            self._say(token, self._t("no_scheduler"))
            return
        parsed = _parse_task_arg(arg)
        if parsed is None:
            self._say(token, self._t("task_usage"))
            return
        run_in, interval, prompt = parsed
        if self._task_store.count() >= self._cfg.task_limit:
            self._say(token, self._t("task_limit", limit=self._cfg.task_limit))
            return
        now = _now()
        self._task_store.add(token, prompt, now + run_in, interval, now=now)
        self._say(token, self._t("task_created", minutes=run_in // 60))

    def _cmd_tasklist(self, token: str) -> None:
        if self._task_store is None:
            self._say(token, self._t("no_scheduler"))
            return
        tasks = self._task_store.list(token)
        if not tasks:
            self._say(token, self._t("task_none"))
            return
        items = [
            SelectItem(
                label=(t.prompt[:40] + ("…" if len(t.prompt) > 40 else "")),
                value=str(t.id),
                description=("⟳" if t.interval_s else ""),
            )
            for t in tasks
        ]
        self._offer_selection(token, self._t("title_tasks"), items, lambda tid: self._delete_task(token, tid))

    def _delete_task(self, token: str, task_id: str) -> None:
        if self._task_store is not None:
            self._task_store.delete(int(task_id))
            self._say(token, self._t("task_deleted"))

    def _cmd_projects(self, token: str) -> None:
        try:
            projects = self._oc.list_projects()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        items = [
            SelectItem(label=(p.get("name") or p.get("worktree", "?")), value=p.get("worktree", ""))
            for p in projects[: self._cfg.list_limit]
            if p.get("worktree")
        ]
        if not items:
            self._say(token, self._t("no_projects"))
            return
        self._offer_selection(
            token, self._t("title_projects"), items, lambda d: self._switch_directory(token, d, "project")
        )

    def _cmd_worktree(self, token: str) -> None:
        try:
            worktrees = self._oc.list_worktrees()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        items = [SelectItem(label=w, value=w) for w in worktrees[: self._cfg.list_limit]]
        if not items:
            self._say(token, self._t("no_worktrees"))
            return
        self._offer_selection(
            token, self._t("title_worktrees"), items, lambda d: self._switch_directory(token, d, "worktree")
        )

    def _switch_directory(self, token: str, directory: str, kind: str) -> None:
        # Switching project/worktree binds future sessions to a new directory;
        # drop the current session so the next prompt creates one there.
        self._store.set_directory(token, directory, now=_now())
        self._store.clear_session(token, now=_now())
        label = self._t("title_projects" if kind == "project" else "title_worktrees").strip(": 📁🌿")
        self._say(token, self._t("dir_switched", kind=label, directory=directory))

    def _cmd_commands(self, token: str) -> None:
        try:
            cmds = self._oc.list_commands()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        items = [
            SelectItem(label=c["name"], value=c["name"], description=(c.get("description") or "")[:40])
            for c in cmds[: self._cfg.list_limit]
            if c.get("name")
        ]
        if not items:
            self._say(token, self._t("no_commands"))
            return
        self._offer_selection(
            token, self._t("title_commands"), items, lambda name: self._run_command(token, name)
        )

    def _run_command(self, token: str, name: str) -> None:
        self._start_command(token, name)

    def _cmd_mcps(self, token: str) -> None:
        try:
            mcps = self._oc.list_mcps()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        names = list(mcps.keys())[: self._cfg.list_limit]
        if not names:
            self._say(token, self._t("no_mcps"))
            return
        items = [SelectItem(label=n, value=n) for n in names]
        self._offer_selection(token, self._t("title_mcps"), items, lambda n: self._toggle_mcp(token, n, mcps))

    def _toggle_mcp(self, token: str, name: str, mcps: dict) -> None:
        cfg = mcps.get(name) or {}
        currently = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
        try:
            self._oc.toggle_mcp(name, not currently)
            state = self._t("mcp_off" if currently else "mcp_on")
            self._say(token, self._t("mcp_toggled", name=name, state=state))
        except OpenCodeDownError:
            self._say(token, self._t("down"))

    def _cmd_messages(self, token: str) -> None:
        sid = self._store.session_id_for(token)
        if not sid:
            self._say(token, self._t("no_session"))
            return
        try:
            messages = self._oc.session_messages(sid)
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        user_msgs = [
            m
            for m in messages
            if (m.get("info") or {}).get("role") == "user" and (m.get("info") or {}).get("id")
        ]
        user_msgs = user_msgs[-self._cfg.list_limit :]
        if not user_msgs:
            self._say(token, self._t("no_messages"))
            return
        items = [SelectItem(label=_message_label(m), value=(m["info"]["id"])) for m in user_msgs]
        self._offer_selection(
            token, self._t("title_messages"), items, lambda mid: self._offer_revert_fork(token, sid, mid)
        )

    def _offer_revert_fork(self, token: str, session_id: str, message_id: str) -> None:
        items = [
            SelectItem(label=self._t("action_revert"), value="revert"),
            SelectItem(label=self._t("action_fork"), value="fork"),
        ]
        self._offer_selection(
            token,
            self._t("title_action"),
            items,
            lambda action: self._do_revert_fork(token, session_id, message_id, action),
        )

    def _do_revert_fork(self, token: str, session_id: str, message_id: str, action: str) -> None:
        try:
            if action == "revert":
                self._oc.revert(session_id, message_id)
                self._say(token, self._t("reverted"))
            else:
                new_id = self._oc.fork(session_id, message_id)
                self._switch_session(token, new_id)
        except OpenCodeDownError:
            self._say(token, self._t("down"))

    def _handle_model(self, token: str, arg: str) -> None:
        if arg:
            if "/" not in arg:
                self._say(token, self._t("model_format"))
                return
            self._store.set_model(token, arg, now=_now())
            self._say(token, self._t("model_set", model=arg))
            return
        try:
            models = self._oc.list_models()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        if not models:
            current = (self._store.get(token).model if self._store.get(token) else None) or "(default)"
            self._say(token, self._t("model_current", model=current))
            return
        items = [
            SelectItem(label=f"{m['providerID']}/{m['id']}", value=f"{m['providerID']}/{m['id']}")
            for m in models[: self._cfg.list_limit]
            if m.get("providerID") and m.get("id")
        ]
        self._offer_selection(token, self._t("title_models"), items, lambda v: self._set_model(token, v))

    def _set_model(self, token: str, value: str) -> None:
        self._store.set_model(token, value, now=_now())
        self._say(token, self._t("model_set", model=value))

    def _handle_agent(self, token: str, arg: str) -> None:
        if arg:
            self._store.set_agent(token, arg.strip(), now=_now())
            self._say(token, self._t("agent_set", agent=arg.strip()))
            return
        try:
            agents = self._oc.list_agents()
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            return
        visible = [a for a in agents if not a.get("hidden") and a.get("name")]
        if not visible:
            self._say(token, self._t("no_agents"))
            return
        items = [
            SelectItem(label=a["name"], value=a["name"], description=(a.get("description") or "")[:40])
            for a in visible[: self._cfg.list_limit]
        ]
        self._offer_selection(token, self._t("title_agents"), items, lambda v: self._set_agent(token, v))

    def _set_agent(self, token: str, value: str) -> None:
        self._store.set_agent(token, value, now=_now())
        self._say(token, self._t("agent_set", agent=value))

    def _offer_selection(self, token: str, title: str, items: list[SelectItem], on_select) -> None:
        if not items:
            self._say(token, self._t("nothing_to_pick"))
            return
        self._pending.set(token, SelectionPending(title=title, items=items, on_select=on_select))
        self._say(token, format_selection(title, items, hint=self._t("pick_number")))

    def _handle_stop(self, token: str) -> None:
        sid = self._store.session_id_for(token)
        if not sid:
            self._say(token, self._t("no_running_session"))
            return
        try:
            self._oc.abort(sid)
            self._say(token, self._t("aborted"))
        except OpenCodeDownError:
            self._say(token, self._t("down"))

    def _handle_status(self, token: str) -> None:
        healthy = self._oc.health()
        sid = self._store.session_id_for(token)
        state = self._store.get(token)
        model = (state.model if state else None) or self._cfg.opencode_model or "(default)"
        agent = (state.agent if state else None) or "(default)"
        health = self._t("reachable") if healthy else self._t("unreachable")
        self._say(token, self._t("status", health=health, sid=sid or "—", model=model, agent=agent))
        self._status.update(opencode_healthy=healthy)

    # --- prompting ---------------------------------------------------------

    def _start_prompt(self, token: str, text: str, files: tuple[FileRef, ...] = ()) -> None:
        self._start_turn(token, lambda sid: self._prompt_runner(token, sid, text, files))

    def _start_command(self, token: str, name: str) -> None:
        self._start_turn(token, lambda sid: self._oc.run_command(sid, name))

    def _prompt_runner(
        self, token: str, session_id: str, text: str, files: tuple[FileRef, ...] = ()
    ) -> PromptResult:
        prompt_text, extra_parts = self._process_files(text, files)
        state = self._store.get(token)
        model = (state.model if state else None) or self._cfg.opencode_model
        agent = state.agent if state else None
        return self._oc.prompt(
            session_id, prompt_text, model=model, agent=agent, extra_parts=extra_parts or None
        )

    def _process_files(self, text: str, files: tuple[FileRef, ...]) -> tuple[str, list[dict]]:
        """Transcribe audio (STT) into the prompt and inline other files as
        OpenCode file parts (base64 data URLs). Runs in the worker thread."""
        prompt_text = text
        extra_parts: list[dict] = []
        for f in files:
            try:
                if f.is_audio and self._stt is not None:
                    audio = self._talk.download(f.path)
                    transcript = self._stt.transcribe(audio, f.name or "audio.ogg")
                    prompt_text = f"{prompt_text} {transcript}".strip() if prompt_text else transcript
                elif not f.is_audio:
                    data = self._talk.download(f.path)
                    extra_parts.append(_file_part(f, data))
            except (STTError, WebDavError, NextcloudTalkError) as exc:
                log.warning("could not process attachment %s: %s", f.name, exc)
        return prompt_text, extra_parts

    def _start_turn(self, token: str, runner) -> None:
        with self._lock:
            worker = self._busy.get(token)
            if worker is not None and worker.is_alive():
                self._say(token, self._t("busy"))
                return
            t = threading.Thread(
                target=self._run_turn, args=(token, runner), name=f"turn:{token}", daemon=True
            )
            self._busy[token] = t
            t.start()

    def _run_turn(self, token: str, runner) -> None:
        try:
            session_id = self._ensure_session(token)
        except OpenCodeDownError:
            self._say(token, self._t("down"))
            self._status.update(state="opencode_down", opencode_healthy=False)
            return
        except Exception as exc:  # noqa: BLE001 - report any setup failure to the user
            log.exception("session setup failed")
            self._say(token, self._t("error", error=exc))
            return

        self._status.update(state="working")
        msg_id = self._say(token, self._t("working"))
        stream = self._begin_turn(session_id, token, msg_id)

        try:
            result = runner(session_id)
        except OpenCodeDownError:
            self._end_turn(session_id)
            self._say(token, self._t("down"))
            self._status.update(state="opencode_down", opencode_healthy=False)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("prompt failed")
            self._finalize_or_say(token, stream, self._t("error", error=exc))
            self._end_turn(session_id)
            self._status.update(state="polling")
            return

        self._pending.pop(token)  # any unanswered ask is moot once the turn ends
        self._deliver(token, result, stream)
        self._end_turn(session_id)
        self._status.update(state="polling")

    def _ensure_session(self, token: str) -> str:
        sid = self._store.session_id_for(token)
        if sid:
            return sid
        state = self._store.get(token)
        directory = state.directory if state else None
        sid = self._oc.create_session(title=f"Talk {token}", directory=directory)
        self._store.set_session(token, sid, now=_now())
        with self._lock:
            self._session_to_token[sid] = token
        return sid

    def _begin_turn(self, session_id: str, token: str, msg_id: int | None) -> StreamState | None:
        """Register a turn: a tool/thinking announce-set, plus a stream if
        streaming is on and we have a message to edit."""
        stream = None
        with self._lock:
            self._announced[session_id] = set()
            if self._cfg.response_streaming and msg_id is not None:
                stream = StreamState(
                    token, msg_id, self._talk.edit, throttle=self._cfg.stream_throttle_ms / 1000
                )
                self._streams[session_id] = stream
        return stream

    def _end_turn(self, session_id: str) -> None:
        with self._lock:
            self._streams.pop(session_id, None)
            self._announced.pop(session_id, None)

    def _deliver(self, token: str, result: PromptResult, stream: StreamState | None) -> None:
        if result.aborted:
            self._finalize_or_say(token, stream, self._t("aborted"))
            return
        if result.error:
            self._finalize_or_say(token, stream, self._t("error", error=result.error))
            return
        text = result.text or self._t("no_answer")
        if self._should_attach(text) and self._deliver_as_file(token, text):
            self._finalize_or_say(token, stream, self._t("attached_as_file"))
        else:
            self._finalize_or_say(token, stream, text)
        self._maybe_tts(token, result.text)

    def _maybe_tts(self, token: str, text: str) -> None:
        """Synthesise the answer to audio and share it, if /tts is on for this
        conversation and TTS + a share folder are configured."""
        if self._tts is None or not text.strip():
            return
        state = self._store.get(token)
        if not (state and state.tts_enabled and self._cfg.share_webdav_dir):
            return
        try:
            audio = self._tts.synthesize(text[:4000])
            name = f"opencode-tts-{_now()}.mp3"
            remote = self._cfg.share_webdav_dir.rstrip("/") + "/" + name
            self._talk.upload_and_share(token, remote, audio, content_type="audio/mpeg")
        except (TTSError, WebDavError, NextcloudTalkError) as exc:
            log.warning("[%s] TTS failed: %s", token, exc)

    def _finalize_or_say(self, token: str, stream: StreamState | None, text: str) -> None:
        if stream is not None:
            stream.finalize(text)
        else:
            self._say(token, text)

    # --- file attachment ---------------------------------------------------

    def _should_attach(self, text: str) -> bool:
        return len(text) > self._cfg.attachment_threshold or text.count("```") >= 2

    def _deliver_as_file(self, token: str, text: str) -> bool:
        """Upload the answer to Nextcloud via WebDAV and share it into the
        conversation. Returns True on success; False if attachments are not
        configured or the upload/share failed (caller falls back to text)."""
        if not self._cfg.share_webdav_dir:
            return False
        try:
            name = f"opencode-{_now()}.md"
            remote_path = self._cfg.share_webdav_dir.rstrip("/") + "/" + name
            self._talk.upload_and_share(token, remote_path, text.encode("utf-8"), caption="OpenCode-Antwort")
            return True
        except (NextcloudTalkError, WebDavError) as exc:
            log.warning("[%s] file attachment failed, posting text: %s", token, exc)
            return False

    # --- SSE consumer ------------------------------------------------------

    def _sse_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                for payload in self._oc.iter_events():
                    backoff = 1.0
                    if self._stop.is_set():
                        return
                    self._handle_event(payload)
            except OpenCodeDownError:
                if self._stop.is_set():
                    return
                self._status.update(opencode_healthy=False)
                log.warning("event stream down, retrying in %.0fs", backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)

    def _handle_event(self, payload: dict) -> None:
        ev = classify(payload)
        if ev is None:
            return
        if isinstance(ev, TextDelta):
            self._on_text(ev)
        elif isinstance(ev, ToolEvent):
            self._on_tool(ev)
        elif isinstance(ev, ReasoningDelta):
            self._on_reasoning(ev)
        elif isinstance(ev, PermissionEvent):
            self._on_permission(ev.request)
        elif isinstance(ev, QuestionEvent):
            self._on_question(ev.request)
        elif isinstance(ev, SessionError):
            token = self._token_for_session(ev.session_id)
            if token:
                self._say(token, self._t("session_error"))
        elif isinstance(ev, SessionIdle):
            self._on_session_idle(ev.session_id)

    def _on_session_idle(self, session_id: str) -> None:
        # The foreground turn finishes via the blocking prompt return (it has an
        # active announce-set). A mapped session going idle *without* an active
        # turn is a background/detached completion worth a short notice.
        if not self._cfg.track_background_sessions:
            return
        with self._lock:
            is_foreground = session_id in self._announced
        if is_foreground:
            return
        token = self._token_for_session(session_id)
        if token:
            self._say(token, self._t("bg_done"))

    def _on_text(self, ev: TextDelta) -> None:
        with self._lock:
            stream = self._streams.get(ev.session_id)
        if stream is not None:
            stream.update_part(ev.message_id, ev.part_id, ev.text)

    def _on_tool(self, ev: ToolEvent) -> None:
        if self._cfg.hide_tool_messages or not ev.tool:
            return
        if not self._announce_once(ev.session_id, f"tool:{ev.call_id}"):
            return
        token = self._token_for_session(ev.session_id)
        if token:
            emoji = _TOOL_EMOJI.get(ev.tool, "🔧")
            self._say(token, f"{emoji} `{ev.tool}`")  # tool name is not localised

    def _on_reasoning(self, ev: ReasoningDelta) -> None:
        if self._cfg.hide_thinking:
            return
        if not self._announce_once(ev.session_id, "thinking"):
            return  # one thinking notice per turn
        token = self._token_for_session(ev.session_id)
        if token:
            self._say(token, self._t("thinking"))

    def _announce_once(self, session_id: str, key: str) -> bool:
        """Return True the first time ``key`` is seen this turn (per session)."""
        with self._lock:
            announced = self._announced.get(session_id)
            if announced is None or key in announced:
                return False
            announced.add(key)
            return True

    def _on_permission(self, request: dict) -> None:
        ask = PermissionAsk.from_request(request)
        token = self._token_for_session(ask.session_id)
        if token is None:
            log.info("permission ask for unmapped session %s — ignoring", ask.session_id)
            return
        self._pending.set(token, PermissionPending(ask))
        self._say(token, format_prompt(ask))

    def _on_question(self, request: dict) -> None:
        ask = QuestionAsk.from_request(request)
        token = self._token_for_session(ask.session_id)
        if token is None:
            log.info("question for unmapped session %s — ignoring", ask.session_id)
            return
        self._pending.set(token, QuestionPending(ask))
        self._say(token, format_question(ask))

    def _token_for_session(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        with self._lock:
            return self._session_to_token.get(session_id)

    # --- helpers -----------------------------------------------------------

    def _say(self, token: str, text: str) -> int | None:
        """Post a message; return its id (for editing) or None on failure."""
        try:
            return self._talk.send(token, text)
        except NextcloudTalkError as exc:
            log.error("[%s] failed to post message: %s", token, exc)
            return None


def _file_part(f: FileRef, data: bytes) -> dict:
    """Build an OpenCode FilePartInput inlining the file as a base64 data URL."""
    mime = f.mimetype or "application/octet-stream"
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "file", "mime": mime, "filename": f.name or "file", "url": f"data:{mime};base64,{b64}"}


def _parse_task_arg(arg: str) -> tuple[int, int, str] | None:
    """Parse `/task` args into (run_in_seconds, interval_seconds, prompt).

    Forms: "<minutes> <prompt>" (one-shot) or "every <minutes> <prompt>".
    Returns None if the syntax is invalid.
    """
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        return None
    head, rest = parts
    if head.lower() in ("every", "alle"):
        sub = rest.split(maxsplit=1)
        if len(sub) < 2 or not sub[0].isdigit():
            return None
        minutes = int(sub[0])
        return minutes * 60, minutes * 60, sub[1].strip()
    if head.isdigit():
        return int(head) * 60, 0, rest.strip()
    return None


def _message_label(message: dict) -> str:
    """Short label for a user message in the /messages picker."""
    parts = message.get("parts") or []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            text = part["text"].strip().replace("\n", " ")
            return text[:50] + ("…" if len(text) > 50 else "")
    return message.get("info", {}).get("id", "?")


def _now() -> int:
    return int(time.time())
