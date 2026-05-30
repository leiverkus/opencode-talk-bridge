"""Bridge orchestration: glue Nextcloud Talk polling to the OpenCode server.

Threading model (sync throughout, to match ``nextcloud-talk-core``):

  - One **poll thread per watched conversation** runs a Talk long-poll loop.
  - One **SSE thread** consumes ``/global/event`` for the whole server and routes
    ``permission.asked`` events to the bound conversation.
  - Each prompt runs in an **ephemeral worker thread**, because
    ``POST /session/{id}/message`` blocks until the turn finishes — and that turn
    may pause for a permission whose reply arrives on the conversation's poll
    loop. Running the prompt inline would deadlock that handshake.

Shared state (``SessionStore``, ``PendingPermissions``, ``StatusWriter``) is
thread-safe; the small in-memory maps here are guarded by ``self._lock``.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from . import commands
from .allowlist import Allowlist
from .config import Config
from .opencode import OpenCodeClient, OpenCodeDownError, PromptResult
from .permissions import PendingPermissions, format_prompt, interpret_reply
from .sessions import SessionStore
from .status import StatusWriter
from .talk import IncomingMessage, NextcloudTalkError, TalkGateway

log = logging.getLogger(__name__)

_WORKING_NOTICE = "🔧 OpenCode arbeitet …"
_BUSY_NOTICE = "⏳ Ich arbeite noch an der vorherigen Anfrage – bitte warten oder `/stop`."
_DOWN_NOTICE = "⚠️ OpenCode ist nicht erreichbar. Bitte den Server prüfen."


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
        self._pending = PendingPermissions()

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._session_to_token: dict[str, str] = {}
        self._busy: dict[str, threading.Thread] = {}
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

        # A pending permission takes priority: an allowed user's yes/no answers it.
        if self._pending.has(token):
            if self._allow.is_allowed(msg.actor_id, msg.actor_type):
                outcome = interpret_reply(msg.text)
                if outcome is not None:
                    self._answer_permission(token, outcome)
                    return
            # Not a recognised reply: fall through and treat as normal input.

        if not self._allow.is_allowed(msg.actor_id, msg.actor_type):
            log.info("[%s] ignoring message from %s (%s)", token, msg.actor_id, msg.actor_type)
            return

        parsed = commands.parse(msg.text)
        if isinstance(parsed, commands.Command):
            self._handle_command(token, parsed)
        else:
            self._start_prompt(token, parsed.text)

    # --- commands ----------------------------------------------------------

    def _handle_command(self, token: str, cmd: commands.Command) -> None:
        if cmd.name == "help":
            self._say(token, commands.HELP_TEXT)
        elif cmd.name == "new":
            self._store.clear_session(token, now=_now())
            self._say(token, "🆕 Neue OpenCode-Session beim nächsten Prompt.")
        elif cmd.name == "session":
            sid = self._store.session_id_for(token)
            self._say(token, f"Session: `{sid}`" if sid else "Noch keine Session.")
        elif cmd.name == "model":
            self._handle_model(token, cmd.arg)
        elif cmd.name == "stop":
            self._handle_stop(token)
        elif cmd.name == "status":
            self._handle_status(token)

    def _handle_model(self, token: str, arg: str) -> None:
        if not arg:
            state = self._store.get(token)
            current = (state.model if state else None) or self._cfg.opencode_model or "(Server-Default)"
            self._say(token, f"Modell: `{current}`")
            return
        if "/" not in arg:
            self._say(token, "Format: `/model providerID/modelID`")
            return
        self._store.set_model(token, arg, now=_now())
        self._say(token, f"✅ Modell gesetzt: `{arg}`")

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
        self._say(
            token,
            f"📊 OpenCode: {'✅ erreichbar' if healthy else '⚠️ nicht erreichbar'}\n"
            f"Session: `{sid or '—'}`\nModell: `{model}`",
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

        self._say(token, _WORKING_NOTICE)
        self._status.update(state="working")
        state = self._store.get(token)
        model = (state.model if state else None) or self._cfg.opencode_model

        try:
            result = self._oc.prompt(session_id, text, model=model)
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)
            self._status.update(state="opencode_down", opencode_healthy=False)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("prompt failed")
            self._say(token, f"⚠️ Fehler: {exc}")
            return
        finally:
            self._pending.pop(token)  # any unanswered ask is moot once the turn ends
            self._status.update(state="polling")

        self._deliver(token, result)

    def _ensure_session(self, token: str) -> str:
        sid = self._store.session_id_for(token)
        if sid:
            return sid
        sid = self._oc.create_session(title=f"Talk {token}")
        self._store.set_session(token, sid, now=_now())
        with self._lock:
            self._session_to_token[sid] = token
        return sid

    def _deliver(self, token: str, result: PromptResult) -> None:
        if result.aborted:
            self._say(token, "🛑 Abgebrochen.")
            return
        if result.error:
            self._say(token, f"⚠️ {result.error}")
            return
        text = result.text or "(keine Antwort)"
        if self._should_attach(text):
            if self._deliver_as_file(token, text):
                return
        self._say(token, text)

    # --- file attachment ---------------------------------------------------

    def _should_attach(self, text: str) -> bool:
        return len(text) > self._cfg.attachment_threshold or text.count("```") >= 2

    def _deliver_as_file(self, token: str, text: str) -> bool:
        """Write the answer to the Nextcloud share dir and share it. Returns
        True on success; False if attachments are not configured/failed (caller
        falls back to posting text)."""
        if not (self._cfg.share_dir and self._cfg.share_webdav_root):
            return False
        try:
            name = f"opencode-{_now()}.md"
            local = Path(self._cfg.share_dir) / name
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(text, encoding="utf-8")
            webdav_path = self._cfg.share_webdav_root.rstrip("/") + "/" + name
            self._talk.share_file(token, webdav_path, caption="OpenCode-Antwort")
            return True
        except (OSError, NextcloudTalkError) as exc:
            log.warning("[%s] file attachment failed, posting text: %s", token, exc)
            return False

    # --- permission handling ----------------------------------------------

    def _answer_permission(self, token: str, outcome: str) -> None:
        ask = self._pending.pop(token)
        if ask is None:
            return
        try:
            self._oc.reply_permission(ask.request_id, outcome)
            label = {"once": "erlaubt (einmal)", "always": "erlaubt (immer)", "reject": "abgelehnt"}[outcome]
            self._say(token, f"🔐 {label}.")
        except OpenCodeDownError:
            self._say(token, _DOWN_NOTICE)

    # --- SSE consumer ------------------------------------------------------

    def _sse_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                for event in self._oc.iter_events():
                    backoff = 1.0
                    if self._stop.is_set():
                        return
                    self._handle_event(event)
            except OpenCodeDownError:
                if self._stop.is_set():
                    return
                self._status.update(opencode_healthy=False)
                log.warning("event stream down, retrying in %.0fs", backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)

    def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        props = event.get("properties") or {}
        if etype == "permission.asked":
            self._on_permission_asked(props)
        elif etype == "session.error":
            sid = props.get("sessionID")
            token = self._token_for_session(sid)
            if token:
                self._say(token, "⚠️ OpenCode meldet einen Fehler.")

    def _on_permission_asked(self, request: dict) -> None:
        from .opencode import PermissionAsk

        ask = PermissionAsk.from_request(request)
        token = self._token_for_session(ask.session_id)
        if token is None:
            log.info("permission ask for unmapped session %s — ignoring", ask.session_id)
            return
        self._pending.set(token, ask)
        self._say(token, format_prompt(ask))

    def _token_for_session(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        with self._lock:
            return self._session_to_token.get(session_id)

    # --- helpers -----------------------------------------------------------

    def _say(self, token: str, text: str) -> None:
        try:
            self._talk.send(token, text)
        except NextcloudTalkError as exc:
            log.error("[%s] failed to post message: %s", token, exc)


def _now() -> int:
    return int(time.time())
