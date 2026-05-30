"""Runtime configuration for the bridge.

Everything is loaded from the environment (optionally seeded from a `.env`
file). The Nextcloud Talk credentials are delegated to
``nextcloud_talk_core.Settings``; the bridge owns the rest.

The single hard security invariant lives here: an empty allowlist raises, so
the bridge cannot start without one (see README threat model).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from nextcloud_talk_core import Settings


class ConfigError(Exception):
    """Raised when the bridge configuration is missing or invalid."""


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Seed os.environ from a simple `.env` file if present.

    Intentionally minimal (no external dependency): ``KEY=VALUE`` per line,
    ``#`` comments, optional surrounding quotes. Existing environment variables
    are never overwritten, so launchd/shell env always wins over the file.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    """Validated bridge configuration."""

    talk: Settings
    conversations: tuple[str, ...]
    watch_all: bool
    allowed_users: frozenset[str]

    opencode_url: str
    opencode_username: str | None
    opencode_password: str | None
    opencode_directory: str | None
    opencode_model: str | None

    db_path: str
    status_file: str
    # WebDAV folder (relative to the Nextcloud user root) the bridge uploads
    # code/long-output attachments into before sharing them. None disables
    # attachments (long output is posted as text instead).
    share_webdav_dir: str | None
    log_level: str

    # Interaction / streaming
    response_streaming: bool
    stream_throttle_ms: int
    hide_tool_messages: bool
    hide_thinking: bool
    track_background_sessions: bool
    list_limit: int
    bot_locale: str

    # Phase 3: voice
    stt_url: str | None
    stt_key: str | None
    stt_model: str
    stt_language: str | None
    tts_url: str | None
    tts_key: str | None
    tts_model: str
    tts_voice: str
    task_limit: int

    poll_timeout: int = 30
    attachment_threshold: int = field(default=1500)

    @classmethod
    def from_env(cls) -> Config:
        talk = Settings.from_env()

        allowed = frozenset(_split_csv(os.environ.get("ALLOWED_USERS", "")))
        if not allowed:
            raise ConfigError(
                "ALLOWED_USERS is empty. Refusing to start: set it to a "
                "comma-separated list of Talk user IDs allowed to issue commands."
            )

        raw_convos = os.environ.get("TALK_CONVERSATIONS", "").strip()
        watch_all = raw_convos.lower() == "all"
        conversations = tuple(_split_csv(raw_convos)) if not watch_all else ()
        if not watch_all and not conversations:
            raise ConfigError(
                "TALK_CONVERSATIONS is empty. Set it to one or more conversation "
                'tokens, or "all" to watch every conversation.'
            )

        opencode_url = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").strip().rstrip("/")

        return cls(
            talk=talk,
            conversations=conversations,
            watch_all=watch_all,
            allowed_users=allowed,
            opencode_url=opencode_url,
            opencode_username=_or_none(os.environ.get("OPENCODE_USERNAME")),
            opencode_password=_or_none(os.environ.get("OPENCODE_PASSWORD")),
            opencode_directory=_or_none(os.environ.get("OPENCODE_DIRECTORY")),
            opencode_model=_or_none(os.environ.get("OPENCODE_MODEL")),
            db_path=os.environ.get("DB_PATH", "bridge.sqlite3").strip(),
            status_file=os.environ.get("STATUS_FILE", "status.json").strip(),
            share_webdav_dir=_or_none(os.environ.get("SHARE_WEBDAV_DIR")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
            response_streaming=_bool(os.environ.get("RESPONSE_STREAMING"), True),
            stream_throttle_ms=_int(os.environ.get("STREAM_THROTTLE_MS"), 1500),
            hide_tool_messages=_bool(os.environ.get("HIDE_TOOL_MESSAGES"), False),
            hide_thinking=_bool(os.environ.get("HIDE_THINKING"), True),
            track_background_sessions=_bool(os.environ.get("TRACK_BACKGROUND_SESSIONS"), True),
            list_limit=_int(os.environ.get("LIST_LIMIT"), 10),
            bot_locale=os.environ.get("BOT_LOCALE", "de").strip().lower() or "de",
            stt_url=_or_none(os.environ.get("STT_API_URL")),
            stt_key=_or_none(os.environ.get("STT_API_KEY")),
            stt_model=os.environ.get("STT_MODEL", "whisper-large-v3-turbo").strip(),
            stt_language=_or_none(os.environ.get("STT_LANGUAGE")),
            tts_url=_or_none(os.environ.get("TTS_API_URL")),
            tts_key=_or_none(os.environ.get("TTS_API_KEY")),
            tts_model=os.environ.get("TTS_MODEL", "gpt-4o-mini-tts").strip(),
            tts_voice=os.environ.get("TTS_VOICE", "alloy").strip(),
            task_limit=_int(os.environ.get("TASK_LIMIT"), 10),
        )


def _or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default
