from __future__ import annotations

import pytest

from opencode_talk_bridge.commands import Command, Prompt, parse


@pytest.mark.parametrize(
    "text,name,arg",
    [
        ("/new", "new", ""),
        ("/status", "status", ""),
        ("/model anthropic/claude", "model", "anthropic/claude"),
        ("  /stop  ", "stop", ""),
        ("/HELP", "help", ""),
        ("/session 123", "session", "123"),
    ],
)
def test_parse_commands(text, name, arg):
    result = parse(text)
    assert isinstance(result, Command)
    assert result.name == name
    assert result.arg == arg


@pytest.mark.parametrize(
    "text",
    [
        "hello world",
        "fix the bug in foo.py",
        "/unknown command",  # unknown slash-word -> treated as prompt
        "  please refactor  ",
    ],
)
def test_parse_prompts(text):
    result = parse(text)
    assert isinstance(result, Prompt)
    assert result.text == text.strip()


def test_unknown_slash_kept_verbatim():
    assert parse("/deploy now").text == "/deploy now"
