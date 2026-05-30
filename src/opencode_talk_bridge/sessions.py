"""SQLite-backed mapping of Talk conversations to OpenCode sessions.

One row per watched conversation. Persists across bridge restarts so that
``last_known_message_id`` survives (no replay of chat history) and a
conversation stays bound to its OpenCode session and chosen model.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    token                 TEXT PRIMARY KEY,
    opencode_session_id   TEXT,
    model                 TEXT,
    agent                 TEXT,
    tts_enabled           INTEGER NOT NULL DEFAULT 0,
    last_known_message_id INTEGER NOT NULL DEFAULT 0,
    updated_at            INTEGER NOT NULL DEFAULT 0
);
"""

# Columns added after 0.1.x; applied idempotently for existing databases.
_MIGRATIONS = (
    "ALTER TABLE conversations ADD COLUMN agent TEXT",
    "ALTER TABLE conversations ADD COLUMN tts_enabled INTEGER NOT NULL DEFAULT 0",
)


@dataclass
class ConversationState:
    token: str
    opencode_session_id: str | None
    model: str | None
    last_known_message_id: int
    agent: str | None = None
    tts_enabled: bool = False


class SessionStore:
    """Thread-safe SQLite store. A single connection guarded by a lock."""

    def __init__(self, db_path: str) -> None:
        # check_same_thread=False: the SSE thread and poll loop may both touch it,
        # serialised by self._lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            for migration in _MIGRATIONS:
                try:
                    self._conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # column already exists
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SessionStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- reads -------------------------------------------------------------

    def get(self, token: str) -> ConversationState | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE token = ?", (token,)).fetchone()
        return _row_to_state(row) if row else None

    def get_or_create(self, token: str) -> ConversationState:
        existing = self.get(token)
        if existing is not None:
            return existing
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO conversations (token) VALUES (?)", (token,))
            self._conn.commit()
        return ConversationState(token=token, opencode_session_id=None, model=None, last_known_message_id=0)

    def session_id_for(self, token: str) -> str | None:
        state = self.get(token)
        return state.opencode_session_id if state else None

    # --- writes ------------------------------------------------------------

    def set_session(self, token: str, session_id: str | None, *, now: int = 0) -> None:
        self._upsert(token, "opencode_session_id", session_id, now)

    def set_model(self, token: str, model: str | None, *, now: int = 0) -> None:
        self._upsert(token, "model", model, now)

    def set_agent(self, token: str, agent: str | None, *, now: int = 0) -> None:
        self._upsert(token, "agent", agent, now)

    def set_tts(self, token: str, enabled: bool, *, now: int = 0) -> None:
        self._upsert(token, "tts_enabled", 1 if enabled else 0, now)

    def update_last_message_id(self, token: str, message_id: int, *, now: int = 0) -> None:
        self._upsert(token, "last_known_message_id", message_id, now)

    def clear_session(self, token: str, *, now: int = 0) -> None:
        """Forget the OpenCode session binding (e.g. on /new) but keep last id."""
        self.set_session(token, None, now=now)

    def _upsert(self, token: str, column: str, value: object, now: int) -> None:
        # column is from a fixed internal set — never user input.
        with self._lock:
            self._conn.execute(
                f"""INSERT INTO conversations (token, {column}, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(token) DO UPDATE SET {column} = excluded.{column},
                                                     updated_at = excluded.updated_at""",
                (token, value, now),
            )
            self._conn.commit()


def _row_to_state(row: sqlite3.Row) -> ConversationState:
    keys = row.keys()
    return ConversationState(
        token=row["token"],
        opencode_session_id=row["opencode_session_id"],
        model=row["model"],
        last_known_message_id=row["last_known_message_id"],
        agent=row["agent"] if "agent" in keys else None,
        tts_enabled=bool(row["tts_enabled"]) if "tts_enabled" in keys else False,
    )
