from __future__ import annotations

from pathlib import Path

from app.models import Segment, Transcript, Word


class FasterWhisperTranscriber:
    def __init__(self, model_size: str = "small", prompt: str = "", beam_size: int = 5) -> None:
        self.model_size = model_size
        self.prompt = prompt.strip()  # names and terms the speaker uses: Whisper spells them the way they are written here
        self.beam_size = beam_size
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy: heavy import

            # int8 on CPU is the fast path on a laptop
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    @staticmethod
    def _load_wav(path: Path):
        """16 kHz mono 16-bit WAV -> float32 array. Bypasses PyAV decoding, whose newer versions
        break faster-whisper's own decoder (`metadata_errors` TypeError)."""
        import wave

        import numpy as np

        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
                raise ValueError("expected 16 kHz mono 16-bit WAV (the pipeline converts to this)")
            raw = w.readframes(w.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    def transcribe(self, audio: Path, language: str | None = None) -> Transcript:
        source = self._load_wav(audio) if audio.suffix.lower() == ".wav" else str(audio)
        segments_iter, info = self._load().transcribe(
            source, language=language, word_timestamps=True, vad_filter=True,
            beam_size=self.beam_size, initial_prompt=self.prompt or None,
        )
        segments: list[Segment] = []
        for s in segments_iter:
            words = [
                Word(text=w.word.strip(), start=w.start, end=w.end, prob=round(float(w.probability), 3))
                for w in (s.words or [])
                if w.word.strip()
            ]
            if words:
                segments.append(
                    Segment(text=s.text.strip(), start=s.start, end=s.end, words=words)
                )
        return Transcript(language=info.language, duration=info.duration, segments=segments)
