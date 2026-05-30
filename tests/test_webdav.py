from __future__ import annotations

import httpx
import pytest
from nextcloud_talk_core import Settings

from opencode_talk_bridge.webdav import WebDavClient, WebDavError, _encode_path, _parent

SETTINGS = Settings(nc_url="https://cloud.example.com", nc_user="bot", nc_app_password="pw")


def _client(handler) -> WebDavClient:
    wd = WebDavClient(SETTINGS)
    wd._client = httpx.Client(transport=httpx.MockTransport(handler))
    return wd


def test_upload_simple_put():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(201)

    wd = _client(handler)
    path = wd.upload("/Bridge/file.md", b"hello")
    assert path == "/Bridge/file.md"
    assert calls == [("PUT", "/remote.php/dav/files/bot/Bridge/file.md")]


def test_upload_creates_dir_on_409_then_retries():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "PUT" and len([c for c in calls if c[0] == "PUT"]) == 1:
            return httpx.Response(409)  # parent missing on first PUT
        if req.method == "MKCOL":
            return httpx.Response(201)
        return httpx.Response(204)  # second PUT succeeds

    wd = _client(handler)
    path = wd.upload("/a/b/file.md", b"x")
    assert path == "/a/b/file.md"
    methods = [m for m, _ in calls]
    assert methods.count("PUT") == 2
    assert methods.count("MKCOL") == 2  # /a and /a/b


def test_mkcol_405_already_exists_is_ok():
    state = {"put": 0}

    def handler(req):
        if req.method == "PUT":
            state["put"] += 1
            return httpx.Response(409) if state["put"] == 1 else httpx.Response(201)
        return httpx.Response(405)  # collection already exists

    wd = _client(handler)
    assert wd.upload("/x/file.md", b"y") == "/x/file.md"


def test_upload_error_raises():
    def handler(req):
        return httpx.Response(507, text="insufficient storage")

    with pytest.raises(WebDavError):
        _client(handler).upload("/file.md", b"z")


def test_transport_error_raises():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(WebDavError):
        _client(boom).upload("/file.md", b"z")


def test_encode_path_quotes_segments():
    assert _encode_path("/a b/c.md") == "/a%20b/c.md"
    assert _parent("/a/b/c.md") == "/a/b"
    assert _parent("/file.md") == "/"
