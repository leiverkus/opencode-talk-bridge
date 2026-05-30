"""HTTP + SSE client for a local ``opencode serve`` instance.

Verified against the OpenAPI of OpenCode 1.15.11 (``GET /doc``). Routes are
session-level (not project-scoped) and the permission flow is global:

  - ``GET  /global/health``                     -> {healthy, version}
  - ``GET  /global/event``                       -> SSE stream of GlobalEvent
  - ``POST /session``                            -> create a Session
  - ``GET  /session``                            -> list sessions
  - ``POST /session/{id}/message``               -> blocks; returns {info, parts}
  - ``POST /session/{id}/abort``                 -> abort the running turn
  - ``GET  /permission``                         -> list pending permissions
  - ``POST /permission/{requestID}/reply``       -> {reply: once|always|reject}

The prompt endpoint (``POST /session/{id}/message``) is synchronous: it returns
the assembled assistant message when the turn finishes. While it blocks, the
agent may ask for permission — those asks arrive on the SSE stream, so the
bridge runs the prompt in a worker thread and the SSE reader in another.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

# Permission reply outcomes accepted by POST /permission/{id}/reply.
PERMISSION_REPLIES = ("once", "always", "reject")


class OpenCodeError(Exception):
    """Base error for OpenCode HTTP interactions."""


class OpenCodeDownError(OpenCodeError):
    """The OpenCode server is unreachable (transport error / failed health)."""


@dataclass(frozen=True)
class PermissionAsk:
    """A pending permission request surfaced by the SSE stream."""

    request_id: str
    session_id: str
    permission: str
    patterns: tuple[str, ...]
    tool: dict[str, Any]

    @classmethod
    def from_request(cls, raw: dict[str, Any]) -> PermissionAsk:
        return cls(
            request_id=raw["id"],
            session_id=raw.get("sessionID", ""),
            permission=raw.get("permission", ""),
            patterns=tuple(raw.get("patterns") or ()),
            tool=raw.get("tool") or {},
        )


@dataclass(frozen=True)
class QuestionOption:
    label: str  # also the value sent back in the answer
    description: str = ""


@dataclass(frozen=True)
class QuestionAsk:
    """A pending agent question surfaced by the SSE stream.

    A question carries one or more sub-questions, each with options and an
    optional free-text ("custom") answer. The bridge handles the common case:
    a single question, rendered as a numbered picker (plus free text if custom).
    The selected option's ``label`` is what gets sent back as the answer.
    """

    request_id: str
    session_id: str
    question: str
    header: str
    options: tuple[QuestionOption, ...]
    custom: bool

    @classmethod
    def from_request(cls, raw: dict[str, Any]) -> QuestionAsk:
        questions = raw.get("questions") or [{}]
        first = questions[0] if questions else {}
        options = tuple(
            QuestionOption(label=o.get("label", ""), description=o.get("description", ""))
            for o in (first.get("options") or [])
            if isinstance(o, dict)
        )
        return cls(
            request_id=raw["id"],
            session_id=raw.get("sessionID", ""),
            question=first.get("question", ""),
            header=first.get("header", ""),
            options=options,
            custom=bool(first.get("custom")),
        )


@dataclass(frozen=True)
class PromptResult:
    """The outcome of a blocking prompt: assistant text + any errors."""

    text: str
    aborted: bool
    error: str | None


class OpenCodeClient:
    """Thin sync wrapper around the OpenCode server HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        directory: str | None = None,
        default_model: str | None = None,
        timeout: float = 30.0,
        prompt_timeout: float = 600.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._directory = directory
        self._default_model = default_model
        self._prompt_timeout = prompt_timeout
        auth = httpx.BasicAuth(username, password) if username else None
        self._client = httpx.Client(base_url=self._base, auth=auth, timeout=timeout)

    def __enter__(self) -> OpenCodeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # --- health ------------------------------------------------------------

    def health(self) -> bool:
        """Return True iff the server reports healthy. Never raises."""
        try:
            resp = self._client.get("/global/health", timeout=5.0)
            resp.raise_for_status()
            return bool(resp.json().get("healthy"))
        except (httpx.HTTPError, ValueError):
            return False

    # --- sessions ----------------------------------------------------------

    def create_session(self, title: str | None = None) -> str:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        data = self._post("/session", body)
        session_id = data.get("id")
        if not session_id:
            raise OpenCodeError(f"session create returned no id: {data!r}")
        return session_id

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._get("/session")

    def abort(self, session_id: str) -> bool:
        return bool(self._post(f"/session/{session_id}/abort", {}))

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        model: str | None = None,
        agent: str | None = None,
        extra_parts: list[dict[str, Any]] | None = None,
    ) -> PromptResult:
        """Send a prompt and block until the assistant turn completes.

        ``model`` overrides the default ("providerID/modelID"); ``agent`` selects
        an agent (e.g. "plan"/"build"); ``extra_parts`` appends file parts.
        """
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if extra_parts:
            parts.extend(extra_parts)
        body: dict[str, Any] = {"parts": parts}
        model_ref = _parse_model(model or self._default_model)
        if model_ref is not None:
            body["model"] = model_ref
        if agent:
            body["agent"] = agent
        data = self._post(
            f"/session/{session_id}/message",
            body,
            timeout=self._prompt_timeout,
        )
        return _prompt_result(data)

    def rename_session(self, session_id: str, title: str) -> None:
        self._patch(f"/session/{session_id}", {"title": title})

    def revert(self, session_id: str, message_id: str, part_id: str | None = None) -> None:
        body: dict[str, Any] = {"messageID": message_id}
        if part_id:
            body["partID"] = part_id
        self._post(f"/session/{session_id}/revert", body)

    def unrevert(self, session_id: str) -> None:
        self._post(f"/session/{session_id}/unrevert", {})

    def fork(self, session_id: str, message_id: str) -> str:
        data = self._post(f"/session/{session_id}/fork", {"messageID": message_id})
        new_id = data.get("id") if isinstance(data, dict) else None
        if not new_id:
            raise OpenCodeError(f"fork returned no id: {data!r}")
        return new_id

    def session_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._get(f"/session/{session_id}/message") or []

    # --- projects / worktrees ---------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        return self._get("/project") or []

    def current_project(self) -> dict[str, Any] | None:
        return self._get("/project/current")

    def list_worktrees(self) -> list[str]:
        return self._get("/experimental/worktree") or []

    # --- models / agents / commands / mcp ---------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        return self._get("/api/model") or []

    def list_agents(self) -> list[dict[str, Any]]:
        return self._get("/agent") or []

    def list_commands(self) -> list[dict[str, Any]]:
        return self._get("/command") or []

    def run_command(self, session_id: str, command: str, arguments: str = "") -> PromptResult:
        body: dict[str, Any] = {"command": command}
        if arguments:
            body["arguments"] = arguments
        data = self._post(f"/session/{session_id}/command", body, timeout=self._prompt_timeout)
        return _prompt_result(data)

    def list_mcps(self) -> dict[str, Any]:
        return self._get("/mcp") or {}

    def toggle_mcp(self, name: str, enable: bool) -> bool:
        action = "connect" if enable else "disconnect"
        return bool(self._post(f"/mcp/{name}/{action}", {}))

    # --- permissions -------------------------------------------------------

    def list_permissions(self) -> list[PermissionAsk]:
        return [PermissionAsk.from_request(p) for p in self._get("/permission")]

    def reply_permission(self, request_id: str, reply: str, message: str | None = None) -> bool:
        if reply not in PERMISSION_REPLIES:
            raise ValueError(f"reply must be one of {PERMISSION_REPLIES}, got {reply!r}")
        body: dict[str, Any] = {"reply": reply}
        if message:
            body["message"] = message
        return bool(self._post(f"/permission/{request_id}/reply", body))

    # --- questions ---------------------------------------------------------

    def reply_question(self, request_id: str, answer: str) -> bool:
        """Answer a single-question agent prompt. ``answer`` is the chosen
        option label (or free text when the question allows custom input)."""
        return bool(self._post(f"/question/{request_id}/reply", {"answers": [[answer]]}))

    def reject_question(self, request_id: str) -> bool:
        return bool(self._post(f"/question/{request_id}/reject", {}))

    # --- events (SSE) ------------------------------------------------------

    def iter_events(self) -> Iterator[dict[str, Any]]:
        """Yield decoded SSE event payloads from ``GET /global/event``.

        Each yielded dict is the GlobalEvent ``payload`` object, i.e. has
        ``{"type": <event-type>, "properties": {...}}``. Raises
        OpenCodeDownError on transport failure so the caller can reconnect.
        """
        try:
            with self._client.stream("GET", "/global/event", timeout=None) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    payload = event.get("payload") if isinstance(event, dict) else None
                    if isinstance(payload, dict) and "type" in payload:
                        yield payload
        except httpx.HTTPError as exc:
            raise OpenCodeDownError(f"event stream failed: {exc}") from exc

    # --- internal ----------------------------------------------------------

    def _get(self, path: str) -> Any:
        try:
            resp = self._client.get(path, params=self._dir_params())
        except httpx.TransportError as exc:
            raise OpenCodeDownError(f"GET {path} failed: {exc}") from exc
        return self._unwrap(resp, path)

    def _post(self, path: str, body: dict[str, Any], *, timeout: float | None = None) -> Any:
        try:
            resp = self._client.post(
                path,
                json=body,
                params=self._dir_params(),
                timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else timeout,
            )
        except httpx.TransportError as exc:
            raise OpenCodeDownError(f"POST {path} failed: {exc}") from exc
        return self._unwrap(resp, path)

    def _patch(self, path: str, body: dict[str, Any]) -> Any:
        try:
            resp = self._client.patch(path, json=body, params=self._dir_params())
        except httpx.TransportError as exc:
            raise OpenCodeDownError(f"PATCH {path} failed: {exc}") from exc
        return self._unwrap(resp, path)

    def _dir_params(self) -> dict[str, str] | None:
        return {"directory": self._directory} if self._directory else None

    @staticmethod
    def _unwrap(resp: httpx.Response, path: str) -> Any:
        if resp.status_code >= 400:
            raise OpenCodeError(f"{path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text


def _parse_model(model: str | None) -> dict[str, str] | None:
    """Turn "providerID/modelID" into the API's model object."""
    if not model:
        return None
    provider, _, model_id = model.partition("/")
    if not provider or not model_id:
        raise ValueError(f'model must be "providerID/modelID", got {model!r}')
    return {"providerID": provider, "modelID": model_id}


def _prompt_result(data: Any) -> PromptResult:
    """Extract assistant text + error from a {info, parts} response."""
    if not isinstance(data, dict):
        return PromptResult(text="", aborted=False, error="unexpected response")
    info = data.get("info") or {}
    parts = data.get("parts") or []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
    text = "\n".join(t for t in texts if t).strip()

    error = info.get("error")
    aborted = False
    err_msg: str | None = None
    if isinstance(error, dict):
        name = error.get("name", "")
        aborted = name == "MessageAbortedError"
        err_msg = None if aborted else (error.get("data", {}).get("message") or name or "error")
    return PromptResult(text=text, aborted=aborted, error=err_msg)


def wait_for_healthy(client: OpenCodeClient, attempts: int = 1, delay: float = 1.0) -> bool:
    """Poll health up to ``attempts`` times. Returns True on first success."""
    for i in range(attempts):
        if client.health():
            return True
        if i < attempts - 1:
            time.sleep(delay)
    return False
