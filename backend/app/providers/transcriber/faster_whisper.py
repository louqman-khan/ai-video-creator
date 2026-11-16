from __future__ import annotations

from pathlib import Path

from app.models import Segment, Transcript, Word


class FasterWhisperTranscriber:
    def __init__(self, model_size: str = "small") -> None:
        self.model_size = model_size
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy: heavy import

            # int8 on CPU is the fast path on a laptop
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio: Path, language: str | None = None) -> Transcript:
        segments_iter, info = self._load().transcribe(
            str(audio), language=language, word_timestamps=True, vad_filter=True
        )
        segments: list[Segment] = []
        for s in segments_iter:
            words = [
                Word(text=w.word.strip(), start=w.start, end=w.end)
                for w in (s.words or [])
                if w.word.strip()
            ]
            if words:
                segments.append(
                    Segment(text=s.text.strip(), start=s.start, end=s.end, words=words)
                )
        return Transcript(language=info.language, duration=info.duration, segments=segments)
