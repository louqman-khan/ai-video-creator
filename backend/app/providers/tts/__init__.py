"""Text-to-speech: a typed script becomes a narration file the normal pipeline can use (task 5.1).

Engines (all run on the CPU through onnxruntime; models are files in `assets/models/tts/`, see docs/tts.md):
- `mms`   Meta MMS-TTS (VITS) converted to ONNX. Urdu. Licence CC-BY-NC 4.0 (not for commercial use).
- `piper` Piper voices (ONNX + bundled espeak-ng phonemes). English.
- `auto`  (default) mms for Urdu, piper for English, whichever has its model installed.
- `elevenlabs` a PAID cloud voice, only when chosen explicitly and keyed (docs/paid-providers.md); never part of `auto`.
- `none`  no speech: asking for it explains how to set it up."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.providers.base import Registry


class TTSUnavailable(RuntimeError):
    """No voice for this language is installed (the message says how to get one)."""


class TTS(Protocol):
    def languages(self) -> list[str]:
        """Language codes that can be spoken right now."""
        ...

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        """Text -> narration WAV file."""
        ...


class UnavailableTTS:
    def languages(self) -> list[str]:
        return []

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        raise TTSUnavailable("Speech is switched off (TTS=none).")


registry: Registry[TTS] = Registry("tts")


@registry.register("none")
def _none(settings: Settings) -> TTS:
    return UnavailableTTS()


@registry.register("mms")
def _mms(settings: Settings) -> TTS:
    from app.providers.tts.mms_onnx import MmsOnnxTTS

    return MmsOnnxTTS(Path(settings.tts_dir))


@registry.register("piper")
def _piper(settings: Settings) -> TTS:
    from app.providers.tts.piper import PiperTTS

    return PiperTTS(Path(settings.tts_dir))


@registry.register("elevenlabs")
def _elevenlabs(settings: Settings) -> TTS:
    from app.providers.tts.elevenlabs import ElevenLabsTTS

    return ElevenLabsTTS(settings)  # paid: never part of "auto"


@registry.register("auto")
def _auto(settings: Settings) -> TTS:
    from app.providers.tts.router import RouterTTS

    return RouterTTS([_mms(settings), _piper(settings)])


def create_tts(settings: Settings) -> TTS:
    return registry.create(settings.tts, settings)


__all__ = ["TTS", "TTSUnavailable", "create_tts"]
