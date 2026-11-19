#!/usr/bin/env python3
"""Free-voice experiment (runs on a Linux machine, see .github/workflows/voice-experiment.yml): can Kokoro (Apache 2.0) read English, and Urdu through its Hindi voices?

For each voice it makes a WAV, notes how fast it was made, and has Whisper listen to it again and compare the words with the text (a rough proxy for "is it understandable";
the real judge is a person listening to the WAV files in the artifact). Urdu is written in Devanagari first (done by Gemini in the product; fixed texts here)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import soundfile as sf
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro

OUT = Path("out")
OUT.mkdir(exist_ok=True)

EN = ("Never underestimate the power of small steps. You don't need to change your entire life in one day. Just improve a little every single day. "
      "Remember, success isn't built overnight. It's built through small actions repeated consistently. Start today!")
UR = [  # (Urdu as the person types it, the same sentence in Devanagari as the Hindi voice needs it)
    ("ہر کہانی ایک منظر سے شروع ہوتی ہے", "हर कहानी एक मंज़र से शुरू होती है"),
    ("پاکستان کے شمالی علاقوں میں خوبصورت وادیاں ہیں", "पाकिस्तान के शुमाली इलाक़ों में ख़ूबसूरत वादियाँ हैं"),
    ("چھوٹے قدموں کی طاقت کو کبھی کم نہ سمجھیں۔ آج ہی شروع کریں!", "छोटे क़दमों की ताक़त को कभी कम न समझें। आज ही शुरू करें!"),
]


def words(t: str) -> list[str]:
    return [w for w in re.sub(r"[^\w\s]", " ", t.lower()).split() if w]


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return d[-1] / max(1, len(ref))


def main() -> None:
    k = Kokoro("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
    print("available voices:", sorted(k.get_voices()))
    whisper = WhisperModel("small", device="cpu", compute_type="int8")
    rows = []

    def run(label: str, text: str, voice: str, lang: str, whisper_lang: str, reference: str | None = None) -> None:
        t0 = time.time()
        samples, sr = k.create(text, voice=voice, speed=1.0, lang=lang)
        made = time.time() - t0
        path = OUT / f"{label}.wav"
        sf.write(path, samples, sr)
        secs = len(samples) / sr
        segs, _ = whisper.transcribe(str(path), language=whisper_lang, beam_size=5)
        heard = " ".join(s.text for s in segs).strip()
        score = wer(words(reference or text), words(heard))
        rows.append({"label": label, "voice": voice, "audio_s": round(secs, 1), "made_in_s": round(made, 1), "x_realtime": round(secs / made, 1), "whisper_heard": heard, "word_error": round(score, 3)})
        print(rows[-1], flush=True)

    for voice, lang in (("af_heart", "en-us"), ("am_michael", "en-us"), ("bf_emma", "en-gb")):
        run(f"english_{voice}", EN, voice, lang, "en")
    hindi = [v for v in ("hf_alpha", "hf_beta", "hm_omega", "hm_psi") if v in k.get_voices()]
    for voice in hindi:
        for i, (ur, deva) in enumerate(UR, 1):
            run(f"urdu_via_hindi_{voice}_{i}", deva, voice, "hi", "hi")
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    md = ["| file | voice | audio s | made in s | x real time | Whisper heard | word error |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['label']} | {r['voice']} | {r['audio_s']} | {r['made_in_s']} | {r['x_realtime']} | {r['whisper_heard']} | {r['word_error']} |" for r in rows]
    (OUT / "results.md").write_text("\n".join(md) + "\n", "utf-8")


if __name__ == "__main__":
    sys.exit(main())
