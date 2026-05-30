"""Speech-to-text via an OpenAI-compatible ``/audio/transcriptions`` endpoint.

Used to transcribe incoming Talk voice notes into a prompt. Compatible with
OpenAI, Groq, Together, and self-hosted Whisper servers.
"""

from __future__ import annotations

import httpx


class STTError(Exception):
    """Transcription failed."""


class STTClient:
    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        model: str = "whisper-large-v3-turbo",
        language: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._url = url.rstrip("/") + "/audio/transcriptions"
        self._model = model
        self._language = language
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def transcribe(self, audio: bytes, filename: str = "audio.ogg") -> str:
        data: dict[str, str] = {"model": self._model}
        if self._language:
            data["language"] = self._language
        try:
            resp = self._client.post(self._url, files={"file": (filename, audio)}, data=data)
        except httpx.HTTPError as exc:
            raise STTError(f"transcription request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise STTError(f"transcription -> HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return (resp.json().get("text") or "").strip()
        except ValueError as exc:
            raise STTError(f"non-JSON transcription response: {exc}") from exc
