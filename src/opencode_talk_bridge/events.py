"""Classify OpenCode SSE event payloads into typed bridge events.

Keeps the parsing of OpenCode's large ``GlobalEvent`` union out of the bridge:
``classify`` turns a raw payload (``{"type", "properties"}``) into one of a few
simple dataclasses the bridge acts on, or ``None`` for events we ignore. This is
pure and unit-testable; the bridge owns the side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TextDelta:
    session_id: str
    message_id: str
    part_id: str
    text: str


@dataclass(frozen=True)
class ToolEvent:
    session_id: str
    tool: str
    status: str
    call_id: str


@dataclass(frozen=True)
class ReasoningDelta:
    session_id: str
    text: str


@dataclass(frozen=True)
class PermissionEvent:
    request: dict[str, Any]


@dataclass(frozen=True)
class QuestionEvent:
    request: dict[str, Any]


@dataclass(frozen=True)
class SessionIdle:
    session_id: str


@dataclass(frozen=True)
class SessionError:
    session_id: str


Event = TextDelta | ToolEvent | ReasoningDelta | PermissionEvent | QuestionEvent | SessionIdle | SessionError


def classify(payload: dict[str, Any]) -> Event | None:
    etype = payload.get("type")
    props = payload.get("properties") or {}

    if etype == "message.part.updated":
        part = props.get("part") or {}
        ptype = part.get("type")
        sid = part.get("sessionID", "")
        if ptype == "text":
            return TextDelta(sid, part.get("messageID", ""), part.get("id", ""), part.get("text", ""))
        if ptype == "tool":
            state = part.get("state") or {}
            return ToolEvent(sid, part.get("tool", ""), state.get("status", ""), part.get("callID", ""))
        if ptype == "reasoning":
            return ReasoningDelta(sid, part.get("text", ""))
        return None

    if etype == "permission.asked":
        return PermissionEvent(props)
    if etype == "question.asked":
        return QuestionEvent(props)
    if etype == "session.idle":
        return SessionIdle(props.get("sessionID", ""))
    if etype == "session.error":
        return SessionError(props.get("sessionID", ""))
    return None
