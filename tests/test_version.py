from __future__ import annotations

from importlib.metadata import version

import opencode_talk_bridge


def test_version_resolves_from_metadata():
    # __version__ is derived from the installed distribution metadata
    # (single source of truth = pyproject.toml), not a hardcoded literal.
    assert opencode_talk_bridge.__version__ == version("opencode-talk-bridge")
    assert opencode_talk_bridge.__version__ != "0.0.0+unknown"  # not the fallback
