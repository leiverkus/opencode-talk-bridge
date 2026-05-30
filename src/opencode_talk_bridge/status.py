"""Atomic JSON status file — the interface for the Swift menubar app.

The menubar app polls this file; it must always be valid JSON, so writes go to
a temp file and are atomically renamed into place. The schema is a stable
contract documented in the README.

State machine::

    starting -> polling <-> working
                  |  \\-> opencode_down
                  \\-> error
                  -> stopped   (clean shutdown)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any

# Allowed top-level states (documented in the README contract).
STATES = ("starting", "polling", "working", "opencode_down", "error", "stopped")


class StatusWriter:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "state": "starting",
            "since": 0,
            "opencode_healthy": False,
            "conversations": [],
            "last_error": None,
            "version": _version(),
        }

    def update(
        self,
        *,
        state: str | None = None,
        since: int | None = None,
        opencode_healthy: bool | None = None,
        conversations: list[str] | None = None,
        last_error: str | None = ...,  # sentinel: ... means "leave unchanged"
    ) -> None:
        with self._lock:
            if state is not None:
                if state not in STATES:
                    raise ValueError(f"unknown state {state!r}")
                self._state["state"] = state
            if since is not None:
                self._state["since"] = since
            if opencode_healthy is not None:
                self._state["opencode_healthy"] = opencode_healthy
            if conversations is not None:
                self._state["conversations"] = list(conversations)
            if last_error is not ...:
                self._state["last_error"] = last_error
            self._flush()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _flush(self) -> None:
        data = json.dumps(self._state, indent=2)
        directory = os.path.dirname(os.path.abspath(self._path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".status-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, self._path)  # atomic on POSIX
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _version() -> str:
    from . import __version__

    return __version__
