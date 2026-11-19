import hashlib
import sys
import types
import wave

import numpy as np
import pytest

from app.config import Settings
from app.media import models
from app.providers.tts import TTSUnavailable, create_tts
from app.providers.tts import kokoro as kk


class FakeKokoro:
    """Stands in for kokoro_onnx.Kokoro: a short tone per call, remembers what it was asked."""

    calls: list = []

    def __init__(self, model, voices):
        FakeKokoro.calls.append(("load", model, voices))

    def create(self, text, voice, speed, lang):
        FakeKokoro.calls.append((text, voice, lang))
        return np.sin(np.linspace(0, 200, 2400, dtype=np.float32)) * 0.5, 24000


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    """The voice 'installed' (two placeholder files) and the library 'importable' (the stand-in)."""
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=FakeKokoro))
    d = tmp_path / "kokoro-en"
    d.mkdir()
    (d / kk.MODEL).write_bytes(b"m")
    (d / kk.VOICES).write_bytes(b"v")
    FakeKokoro.calls = []
    return tmp_path


def test_it_speaks_english_sentence_by_sentence_with_the_chosen_voice_and_writes_a_wav(installed, tmp_path):
    t = kk.KokoroTTS(installed, voice="am_michael")
    assert t.languages() == ["en"]
    out = t.synthesize("First sentence. Second one!", "en", tmp_path / "o.wav")
    asked = [c for c in FakeKokoro.calls if c[0] != "load"]
    assert [a[0] for a in asked] == ["First sentence.", "Second one!"] and {a[1] for a in asked} == {"am_michael"} and {a[2] for a in asked} == {"en-us"}
    with wave.open(str(out)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getnframes() > 4800          # two pieces and the pause between them
    t.synthesize("Hi.", "en", tmp_path / "p.wav")
    assert sum(1 for c in FakeKokoro.calls if c[0] == "load") == 1                                      # the model is loaded once


def test_british_voices_use_british_pronunciation_and_an_unknown_voice_falls_back_to_the_default(installed, tmp_path):
    kk.KokoroTTS(installed).synthesize("Hello.", "en", tmp_path / "a.wav", voice="bf_emma")
    kk.KokoroTTS(installed).synthesize("Hello.", "en", tmp_path / "b.wav", voice="../../etc/passwd")
    asked = [c for c in FakeKokoro.calls if c[0] != "load"]
    assert asked[0][1:] == ("bf_emma", "en-gb") and asked[1][1:] == (kk.DEFAULT_VOICE, "en-us")


def test_it_says_clearly_when_it_cannot_speak(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=FakeKokoro))
    t = kk.KokoroTTS(tmp_path)
    assert t.languages() == []                                                       # no files yet
    with pytest.raises(TTSUnavailable, match="fetch-models --kokoro"):
        t.synthesize("Hi.", "en", tmp_path / "o.wav")
    with pytest.raises(TTSUnavailable, match="English only"):
        t.synthesize("ہیلو", "ur", tmp_path / "o.wav")
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)                              # the library is not installed
    assert kk.KokoroTTS(tmp_path).languages() == []


def test_the_public_site_has_the_english_voice_but_not_the_personal_use_ones(installed):
    hosted = Settings(_env_file=None, mode="hosted", tts="auto", tts_dir=str(installed))
    assert create_tts(hosted).languages() == ["en"]                                  # Kokoro is licence-clean; Urdu (MMS) and Piper stay off
    local = Settings(_env_file=None, mode="local", tts="auto", tts_dir=str(installed))
    assert "en" in create_tts(local).languages()


def test_auto_prefers_kokoro_for_english(installed, tmp_path):
    s = Settings(_env_file=None, mode="local", tts="auto", tts_dir=str(installed))
    create_tts(s).synthesize("Hello there.", "en", tmp_path / "o.wav")
    assert any(c[0] == "Hello there." for c in FakeKokoro.calls)


def test_the_model_download_is_checked_against_its_checksum(tmp_path, monkeypatch):
    payload = {"kokoro-v1.0.int8.onnx": b"model bytes", "voices-v1.0.bin": b"voice bytes"}
    monkeypatch.setattr(models, "KOKORO_FILES", tuple((n, hashlib.sha256(b).hexdigest()) for n, b in payload.items()))

    class Resp:
        def __init__(self, data):
            self.data, self.is_error, self.status_code = data, False, 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self, n):
            yield self.data

    class Client:
        bad = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            name = url.rsplit("/", 1)[1]
            return Resp(b"tampered" if Client.bad else payload[name])

    monkeypatch.setattr(models, "make_client", lambda **kw: Client())
    s = Settings(_env_file=None, tts_dir=str(tmp_path))
    assert not models.kokoro_ready(s)
    files = models.fetch_kokoro(s)
    assert [f.name for f in files] == list(payload) and (tmp_path / "kokoro-en" / "voices-v1.0.bin").read_bytes() == b"voice bytes"
    assert models.fetch_kokoro(s) == files                                              # already there and correct: nothing downloaded again
    Client.bad = True
    (tmp_path / "kokoro-en" / "voices-v1.0.bin").unlink()
    with pytest.raises(models.ModelError, match="not the expected file"):
        models.fetch_kokoro(s)
    assert not (tmp_path / "kokoro-en" / "voices-v1.0.bin").exists() and not list((tmp_path / "kokoro-en").glob("*.part"))   # a bad file is never kept
