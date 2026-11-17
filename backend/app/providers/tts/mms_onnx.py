"""Meta MMS-TTS (VITS) through onnxruntime. One folder per language in `<tts_dir>/mms-<code>/` made by backend/tools/export_mms_onnx.py."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from app.text.urdu import normalize_text as normalize_urdu
from app.providers.tts import TTSUnavailable
from app.providers.tts.text import sentences, write_wav

log = logging.getLogger("avc.tts")
FOLDER = {"ur": "mms-urd", "en": "mms-eng"}  # language code -> model folder name


class MmsOnnxTTS:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._voices: dict[str, _Voice] = {}

    def languages(self) -> list[str]:
        return [lang for lang, d in FOLDER.items() if (self.root / d / "model.onnx").is_file()]

    def _voice(self, language: str) -> _Voice:
        if language not in self._voices:
            d = self.root / FOLDER.get(language, "-")
            if not (d / "model.onnx").is_file():
                raise TTSUnavailable(f"No MMS voice for '{language}' is installed. Convert one with backend/tools/export_mms_onnx.py (see docs/tts.md).")
            self._voices[language] = _Voice(d)
        return self._voices[language]

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        v = self._voice(language)
        if language == "ur":
            text = normalize_urdu(text)
        pieces = [v.speak(s) for s in sentences(text)]
        pieces = [p for p in pieces if p.size]
        if not pieces:
            raise TTSUnavailable("There is nothing in this text the voice can say.")
        return write_wav(out, pieces, v.sample_rate)


class _Voice:
    def __init__(self, folder: Path) -> None:
        import onnxruntime as ort

        meta = json.loads((folder / "voice.json").read_text("utf-8"))
        self.vocab: dict[str, int] = json.loads((folder / "vocab.json").read_text("utf-8"))
        self.sample_rate = int(meta["sample_rate"])
        self.add_blank = bool(meta.get("add_blank", True))
        self.normalize = bool(meta.get("normalize", True))
        self.unk = self.vocab.get(meta.get("unk_token") or "<unk>")
        self.sess = ort.InferenceSession(str(folder / "model.onnx"), providers=["CPUExecutionProvider"])

    def tokens(self, text: str) -> list[int]:
        """Characters -> ids exactly like the Hugging Face VitsTokenizer: lower-case, unknown characters dropped, a blank (id 0) between characters."""
        if self.normalize:
            text = text.lower()
        ids = [self.vocab[c] for c in text if c in self.vocab]
        if self.add_blank:
            spaced = [0] * (len(ids) * 2 + 1)
            spaced[1::2] = ids
            ids = spaced
        return ids

    def speak(self, sentence: str) -> np.ndarray:
        ids = self.tokens(sentence)
        if len(ids) <= 1:
            return np.zeros(0, dtype=np.float32)
        arr = np.asarray([ids], dtype=np.int64)
        wav = self.sess.run(None, {"input_ids": arr, "attention_mask": np.ones_like(arr)})[0]
        return np.asarray(wav, dtype=np.float32).reshape(-1)
