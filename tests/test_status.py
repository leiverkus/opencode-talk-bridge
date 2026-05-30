from __future__ import annotations

import json

import pytest

from opencode_talk_bridge.status import StatusWriter


def test_initial_write_and_update(tmp_path):
    path = tmp_path / "status.json"
    sw = StatusWriter(str(path))
    sw.update(state="polling", since=123, conversations=["tok"], opencode_healthy=True)
    data = json.loads(path.read_text())
    assert data["state"] == "polling"
    assert data["since"] == 123
    assert data["conversations"] == ["tok"]
    assert data["opencode_healthy"] is True
    assert "version" in data


def test_unknown_state_rejected(tmp_path):
    sw = StatusWriter(str(tmp_path / "s.json"))
    with pytest.raises(ValueError):
        sw.update(state="bogus")


def test_last_error_sentinel_preserves_value(tmp_path):
    path = tmp_path / "s.json"
    sw = StatusWriter(str(path))
    sw.update(state="error", last_error="boom")
    sw.update(state="polling")  # not passing last_error keeps it
    assert json.loads(path.read_text())["last_error"] == "boom"
    sw.update(last_error=None)  # explicit clear
    assert json.loads(path.read_text())["last_error"] is None


def test_atomic_write_leaves_no_temp_files(tmp_path):
    sw = StatusWriter(str(tmp_path / "s.json"))
    sw.update(state="polling")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".status-")]
    assert leftovers == []
