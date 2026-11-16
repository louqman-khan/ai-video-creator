from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.models import Transcript


class Transcriber(Protocol):
    def transcribe(self, audio: Path, language: str | None = None) -> Transcript:
        """Speech -> text with word-level timestamps. language=None -> auto-detect."""
        ...
