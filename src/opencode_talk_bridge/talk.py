"""Nextcloud Talk gateway used by the bridge.

Two concerns, two underlying clients from ``nextcloud-talk-core`` (never
reimplemented here):

  - **Sending / sharing / listing**: the high-level ``TalkClient``.
  - **Polling**: the low-level ``OCSClient``, called directly so we can read the
    raw ``actorId`` / ``actorType`` per message. The core ``Message`` model
    collapses the author to a display name (``actorDisplayName``), which is unfit
    for the security allowlist — so polling parses the raw OCS dicts itself,
    mirroring core's ``wait_for_messages`` request exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nextcloud_talk_core import (
    Conversation,
    NextcloudTalkError,
    OCSClient,
    Settings,
    TalkClient,
)

from .webdav import WebDavClient, WebDavError


@dataclass(frozen=True)
class IncomingMessage:
    id: int
    actor_id: str
    actor_type: str
    actor_display_name: str
    text: str
    timestamp: int
    is_system: bool


def _parse_message(raw: dict[str, Any]) -> IncomingMessage:
    return IncomingMessage(
        id=int(raw["id"]),
        actor_id=raw.get("actorId", ""),
        actor_type=raw.get("actorType", ""),
        actor_display_name=raw.get("actorDisplayName", ""),
        text=raw.get("message", ""),
        timestamp=int(raw.get("timestamp", 0)),
        is_system=raw.get("systemMessage", "") != "" or raw.get("messageType") == "system",
    )


class TalkGateway:
    """Polling + posting against Nextcloud Talk."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._talk = TalkClient(settings)
        self._ocs = OCSClient(settings)
        self._webdav = WebDavClient(settings)
        self.own_user = settings.nc_user

    def close(self) -> None:
        self._talk.close()
        self._ocs.close()
        self._webdav.close()

    def __enter__(self) -> TalkGateway:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- read --------------------------------------------------------------

    def list_conversations(self) -> list[Conversation]:
        return self._talk.list_conversations()

    def latest_message_id(self, token: str) -> int:
        """Most recent message id in a conversation, or 0 if empty.

        Used to initialise the long-poll cursor so a freshly-watched
        conversation does not replay its whole history.
        """
        data = self._ocs.get(
            f"/api/v1/chat/{token}",
            params={"lookIntoFuture": 0, "limit": 1},
        )
        if not data:
            return 0
        return max(int(m["id"]) for m in data)

    def poll(self, token: str, last_known_message_id: int, timeout: int = 30) -> list[IncomingMessage]:
        """Long-poll for new messages after ``last_known_message_id``.

        Mirrors ``nextcloud_talk_core.TalkClient.wait_for_messages`` but returns
        raw-parsed messages including the stable author id. Returns [] on
        timeout with no new messages.
        """
        timeout = min(timeout, 60)
        data = self._ocs.get(
            f"/api/v1/chat/{token}",
            params={
                "lookIntoFuture": 1,
                "lastKnownMessageId": last_known_message_id,
                "limit": 100,
                "timeout": timeout,
            },
            # HTTP timeout must outlast the server-side long-poll.
            timeout=timeout + 30,
        )
        if not data:
            return []
        return [_parse_message(m) for m in data]

    # --- write -------------------------------------------------------------

    def send(self, token: str, text: str, reply_to: int | None = None) -> None:
        self._talk.send_message(token, text, reply_to=reply_to)

    def upload_and_share(
        self,
        token: str,
        remote_path: str,
        content: bytes,
        *,
        caption: str | None = None,
        content_type: str = "text/markdown",
    ) -> None:
        """Upload ``content`` to the server via WebDAV, then share it into the
        conversation. Uploading first removes the dependency on a desktop sync
        client having already pushed the file."""
        path = self._webdav.upload(remote_path, content, content_type=content_type)
        self._talk.share_file(token, path, caption=caption)


__all__ = ["IncomingMessage", "TalkGateway", "NextcloudTalkError", "WebDavError"]
