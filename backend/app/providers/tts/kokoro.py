"""Kokoro-82M English voices (Apache 2.0: free for commercial use), run on the CPU through onnxruntime (package `kokoro-onnx`).

Files, made by `avc fetch-models --kokoro`: `<tts_dir>/kokoro-en/kokoro-v1.0.int8.onnx` and `voices-v1.0.bin`. English only (US and British voices).
Not subject to the personal-use gate of the other free voices, so the public (hosted) site can offer it. Note: the phoneme step uses espeak-ng (GPL): fine for a site we run
ourselves, to be reviewed before an installer carrying it is given to other people."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from app.providers.tts import TTSUnavailable
from app.providers.tts.text import sentences, write_wav

log = logging.getLogger("avc.tts")

MODEL = "kokoro-v1.0.int8.onnx"
VOICES = "voices-v1.0.bin"
DEFAULT_VOICE = "af_heart"
# the voices we offer: name -> (label, espeak language of the voice)
VOICE_LANG = {"af_heart": "en-us", "af_bella": "en-us", "af_nicole": "en-us", "am_michael": "en-us", "am_adam": "en-us", "bf_emma": "en-gb", "bm_george": "en-gb"}


def folder(root: Path) -> Path:
    return root / "kokoro-en"


def files_present(root: Path) -> bool:
    d = folder(root)
    return (d / MODEL).is_file() and (d / VOICES).is_file()


class KokoroTTS:
    def __init__(self, root: Path, voice: str = DEFAULT_VOICE) -> None:
        self.root = root
        self.voice = voice if voice in VOICE_LANG else DEFAULT_VOICE
        self._engine = None
        self._lock = threading.Lock()  # espeak-ng keeps process-wide state: one speech at a time

    def languages(self) -> list[str]:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return []
        return ["en"] if files_present(self.root) else []

    def _load(self):
        if self._engine is None:
            from kokoro_onnx import Kokoro

            d = folder(self.root)
            self._engine = Kokoro(str(d / MODEL), str(d / VOICES))
        return self._engine

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        if language != "en":
            raise TTSUnavailable("The Kokoro voices speak English only.")
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            raise TTSUnavailable("The 'kokoro-onnx' package is not installed (pip install kokoro-onnx).") from None
        if not files_present(self.root):
            raise TTSUnavailable(f"The English voice files are not downloaded yet (run `avc fetch-models --kokoro`; they go to {folder(self.root)}).")
        name = voice if voice in VOICE_LANG else self.voice
        pieces: list[np.ndarray] = []
        rate = 24000
        with self._lock:
            engine = self._load()
            for s in sentences(text):
                samples, rate = engine.create(s, voice=name, speed=1.0, lang=VOICE_LANG[name])
                pieces.append(np.asarray(samples, dtype=np.float32))
        if not pieces:
            raise TTSUnavailable("There is nothing in this text the voice can say.")
        return write_wav(out, pieces, int(rate))
