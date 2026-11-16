"""TTS provider interface (Step 5). No engine yet: 'none' fails with a clear message.
Planned defaults: Meta MMS-TTS (Urdu), Piper/Kokoro (English)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.providers.base import Registry


class TTS(Protocol):
    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        """Text -> narration audio file."""
        ...


class UnavailableTTS:
    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        raise NotImplementedError("No TTS engine is configured yet (planned for Step 5).")


registry: Registry[TTS] = Registry("tts")


@registry.register("none")
def _none(settings: Settings) -> TTS:
    return UnavailableTTS()


def create_tts(settings: Settings) -> TTS:
    return registry.create(settings.tts, settings)


__all__ = ["TTS", "create_tts"]
