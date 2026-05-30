"""Allowlist enforcement — the bridge's primary access control.

Messages are only acted on if their author is an allowlisted Talk user. The
author is matched on the STABLE user id (OCS ``actorId`` with
``actorType == "users"``), never the display name — display names are not
unique and can be changed. This is why the bridge polls raw OCS message dicts
(see ``talk.py``) instead of relying on ``nextcloud_talk_core.Message.actor``,
which collapses to the display name.
"""

from __future__ import annotations

from collections.abc import Iterable


class Allowlist:
    def __init__(self, user_ids: Iterable[str]) -> None:
        self._users = frozenset(u.strip() for u in user_ids if u.strip())
        if not self._users:
            # Defensive: Config.from_env already guarantees this, but never
            # allow an empty allowlist to be constructed silently.
            raise ValueError("allowlist must not be empty")

    def is_allowed(self, actor_id: str, actor_type: str = "users") -> bool:
        """True iff this is a real user on the allowlist.

        Bots, guests, federated users, and system actors are always rejected
        regardless of id collisions, because actor_type must be "users".
        """
        return actor_type == "users" and actor_id in self._users

    def __contains__(self, actor_id: object) -> bool:
        return isinstance(actor_id, str) and actor_id in self._users
