#!/usr/bin/env python3
"""Real check of the English voice THROUGH THE PRODUCT (run on Linux by .github/workflows/voice-product-check.yml): hosted-mode settings, the voice factory, a real WAV,
and Whisper listening to it again. Prints ::notice/::error lines so the result can be read without a login."""

from __future__ import annotations

import sys
import time
import traceback
import wave
from pathlib import Path

import numpy as np

TEXT = "Never underestimate the power of small steps. Remember, success isn't built overnight. Start today!"


def note(kind: str, msg: str) -> None:
    print(f"::{kind} title=product voice check::" + msg.replace("%", "%25").replace("\n", " "), flush=True)


def main() -> int:
    from faster_whisper import WhisperModel

    from app.config import Settings
    from app.providers.tts import create_tts

    s = Settings(_env_file=None, mode="hosted", tts="auto")            # the public site: personal-use voices are off
    tts = create_tts(s)
    langs = tts.languages()
    note("notice", f"hosted voices available: {langs}")
    if langs != ["en"]:
        note("error", f"expected exactly ['en'] on the hosted site, got {langs}")
        return 1
    out = Path("english_check.wav")
    t0 = time.time()
    tts.synthesize(TEXT, "en", out)
    made = time.time() - t0
    with wave.open(str(out)) as w:
        rate, frames = w.getframerate(), w.getnframes()
        audio = np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32) / 32768.0
    secs = frames / rate
    x16 = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate)), np.arange(len(audio)), audio).astype(np.float32)
    segs, _ = WhisperModel("small", device="cpu", compute_type="int8").transcribe(x16, language="en", beam_size=5)
    heard = " ".join(sg.text for sg in segs).strip()
    note("notice", f"made {secs:.1f}s of audio at {rate} Hz in {made:.1f}s; Whisper heard: {heard}")
    try:
        tts.synthesize("ہیلو", "ur", Path("urdu.wav"))
        note("error", "Urdu should not be available on the hosted site")
        return 1
    except Exception as e:  # noqa: BLE001
        note("notice", f"Urdu correctly refused: {type(e).__name__}: {str(e)[:120]}")
    ok = "small steps" in heard.lower() and "start today" in heard.lower()
    note("notice" if ok else "error", "RESULT: " + ("PASS, the product speaks English on the hosted site" if ok else "FAIL, Whisper did not hear the sentence"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        note("error", traceback.format_exc()[-900:])
        sys.exit(1)
