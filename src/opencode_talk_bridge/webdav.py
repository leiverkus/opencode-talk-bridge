"""Minimal WebDAV client for uploading attachments to Nextcloud.

``nextcloud-talk-core`` only speaks the OCS API; sharing a file into a Talk
conversation (``TalkClient.share_file``) requires the file to already exist on
the server. This client uploads the file first via WebDAV (``PUT``), creating
the target collection if needed (``MKCOL``), so the bridge does not depend on a
desktop sync client having uploaded it.

It reuses the same Basic-Auth app-password credentials as the OCS client.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
from nextcloud_talk_core import Settings


class WebDavError(Exception):
    """An upload or collection-creation failed."""


class WebDavClient:
    def __init__(self, settings: Settings, *, timeout: float = 60.0) -> None:
        self._user = settings.nc_user
        # Files live under the user's principal collection.
        self._base = f"{settings.nc_url}/remote.php/dav/files/{quote(settings.nc_user)}"
        self._client = httpx.Client(
            auth=httpx.BasicAuth(settings.nc_user, settings.nc_app_password),
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def upload(self, remote_path: str, content: bytes, *, content_type: str = "text/markdown") -> str:
        """Upload ``content`` to ``remote_path`` (relative to the user root).

        Creates parent collections on demand. Returns the normalised path
        (leading slash, suitable for ``TalkClient.share_file``).
        """
        path = "/" + remote_path.strip("/")
        url = self._base + _encode_path(path)
        resp = self._put(url, content, content_type)
        if resp.status_code == 409:  # parent collection missing
            self._ensure_dir(_parent(path))
            resp = self._put(url, content, content_type)
        if resp.status_code >= 400:
            raise WebDavError(f"PUT {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return path

    def download(self, remote_path: str) -> bytes:
        """Download a file by its path relative to the user root."""
        path = "/" + remote_path.strip("/")
        url = self._base + _encode_path(path)
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise WebDavError(f"download {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise WebDavError(f"GET {path} -> HTTP {resp.status_code}")
        return resp.content

    def _put(self, url: str, content: bytes, content_type: str) -> httpx.Response:
        try:
            return self._client.request("PUT", url, content=content, headers={"Content-Type": content_type})
        except httpx.HTTPError as exc:
            raise WebDavError(f"upload failed: {exc}") from exc

    def _ensure_dir(self, dir_path: str) -> None:
        """MKCOL each segment of ``dir_path`` (idempotent)."""
        parts = [p for p in dir_path.strip("/").split("/") if p]
        cumulative = ""
        for part in parts:
            cumulative += "/" + part
            url = self._base + _encode_path(cumulative)
            try:
                resp = self._client.request("MKCOL", url)
            except httpx.HTTPError as exc:
                raise WebDavError(f"MKCOL {cumulative} failed: {exc}") from exc
            # 201 Created, or 405 Method Not Allowed (already exists) are both fine.
            if resp.status_code not in (201, 405):
                raise WebDavError(f"MKCOL {cumulative} -> HTTP {resp.status_code}")


def _encode_path(path: str) -> str:
    """Percent-encode each path segment, preserving slashes."""
    return "/" + "/".join(quote(seg) for seg in path.strip("/").split("/") if seg)


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"
