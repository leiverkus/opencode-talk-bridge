"""Map OpenCode permission requests to Talk yes/no prompts and back.

When OpenCode wants to run something dangerous (shell, file write) it emits a
``permission.asked`` event and blocks. The bridge posts a concise prompt into
the bound conversation; the next reply from an allowlisted user is interpreted
as the answer and sent to ``POST /permission/{id}/reply``.

Nothing from the tool payload beyond the permission kind and the suggested
patterns is echoed, and even those are length-capped, so command arguments that
might contain secrets are never posted verbatim.
"""

from __future__ import annotations

import threading

from .opencode import PermissionAsk

# Reply-word -> OpenCode outcome. Lowercased exact-token match.
_ALLOW_ONCE = {"ja", "yes", "y", "j", "ok", "allow", "erlauben"}
_ALLOW_ALWAYS = {"immer", "always", "a"}
_REJECT = {"nein", "no", "n", "deny", "reject", "ablehnen", "stop"}

_MAX_PATTERN_LEN = 80


def interpret_reply(text: str) -> str | None:
    """Return "once"/"always"/"reject", or None if the text isn't an answer."""
    token = text.strip().lower()
    if token in _ALLOW_ALWAYS:
        return "always"
    if token in _ALLOW_ONCE:
        return "once"
    if token in _REJECT:
        return "reject"
    return None


def format_prompt(ask: PermissionAsk) -> str:
    """Build a concise, secret-safe Talk prompt for a permission request."""
    kind = ask.permission or "eine Aktion"
    detail = ""
    if ask.patterns:
        pattern = ask.patterns[0]
        if len(pattern) > _MAX_PATTERN_LEN:
            pattern = pattern[:_MAX_PATTERN_LEN] + "…"
        detail = f" (`{pattern}`)"
    return (
        f"🔐 OpenCode möchte *{kind}*{detail} ausführen.\n"
        "Antworte `ja` (einmal), `immer` (für diese Session) oder `nein`."
    )


class PendingPermissions:
    """Thread-safe registry of the permission awaiting a reply per conversation.

    Only one pending permission per conversation is tracked; OpenCode serialises
    permission asks within a session, so a newer ask replaces an older one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_token: dict[str, PermissionAsk] = {}

    def set(self, token: str, ask: PermissionAsk) -> None:
        with self._lock:
            self._by_token[token] = ask

    def get(self, token: str) -> PermissionAsk | None:
        with self._lock:
            return self._by_token.get(token)

    def pop(self, token: str) -> PermissionAsk | None:
        with self._lock:
            return self._by_token.pop(token, None)

    def has(self, token: str) -> bool:
        with self._lock:
            return token in self._by_token
