"""AudioCleaner provider. Step 1 ships only a no-op; DeepFilterNet/loudnorm arrive in Step 2."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.providers.base import Registry


class AudioCleaner(Protocol):
    def clean(self, src: Path, dst: Path) -> Path:
        """Return the path of the cleaned audio (may be `src` itself)."""
        ...


class NoopCleaner:
    def clean(self, src: Path, dst: Path) -> Path:
        return src


registry: Registry[AudioCleaner] = Registry("audio cleaner")


@registry.register("noop")
def _noop(settings: Settings) -> AudioCleaner:
    return NoopCleaner()


def create_cleaner(settings: Settings) -> AudioCleaner:
    return registry.create(settings.audio_cleaner, settings)


__all__ = ["AudioCleaner", "create_cleaner"]
