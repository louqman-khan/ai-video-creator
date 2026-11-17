"""Piper voices (ONNX). One voice = `<name>.onnx` + `<name>.onnx.json` in `<tts_dir>/piper-<code>/`; the first one found is used."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.providers.tts import TTSUnavailable
from app.providers.tts.text import sentences, write_wav

log = logging.getLogger("avc.tts")


class PiperTTS:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._loaded: dict[str, object] = {}

    def _model(self, language: str) -> Path | None:
        d = self.root / f"piper-{language}"
        found = sorted(d.glob("*.onnx")) if d.is_dir() else []
        return found[0] if found else None

    def languages(self) -> list[str]:
        try:
            import piper  # noqa: F401
        except ImportError:
            return []
        return [lang for lang in ("en", "ur") if self._model(lang)]

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        try:
            from piper import PiperVoice
        except ImportError:
            raise TTSUnavailable("The 'piper-tts' package is not installed (pip install piper-tts).") from None
        model = self._model(language)
        if model is None:
            raise TTSUnavailable(f"No Piper voice for '{language}' is installed. Put a voice (.onnx and .onnx.json) in {self.root / f'piper-{language}'} (see docs/tts.md).")
        if language not in self._loaded:
            self._loaded[language] = PiperVoice.load(model)
        pv = self._loaded[language]
        pieces: list[np.ndarray] = []
        rate = int(pv.config.sample_rate)  # type: ignore[attr-defined]
        for s in sentences(text):
            chunks = [np.asarray(c.audio_float_array, dtype=np.float32) for c in pv.synthesize(s)]  # type: ignore[attr-defined]
            if chunks:
                pieces.append(np.concatenate(chunks))
        if not pieces:
            raise TTSUnavailable("There is nothing in this text the voice can say.")
        return write_wav(out, pieces, rate)
