from __future__ import annotations

from opencode_talk_bridge.opencode import QuestionAsk
from opencode_talk_bridge.pending import (
    PendingRegistry,
    SelectionPending,
    SelectItem,
    format_question,
    format_selection,
    parse_choice,
)


def test_registry_roundtrip():
    reg = PendingRegistry()
    pending = SelectionPending("Pick", [SelectItem("A", "a")], on_select=lambda v: None)
    assert reg.has("tok") is False
    reg.set("tok", pending)
    assert reg.has("tok") is True
    assert reg.get("tok") is pending
    assert reg.pop("tok") is pending
    assert reg.has("tok") is False


def test_format_selection_numbers_items():
    text = format_selection("Pick:", [SelectItem("Alpha", "a"), SelectItem("Beta", "b", "second")])
    assert "1. Alpha" in text
    assert "2. Beta — second" in text
    assert "Nummer" in text


def test_parse_choice():
    assert parse_choice("1", 3) == 0
    assert parse_choice("3", 3) == 2
    assert parse_choice("4", 3) is None
    assert parse_choice("0", 3) is None
    assert parse_choice("abc", 3) is None
    assert parse_choice(" 2 ", 3) == 1


def _question(options, custom=False):
    return QuestionAsk.from_request(
        {
            "id": "q1",
            "sessionID": "ses_1",
            "questions": [
                {
                    "question": "Which?",
                    "header": "Choice",
                    "options": [{"label": label, "description": ""} for label in options],
                    "custom": custom,
                }
            ],
        }
    )


def test_format_question_with_options():
    text = format_question(_question(["Yes", "No"], custom=True))
    assert "Which?" in text
    assert "1. Yes" in text
    assert "freiem Text" in text  # custom hint
