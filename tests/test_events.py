from __future__ import annotations

from opencode_talk_bridge.events import (
    PermissionEvent,
    QuestionEvent,
    ReasoningDelta,
    SessionError,
    SessionIdle,
    TextDelta,
    ToolEvent,
    classify,
)


def _part_event(part):
    return {"type": "message.part.updated", "properties": {"part": part}}


def test_classify_text_delta():
    ev = classify(
        _part_event({"type": "text", "sessionID": "ses_1", "messageID": "msg_1", "id": "p1", "text": "hi"})
    )
    assert ev == TextDelta("ses_1", "msg_1", "p1", "hi")


def test_classify_tool_event():
    ev = classify(
        _part_event(
            {
                "type": "tool",
                "sessionID": "ses_1",
                "tool": "bash",
                "callID": "c1",
                "state": {"status": "running"},
            }
        )
    )
    assert ev == ToolEvent("ses_1", "bash", "running", "c1")


def test_classify_reasoning():
    ev = classify(_part_event({"type": "reasoning", "sessionID": "ses_1", "text": "thinking"}))
    assert ev == ReasoningDelta("ses_1", "thinking")


def test_classify_unknown_part_is_none():
    assert classify(_part_event({"type": "step-start", "sessionID": "ses_1"})) is None


def test_classify_permission_and_question():
    p = classify({"type": "permission.asked", "properties": {"id": "perm_1", "sessionID": "ses_1"}})
    assert isinstance(p, PermissionEvent)
    assert p.request["id"] == "perm_1"
    q = classify({"type": "question.asked", "properties": {"id": "q_1", "sessionID": "ses_1"}})
    assert isinstance(q, QuestionEvent)


def test_classify_session_lifecycle():
    assert classify({"type": "session.idle", "properties": {"sessionID": "ses_1"}}) == SessionIdle("ses_1")
    assert classify({"type": "session.error", "properties": {"sessionID": "ses_1"}}) == SessionError("ses_1")


def test_classify_ignored_event():
    assert classify({"type": "server.connected", "properties": {}}) is None
