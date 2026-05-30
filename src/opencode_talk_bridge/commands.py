"""Parse incoming Talk messages into commands or plain prompts.

Pure functions — no I/O — so the parser is trivially unit-testable. A message
whose first token is a known ``/word`` becomes a :class:`Command`; everything
else is a :class:`Prompt`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Known slash-commands. Keep in sync with the help text and the README.
COMMANDS = (
    "new",
    "session",
    "sessions",
    "model",
    "agent",
    "projects",
    "worktree",
    "messages",
    "commands",
    "skills",
    "mcps",
    "rename",
    "detach",
    "tts",
    "task",
    "tasklist",
    "stop",
    "status",
    "help",
)


@dataclass(frozen=True)
class Command:
    name: str
    arg: str  # remainder of the line after the command, stripped (may be empty)


@dataclass(frozen=True)
class Prompt:
    text: str


def parse(message: str) -> Command | Prompt:
    text = message.strip()
    if not text.startswith("/"):
        return Prompt(text=text)

    first, _, rest = text.partition(" ")
    name = first[1:].lower()
    if name in COMMANDS:
        return Command(name=name, arg=rest.strip())
    # Unknown slash-word: treat as a plain prompt rather than silently dropping.
    return Prompt(text=text)


# The help text is localised in messages.py (key "help"), not here.
