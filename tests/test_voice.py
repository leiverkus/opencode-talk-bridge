from __future__ import annotations

import httpx
import pytest

from opencode_talk_bridge.stt import STTClient, STTError
from opencode_talk_bridge.tts import TTSClient, TTSError


def _stt(handler) -> STTClient:
    c = STTClient("http://stt.test/v1", api_key="k", model="whisper")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _tts(handler) -> TTSClient:
    c = TTSClient("http://tts.test/v1", api_key="k", model="tts", voice="alloy")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_stt_transcribes():
    def handler(req):
        assert req.url.path.endswith("/audio/transcriptions")
        assert b"whisper" in req.content
        return httpx.Response(200, json={"text": " hello world "})

    assert _stt(handler).transcribe(b"audiobytes", "note.ogg") == "hello world"


def test_stt_http_error():
    def handler(req):
        return httpx.Response(500, text="boom")

    with pytest.raises(STTError):
        _stt(handler).transcribe(b"x")


def test_stt_transport_error():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(STTError):
        _stt(boom).transcribe(b"x")


def test_tts_synthesizes():
    import json

    def handler(req):
        body = json.loads(req.content)
        assert body == {"model": "tts", "input": "hello", "voice": "alloy"}
        return httpx.Response(200, content=b"AUDIO")

    assert _tts(handler).synthesize("hello") == b"AUDIO"


def test_tts_http_error():
    def handler(req):
        return httpx.Response(503, text="no")

    with pytest.raises(TTSError):
        _tts(handler).synthesize("hi")
