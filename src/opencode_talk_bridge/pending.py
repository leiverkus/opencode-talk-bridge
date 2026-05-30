"""Unified pending-interaction registry.

Talk has no inline buttons, so every interactive flow (permission, agent
question, list picker) is driven by the *next reply* in the conversation. At
most one interaction is pending per conversation; OpenCode serialises these
within a session. The bridge consults the pending interaction before normal
message handling (see ``bridge._handle_message``):

  - **permission** — answered by ``ja``/``immer``/``nein`` (``interpret_reply``).
  - **question** — an agent question; a numbered option or free text answers it.
  - **selection** — a numbered list; a bare integer runs the stored callback.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .opencode import PermissionAsk, QuestionAsk


@dataclass(frozen=True)
class SelectItem:
    label: str
    value: str
    description: str = ""


@dataclass
class PermissionPending:
    ask: PermissionAsk
    kind: str = field(default="permission", init=False)


@dataclass
class QuestionPending:
    ask: QuestionAsk
    kind: str = field(default="question", init=False)


@dataclass
class SelectionPending:
    title: str
    items: list[SelectItem]
    on_select: Callable[[str], None]  # receives the chosen item's value
    kind: str = field(default="selection", init=False)


Pending = PermissionPending | QuestionPending | SelectionPending


class PendingRegistry:
    """Thread-safe one-pending-interaction-per-conversation store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_token: dict[str, Pending] = {}

    def set(self, token: str, pending: Pending) -> None:
        with self._lock:
            self._by_token[token] = pending

    def get(self, token: str) -> Pending | None:
        with self._lock:
            return self._by_token.get(token)

    def pop(self, token: str) -> Pending | None:
        with self._lock:
            return self._by_token.pop(token, None)

    def has(self, token: str) -> bool:
        with self._lock:
            return token in self._by_token


def format_selection(title: str, items: list[SelectItem]) -> str:
    """Render a numbered picker. Reply with the number to choose."""
    lines = [title]
    for i, item in enumerate(items, 1):
        line = f"{i}. {item.label}"
        if item.description:
            line += f" — {item.description}"
        lines.append(line)
    lines.append("_Antworte mit der Nummer._")
    return "\n".join(lines)


def parse_choice(text: str, count: int) -> int | None:
    """Parse a bare 1..count integer reply into a 0-based index, else None."""
    token = text.strip()
    if not token.isdigit():
        return None
    n = int(token)
    return n - 1 if 1 <= n <= count else None


def format_question(ask: QuestionAsk) -> str:
    """Render an agent question with its options as a numbered picker."""
    lines: list[str] = []
    if ask.header:
        lines.append(f"❓ *{ask.header}*")
    if ask.question:
        lines.append(ask.question)
    for i, opt in enumerate(ask.options, 1):
        line = f"{i}. {opt.label}"
        if opt.description:
            line += f" — {opt.description}"
        lines.append(line)
    if ask.options:
        hint = "Antworte mit der Nummer" + (" oder mit freiem Text." if ask.custom else ".")
    else:
        hint = "Antworte frei."
    lines.append(f"_{hint}_")
    return "\n".join(lines)
