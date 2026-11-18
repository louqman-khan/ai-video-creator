from __future__ import annotations

from app.config import Settings
from app.providers.base import Registry

from .faster_whisper import FasterWhisperTranscriber
from .interface import Transcriber

registry: Registry[Transcriber] = Registry("transcriber")


@registry.register("faster_whisper")
def _fw(settings: Settings) -> Transcriber:
    return FasterWhisperTranscriber(settings.whisper_model, settings.whisper_prompt, settings.whisper_beam)


def create_transcriber(settings: Settings) -> Transcriber:
    return registry.create(settings.transcriber, settings)


__all__ = ["Transcriber", "create_transcriber"]
