"""Text-to-speech via an OpenAI-compatible ``/audio/speech`` endpoint.

Used to synthesise the assistant reply into an audio file that is uploaded to
Nextcloud and shared into the conversation (toggled per-conversation by /tts).
"""

from __future__ import annotations

import httpx


class TTSError(Exception):
    """Synthesis failed."""


class TTSClient:
    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        timeout: float = 120.0,
    ) -> None:
        self._url = url.rstrip("/") + "/audio/speech"
        self._model = model
        self._voice = voice
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def synthesize(self, text: str) -> bytes:
        body = {"model": self._model, "input": text, "voice": self._voice}
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise TTSError(f"synthesis request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise TTSError(f"synthesis -> HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.content
