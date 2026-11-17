import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.providers.tts import TTSUnavailable, create_tts
from app.providers.tts.router import RouterTTS
from app.providers.tts.text import sentences, write_wav

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "assets" / "models" / "tts"


def test_script_is_split_into_sentences_in_english_and_urdu_and_long_ones_are_cut():
    assert sentences("One. Two! Three?\nFour") == ["One.", "Two!", "Three?", "Four"]
    assert sentences("پہلا جملہ۔ دوسرا جملہ؟ تیسرا") == ["پہلا جملہ۔", "دوسرا جملہ؟", "تیسرا"]
    long = ", ".join(["word"] * 80)
    parts = sentences(long, max_chars=100)
    assert len(parts) > 3 and all(len(p) <= 100 for p in parts) and " ".join(parts).replace(", ", " ").count("word") == 80
    assert sentences("   ") == []


def test_pieces_are_joined_with_pauses_and_never_clip(tmp_path):
    loud = np.full(1000, 3.0, dtype=np.float32)                                    # louder than full scale
    out = write_wav(tmp_path / "x.wav", [loud, loud], 1000, pause_s=0.5)
    w = wave.open(str(out))
    assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 1000)
    assert w.getnframes() == 2500                                                   # 1 s + 0.5 s pause + 1 s
    data = np.frombuffer(w.readframes(2500), dtype="<i2")
    assert data.max() <= 32767 and data[1200] == 0                                  # silence in the gap


def test_the_router_uses_the_first_engine_that_has_the_language(tmp_path):
    class Fake:
        def __init__(self, langs, tag):
            self.langs, self.tag = langs, tag

        def languages(self):
            return self.langs

        def synthesize(self, text, language, out, voice=None):
            out.write_text(self.tag)
            return out

    r = RouterTTS([Fake(["ur"], "mms"), Fake(["en", "ur"], "piper")])
    assert r.languages() == ["ur", "en"]
    assert r.synthesize("x", "ur", tmp_path / "a").read_text() == "mms"
    assert r.synthesize("x", "en", tmp_path / "b").read_text() == "piper"
    with pytest.raises(TTSUnavailable, match="fr"):
        r.synthesize("x", "fr", tmp_path / "c")


def test_none_and_missing_models_explain_themselves(tmp_path):
    s = Settings(_env_file=None, tts="none")
    assert create_tts(s).languages() == []
    with pytest.raises(TTSUnavailable):
        create_tts(s).synthesize("hi", "en", tmp_path / "o.wav")
    empty = create_tts(Settings(_env_file=None, tts="auto", tts_dir=str(tmp_path)))
    assert empty.languages() == []
    with pytest.raises(TTSUnavailable, match="docs/tts.md|installed"):
        empty.synthesize("hi", "ur", tmp_path / "o.wav")


@pytest.mark.skipif(not (MODELS / "mms-urd" / "model.onnx").is_file(), reason="the Urdu voice is not installed (docs/tts.md)")
def test_urdu_voice_speaks_and_tokenises_like_the_original(tmp_path):
    t = create_tts(Settings(_env_file=None, tts="mms"))
    assert "ur" in t.languages()
    out = t.synthesize("پاکستان کے پہاڑ۔ یہ ایک جملہ ہے۔", "ur", tmp_path / "ur.wav")
    w = wave.open(str(out))
    assert w.getframerate() == 16000 and 1.5 < w.getnframes() / 16000 < 15
    # same ids as the Hugging Face tokenizer (blank between characters, unknown characters dropped)
    v = t._voice("ur")
    ids = v.tokens("پاک x")
    assert ids[0] == 0 and ids[-1] == 0 and ids[1::2] == [v.vocab[c] for c in "پاک "] and len(ids) == 2 * 4 + 1


@pytest.mark.skipif(not (MODELS / "piper-en").is_dir() or not list((MODELS / "piper-en").glob("*.onnx")), reason="no English voice installed (docs/tts.md)")
def test_english_voice_speaks(tmp_path):
    t = create_tts(Settings(_env_file=None, tts="piper"))
    out = t.synthesize("Hello. This is a test.", "en", tmp_path / "en.wav")
    w = wave.open(str(out))
    assert w.getframerate() >= 16000 and 1.0 < w.getnframes() / w.getframerate() < 10
