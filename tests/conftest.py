"""Shared pytest fixtures.

Every test runs against mocks — no live Nextcloud or OpenCode calls.
"""

from __future__ import annotations

import pytest

_TALK_ENV = {
    "NC_URL": "https://cloud.example.com",
    "NC_USER": "bot",
    "NC_APP_PASSWORD": "app-pw-123",
}


@pytest.fixture
def talk_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set the Nextcloud-Talk env vars required by nextcloud-talk-core."""
    for key, value in _TALK_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(_TALK_ENV)
