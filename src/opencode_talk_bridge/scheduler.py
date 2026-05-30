"""Scheduled tasks: run a prompt in a conversation later or on an interval.

A SQLite-backed task store plus a daemon thread that fires due tasks via a
runner callback (the bridge wires this to start a normal prompt turn). One-shot
tasks are deleted after firing; recurring tasks are rescheduled by their
interval. Times are Unix timestamps so the schedule survives restarts.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    run_at     INTEGER NOT NULL,
    interval_s INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Task:
    id: int
    token: str
    prompt: str
    run_at: int
    interval_s: int


class TaskStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add(self, token: str, prompt: str, run_at: int, interval_s: int = 0, *, now: int = 0) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO scheduled_tasks (token, prompt, run_at, interval_s, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (token, prompt, run_at, interval_s, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list(self, token: str) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE token = ? ORDER BY run_at", (token,)
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM scheduled_tasks").fetchone()[0])

    def delete(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            self._conn.commit()

    def due(self, now: int) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE run_at <= ? ORDER BY run_at", (now,)
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def reschedule(self, task_id: int, new_run_at: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE scheduled_tasks SET run_at = ? WHERE id = ?", (new_run_at, task_id))
            self._conn.commit()


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        token=row["token"],
        prompt=row["prompt"],
        run_at=row["run_at"],
        interval_s=row["interval_s"],
    )


class Scheduler:
    """Polls the task store and fires due tasks via ``runner(token, prompt)``."""

    def __init__(
        self,
        store: TaskStore,
        runner: Callable[[str, str], None],
        *,
        tick: float = 30.0,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._tick = tick
        self._clock = clock or (lambda: int(time.time()))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_due()
            self._stop.wait(self._tick)

    def run_due(self) -> None:
        """Fire all due tasks once (also usable directly in tests)."""
        now = self._clock()
        for task in self._store.due(now):
            try:
                self._runner(task.token, task.prompt)
            except Exception:  # noqa: BLE001 - a bad task must not kill the loop
                log.exception("scheduled task %s failed", task.id)
            if task.interval_s > 0:
                self._store.reschedule(task.id, now + task.interval_s)
            else:
                self._store.delete(task.id)
