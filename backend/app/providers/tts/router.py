"""Pick, for each language, the first engine that has a voice for it."""

from __future__ import annotations

from pathlib import Path

from app.providers.tts import TTS, TTSUnavailable


class RouterTTS:
    def __init__(self, engines: list[TTS]) -> None:
        self.engines = engines

    def languages(self) -> list[str]:
        seen: list[str] = []
        for e in self.engines:
            seen += [lang for lang in e.languages() if lang not in seen]
        return seen

    def synthesize(self, text: str, language: str, out: Path, voice: str | None = None) -> Path:
        for e in self.engines:
            if language in e.languages():
                return e.synthesize(text, language, out, voice)
        raise TTSUnavailable(
            f"No voice for '{language}' is installed. English needs a Piper voice, Urdu a converted MMS voice (see docs/tts.md).")
