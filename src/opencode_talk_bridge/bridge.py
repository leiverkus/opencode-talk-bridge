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
from .sessions import SessionStore
from .status import StatusWriter
from .streaming import StreamState
from .talk import IncomingMessage, NextcloudTalkError, TalkGateway, WebDavError

log = logging.getLogger(__name__)

_WORKING_NOTICE = "🔧 OpenCode arbeitet …"
_BUSY_NOTICE = "⏳ Ich arbeite noch an der vorherigen Anfrage – bitte warten oder `/stop`."
_DOWN_NOTICE = "⚠️ OpenCode ist nicht erreichbar. Bitte den Server prüfen."

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
    ) -> None:
        self._cfg = config
        self._talk = gateway
        self._oc = opencode
        self._store = store
        self._status = status
        self._allow = Allowlist(config.allowed_users)
        self._pending = PendingRegistry()

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
        # Closing the OpenCode client breaks the blocking SSE stream.
        self._oc.close()

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
        else:
            self._start_prompt(token, parsed.text)

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
            label = {"once": "erlaubt (einmal)", "always": "erlaubt (immer)", "reject": "abgelehnt"}[outcome]
            self._say(token, f"🔐 {label}.")
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)

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
            self._say(token, f"✅ {answer}")
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
        return True

    # --- commands ----------------------------------------------------------

    def _handle_command(self, token: str, cmd: commands.Command) -> None:
        handlers = {
            "help": lambda: self._say(token, commands.HELP_TEXT),
            "new": lambda: self._cmd_new(token),
            "session": lambda: self._cmd_session(token),
            "sessions": lambda: self._cmd_sessions(token),
            "model": lambda: self._handle_model(token, cmd.arg),
            "agent": lambda: self._handle_agent(token, cmd.arg),
            "stop": lambda: self._handle_stop(token),
            "status": lambda: self._handle_status(token),
        }
        handler = handlers.get(cmd.name)
        if handler:
            handler()

    def _cmd_new(self, token: str) -> None:
        self._store.clear_session(token, now=_now())
        self._say(token, "🆕 Neue OpenCode-Session beim nächsten Prompt.")

    def _cmd_session(self, token: str) -> None:
        sid = self._store.session_id_for(token)
        self._say(token, f"Session: `{sid}`" if sid else "Noch keine Session.")

    def _cmd_sessions(self, token: str) -> None:
        try:
            sessions = self._oc.list_sessions()
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
            return
        sessions = sessions[: self._cfg.list_limit]
        if not sessions:
            self._say(token, "Keine Sessions vorhanden. Schreib einfach einen Prompt.")
            return
        items = [
            SelectItem(
                label=(s.get("title") or s.get("id", "?")), value=s["id"], description=s.get("id", "")[:12]
            )
            for s in sessions
            if s.get("id")
        ]
        self._offer_selection(token, "🗂 Sessions:", items, lambda sid: self._switch_session(token, sid))

    def _switch_session(self, token: str, session_id: str) -> None:
        self._store.set_session(token, session_id, now=_now())
        with self._lock:
            self._session_to_token[session_id] = token
        self._say(token, f"✅ Session gewechselt: `{session_id}`")

    def _handle_model(self, token: str, arg: str) -> None:
        if arg:
            if "/" not in arg:
                self._say(token, "Format: `/model providerID/modelID`")
                return
            self._store.set_model(token, arg, now=_now())
            self._say(token, f"✅ Modell gesetzt: `{arg}`")
            return
        try:
            models = self._oc.list_models()
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
            return
        if not models:
            current = (self._store.get(token).model if self._store.get(token) else None) or "(Server-Default)"
            self._say(token, f"Aktuelles Modell: `{current}`\nSetzen: `/model providerID/modelID`")
            return
        items = [
            SelectItem(label=f"{m['providerID']}/{m['id']}", value=f"{m['providerID']}/{m['id']}")
            for m in models[: self._cfg.list_limit]
            if m.get("providerID") and m.get("id")
        ]
        self._offer_selection(token, "🧠 Modelle:", items, lambda v: self._set_model(token, v))

    def _set_model(self, token: str, value: str) -> None:
        self._store.set_model(token, value, now=_now())
        self._say(token, f"✅ Modell gesetzt: `{value}`")

    def _handle_agent(self, token: str, arg: str) -> None:
        if arg:
            self._store.set_agent(token, arg.strip(), now=_now())
            self._say(token, f"✅ Agent gesetzt: `{arg.strip()}`")
            return
        try:
            agents = self._oc.list_agents()
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
            return
        visible = [a for a in agents if not a.get("hidden") and a.get("name")]
        if not visible:
            self._say(token, "Keine Agenten verfügbar. Setzen: `/agent <name>`")
            return
        items = [
            SelectItem(label=a["name"], value=a["name"], description=(a.get("description") or "")[:40])
            for a in visible[: self._cfg.list_limit]
        ]
        self._offer_selection(token, "🎭 Agenten:", items, lambda v: self._set_agent(token, v))

    def _set_agent(self, token: str, value: str) -> None:
        self._store.set_agent(token, value, now=_now())
        self._say(token, f"✅ Agent gesetzt: `{value}`")

    def _offer_selection(self, token: str, title: str, items: list[SelectItem], on_select) -> None:
        if not items:
            self._say(token, "Nichts zur Auswahl.")
            return
        self._pending.set(token, SelectionPending(title=title, items=items, on_select=on_select))
        self._say(token, format_selection(title, items))

    def _handle_stop(self, token: str) -> None:
        sid = self._store.session_id_for(token)
        if not sid:
            self._say(token, "Keine laufende Session.")
            return
        try:
            self._oc.abort(sid)
            self._say(token, "🛑 Abgebrochen.")
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)

    def _handle_status(self, token: str) -> None:
        healthy = self._oc.health()
        sid = self._store.session_id_for(token)
        state = self._store.get(token)
        model = (state.model if state else None) or self._cfg.opencode_model or "(Server-Default)"
        agent = (state.agent if state else None) or "(Default)"
        self._say(
            token,
            f"📊 OpenCode: {'✅ erreichbar' if healthy else '⚠️ nicht erreichbar'}\n"
            f"Session: `{sid or '—'}`\nModell: `{model}`\nAgent: `{agent}`",
        )
        self._status.update(opencode_healthy=healthy)

    # --- prompting ---------------------------------------------------------

    def _start_prompt(self, token: str, text: str) -> None:
        with self._lock:
            worker = self._busy.get(token)
            if worker is not None and worker.is_alive():
                self._say(token, _BUSY_NOTICE)
                return
            t = threading.Thread(
                target=self._run_prompt, args=(token, text), name=f"prompt:{token}", daemon=True
            )
            self._busy[token] = t
            t.start()

    def _run_prompt(self, token: str, text: str) -> None:
        try:
            session_id = self._ensure_session(token)
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
            self._status.update(state="opencode_down", opencode_healthy=False)
            return
        except Exception as exc:  # noqa: BLE001 - report any setup failure to the user
            log.exception("session setup failed")
            self._say(token, f"⚠️ Fehler: {exc}")
            return

        self._status.update(state="working")
        msg_id = self._say(token, _WORKING_NOTICE)
        stream = self._begin_turn(session_id, token, msg_id)
        state = self._store.get(token)
        model = (state.model if state else None) or self._cfg.opencode_model
        agent = state.agent if state else None

        try:
            result = self._oc.prompt(session_id, text, model=model, agent=agent)
        except OpenCodeDownError:
            self._end_turn(session_id)
            self._say(token, _DOWN_NOTICE)
            self._status.update(state="opencode_down", opencode_healthy=False)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("prompt failed")
            self._finalize_or_say(token, stream, f"⚠️ Fehler: {exc}")
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
        sid = self._oc.create_session(title=f"Talk {token}")
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
            self._finalize_or_say(token, stream, "🛑 Abgebrochen.")
            return
        if result.error:
            self._finalize_or_say(token, stream, f"⚠️ {result.error}")
            return
        text = result.text or "(keine Antwort)"
        if self._should_attach(text) and self._deliver_as_file(token, text):
            self._finalize_or_say(token, stream, "📎 Antwort als Datei angehängt.")
            return
        self._finalize_or_say(token, stream, text)

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
                self._say(token, "⚠️ OpenCode meldet einen Fehler.")
        elif isinstance(ev, SessionIdle):
            pass  # turn completion is driven by the blocking prompt return

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
            self._say(token, f"{emoji} `{ev.tool}`")

    def _on_reasoning(self, ev: ReasoningDelta) -> None:
        if self._cfg.hide_thinking:
            return
        if not self._announce_once(ev.session_id, "thinking"):
            return  # one thinking notice per turn
        token = self._token_for_session(ev.session_id)
        if token:
            self._say(token, "💭 denkt nach …")

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


def _now() -> int:
    return int(time.time())
