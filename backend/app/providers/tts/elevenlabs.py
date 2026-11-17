"""ElevenLabs text-to-speech: a PAID service (it uses your character quota), only used when TTS=elevenlabs and ELEVENLABS_API_KEY is set.

Written from the public API description (POST /v1/text-to-speech/{voice_id}); it has been exercised with mocked HTTP only, not with a live account."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import numpy as np

from app.config import Settings
from app.http import make_client
from app.providers.tts import TTSUnavailable
from app.providers.tts.text import sentences, write_wav

API = "https://api.elevenlabs.io/v1/text-to-speech"
RATE = 24000
CHUNK_CHARS = 2500  # well inside the per-request limit


def decode_mp3(data: bytes) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"], input=data, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise TTSUnavailable("ElevenLabs sent audio that could not be read.")
    return np.frombuffer(p.stdout, dtype="<f4")


class ElevenLabsTTS:
    paid = True

    def __init__(self, settings: Settings) -> None:
        self.key, self.model = settings.elevenlabs_api_key, settings.elevenlabs_model
        self.voices = {"en": settings.elevenlabs_voice_en, "ur": settings.elevenlabs_voice_ur}

    def languages(self) -> list[str]:
        return [lang for lang, v in self.voices.items() if self.key and v]

    def _chunks(self, text: str) -> list[str]:
        out: list[str] = []
        cur = ""
        for s in sentences(text, max_chars=CHUNK_CHARS):
            if cur and len(cur) + len(s) + 1 > CHUNK_CHARS:
                out.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        return [*out, cur] if cur else out

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        if not self.key:
            raise TTSUnavailable("ELEVENLABS_API_KEY is not set.")
        voice_id = voice or self.voices.get(language, "")
        if not voice_id:
            raise TTSUnavailable(f"No ElevenLabs voice is set for '{language}' (ELEVENLABS_VOICE_{language.upper()}).")
        pieces: list[np.ndarray] = []
        try:
            with make_client(read_timeout=120.0) as c:
                for chunk in self._chunks(text):
                    r = c.post(f"{API}/{voice_id}", params={"output_format": "mp3_44100_128"},
                               headers={"xi-api-key": self.key, "accept": "audio/mpeg"}, json={"text": chunk, "model_id": self.model})
                    if r.status_code == 401:
                        raise TTSUnavailable("ElevenLabs refused the key (HTTP 401).")
                    if r.status_code == 429 or r.status_code == 402:
                        raise TTSUnavailable("The ElevenLabs quota or rate limit is used up (HTTP %d)." % r.status_code)
                    r.raise_for_status()
                    pieces.append(decode_mp3(r.content))
        except httpx.HTTPStatusError as e:
            raise TTSUnavailable(f"ElevenLabs answered with an error (HTTP {e.response.status_code}).") from None
        except httpx.HTTPError:
            raise TTSUnavailable("ElevenLabs could not be reached.") from None
        if not pieces:
            raise TTSUnavailable("There is nothing in this text to speak.")
        return write_wav(out, pieces, RATE, pause_s=0.1)
