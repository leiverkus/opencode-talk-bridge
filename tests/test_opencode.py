from __future__ import annotations

import json

import httpx
import pytest

from opencode_talk_bridge.opencode import (
    OpenCodeClient,
    OpenCodeDownError,
    OpenCodeError,
    _parse_model,
    _prompt_result,
)


def _client(handler) -> OpenCodeClient:
    oc = OpenCodeClient("http://oc.test", directory="/work")
    oc._client = httpx.Client(base_url="http://oc.test", transport=httpx.MockTransport(handler))
    return oc


def test_health_true_false():
    def ok(req):
        return httpx.Response(200, json={"healthy": True, "version": "1.15.11"})

    assert _client(ok).health() is True

    def bad(req):
        return httpx.Response(500, text="boom")

    assert _client(bad).health() is False


def test_health_transport_error_is_false():
    def boom(req):
        raise httpx.ConnectError("refused")

    assert _client(boom).health() is False


def test_create_session_returns_id():
    def handler(req):
        assert req.url.path == "/session"
        assert req.url.params.get("directory") == "/work"
        return httpx.Response(200, json={"id": "ses_abc", "title": "x"})

    assert _client(handler).create_session("hi") == "ses_abc"


def test_create_session_missing_id_raises():
    def handler(req):
        return httpx.Response(200, json={"title": "x"})

    with pytest.raises(OpenCodeError):
        _client(handler).create_session()


def test_prompt_collects_text_parts():
    def handler(req):
        body = json.loads(req.content)
        assert body["parts"] == [{"type": "text", "text": "hello"}]
        return httpx.Response(
            200,
            json={
                "info": {"role": "assistant", "time": {"completed": 1}},
                "parts": [
                    {"type": "text", "text": "Hi there"},
                    {"type": "tool", "text": "ignored"},
                    {"type": "text", "text": "line two"},
                ],
            },
        )

    result = _client(handler).prompt("ses_abc", "hello")
    assert result.text == "Hi there\nline two"
    assert result.aborted is False
    assert result.error is None


def test_prompt_with_model_override():
    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == {"providerID": "anthropic", "modelID": "claude-sonnet-4-6"}
        return httpx.Response(200, json={"info": {}, "parts": []})

    _client(handler).prompt("ses_abc", "hi", model="anthropic/claude-sonnet-4-6")


def test_prompt_aborted_flag():
    data = {"info": {"error": {"name": "MessageAbortedError"}}, "parts": []}
    result = _prompt_result(data)
    assert result.aborted is True
    assert result.error is None


def test_prompt_error_message():
    data = {"info": {"error": {"name": "APIError", "data": {"message": "rate limited"}}}, "parts": []}
    result = _prompt_result(data)
    assert result.aborted is False
    assert result.error == "rate limited"


def test_reply_permission_validates_outcome():
    def handler(req):
        return httpx.Response(200, json=True)

    oc = _client(handler)
    assert oc.reply_permission("perm_1", "once") is True
    with pytest.raises(ValueError):
        oc.reply_permission("perm_1", "maybe")


def test_list_permissions_maps_requests():
    def handler(req):
        return httpx.Response(
            200,
            json=[
                {
                    "id": "perm_1",
                    "sessionID": "ses_abc",
                    "permission": "bash",
                    "patterns": ["git status*"],
                    "tool": {"callID": "c1"},
                }
            ],
        )

    asks = _client(handler).list_permissions()
    assert len(asks) == 1
    assert asks[0].request_id == "perm_1"
    assert asks[0].session_id == "ses_abc"
    assert asks[0].patterns == ("git status*",)


def test_transport_error_maps_to_down():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(OpenCodeDownError):
        _client(boom).list_sessions()


def test_http_error_maps_to_opencode_error():
    def handler(req):
        return httpx.Response(404, text="nope")

    with pytest.raises(OpenCodeError):
        _client(handler).create_session()


def test_iter_events_parses_sse_payloads():
    stream = (
        'data: {"directory":"/w","payload":{"id":"e1","type":"permission.asked",'
        '"properties":{"id":"perm_1","sessionID":"ses_abc","permission":"bash"}}}\n'
        "\n"
        ": comment line ignored\n"
        "data: not-json\n"
        'data: {"payload":{"type":"session.idle","properties":{"sessionID":"ses_abc"}}}\n'
    )

    def handler(req):
        assert req.url.path == "/global/event"
        return httpx.Response(200, text=stream)

    events = list(_client(handler).iter_events())
    assert [e["type"] for e in events] == ["permission.asked", "session.idle"]
    assert events[0]["properties"]["sessionID"] == "ses_abc"


def test_iter_events_transport_error():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(OpenCodeDownError):
        list(_client(boom).iter_events())


def test_run_command_always_sends_arguments():
    def handler(req):
        body = json.loads(req.content)
        assert body == {"command": "pdf", "arguments": ""}  # arguments is required
        return httpx.Response(200, json={"info": {}, "parts": []})

    _client(handler).run_command("ses_1", "pdf")


def test_list_skills():
    def handler(req):
        assert req.url.path == "/skill"
        return httpx.Response(200, json=[{"name": "pdf", "description": "PDF skill"}])

    skills = _client(handler).list_skills()
    assert skills[0]["name"] == "pdf"


def test_parse_model():
    assert _parse_model(None) is None
    assert _parse_model("anthropic/claude") == {"providerID": "anthropic", "modelID": "claude"}
    with pytest.raises(ValueError):
        _parse_model("noslash")
