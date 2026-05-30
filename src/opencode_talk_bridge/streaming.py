"""Live response streaming via Talk message editing.

OpenCode emits ``message.part.updated`` events whose ``TextPart.text`` is the
*cumulative* text of that part. The SSE thread feeds those into a ``StreamState``
keyed by OpenCode ``sessionID``; the state edits a single Talk message at most
once per ``throttle`` seconds (each edit is a full REST call, so we throttle
harder than Telegram would). ``finalize`` forces a last edit with the
authoritative text once the blocking prompt returns.

A monotonic clock is injected so throttling is deterministic in tests.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

# Talk rejects empty edits and has a max length; keep a safety cap.
_MAX_LEN = 30000


class StreamState:
    def __init__(
        self,
        token: str,
        message_id: int,
        editor: Callable[[str, int, str], None],
        *,
        throttle: float = 1.5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.token = token
        self.message_id = message_id
        self._edit = editor
        self._throttle = throttle
        self._clock = clock or _monotonic
        self._lock = threading.Lock()
        # Cumulative text per (messageID, partID), joined in insertion order.
        self._parts: dict[tuple[str, str], str] = {}
        self._order: list[tuple[str, str]] = []
        self._last_edit = float("-inf")
        self._last_rendered = ""

    def update_part(self, message_id: str, part_id: str, text: str) -> None:
        """Record the latest cumulative text of a text part, then maybe edit."""
        key = (message_id, part_id)
        with self._lock:
            if key not in self._parts:
                self._order.append(key)
            self._parts[key] = text
            rendered = self._render()
            now = self._clock()
            if rendered and rendered != self._last_rendered and (now - self._last_edit) >= self._throttle:
                self._flush(rendered, now)

    def finalize(self, text: str | None = None) -> None:
        """Force a final edit. If ``text`` is given it replaces the buffer."""
        with self._lock:
            rendered = text if text is not None else self._render()
            if rendered and rendered != self._last_rendered:
                self._flush(rendered, self._clock())

    def _render(self) -> str:
        return "\n".join(self._parts[k] for k in self._order if self._parts[k]).strip()[:_MAX_LEN]

    def _flush(self, rendered: str, now: float) -> None:
        try:
            self._edit(self.token, self.message_id, rendered)
            self._last_rendered = rendered
            self._last_edit = now
        except Exception:  # noqa: BLE001 - a failed edit must not kill the SSE loop
            pass


def _monotonic() -> float:
    import time

    return time.monotonic()
