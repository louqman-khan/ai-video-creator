import sys
import types

import httpx
import pytest

from app.config import Settings
from app.providers.tts import TTSUnavailable, create_tts
from app.providers.tts import kokoro as kk
from app.providers.tts.urdu_script import GeminiTransliterator
from tests.test_kokoro import FakeKokoro, installed  # noqa: F401  (fixture)


def fake_gemini(answers):
    """A Gemini stand-in: each call returns the next answer (a list of strings) as the JSON the service would send."""
    import json

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        a = answers[min(len(calls) - 1, len(answers) - 1)]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"sentences": a})}]}}]})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_urdu_is_written_in_devanagari_then_read_by_the_hindi_voice(installed, tmp_path):  # noqa: F811
    client, calls = fake_gemini([["हर कहानी एक मंज़र से शुरू होती है।", "आज ही शुरू करें!"]])
    tts = kk.KokoroUrduTTS(kk.KokoroTTS(installed), GeminiTransliterator("k", "m", client))
    assert tts.languages() == ["ur"]
    tts.synthesize("ہر کہانی ایک منظر سے شروع ہوتی ہے۔ آج ہی شروع کریں!", "ur", tmp_path / "u.wav")
    asked = [c for c in FakeKokoro.calls if c[0] != "load"]
    assert [a[0] for a in asked] == ["हर कहानी एक मंज़र से शुरू होती है।", "आज ही शुरू करें!"] and {a[1:] for a in asked} == {("hf_alpha", "hi")}
    assert len(calls) == 1  # one request for the whole script, not one per sentence


def test_a_bad_answer_is_never_spoken(installed, tmp_path):  # noqa: F811
    for bad in (["ہر کہانی"], ["x"], []):  # Arabic script left, no Devanagari, wrong count
        client, _ = fake_gemini([bad])
        tts = kk.KokoroUrduTTS(kk.KokoroTTS(installed), GeminiTransliterator("k", "m", client))
        with pytest.raises(TTSUnavailable, match="could not be prepared"):
            tts.synthesize("ہر کہانی۔ دوسرا جملہ۔", "ur", tmp_path / "u.wav")


def test_no_gemini_key_or_no_voice_files_means_no_urdu_and_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=FakeKokoro))
    assert kk.KokoroUrduTTS(kk.KokoroTTS(tmp_path), lambda s: s).languages() == []  # files missing
    t = kk.KokoroUrduTTS(kk.KokoroTTS(tmp_path), None)
    assert t.languages() == []
    with pytest.raises(TTSUnavailable, match="Gemini key"):
        t.synthesize("ہاں۔", "ur", tmp_path / "x.wav")


def test_hosted_site_offers_urdu_when_a_key_is_set_and_english_always(installed):  # noqa: F811
    s = Settings(mode="hosted", tts="auto", tts_dir=str(installed), gemini_api_key="k", allow_noncommercial_voices=False, _env_file=None)
    assert create_tts(s).languages() == ["en", "ur"]
    s2 = Settings(mode="hosted", tts="auto", tts_dir=str(installed), gemini_api_key="", allow_noncommercial_voices=False, _env_file=None)
    assert create_tts(s2).languages() == ["en"]
    s3 = Settings(mode="hosted", tts="auto", tts_dir=str(installed), gemini_api_key="k", urdu_via_hindi=False, allow_noncommercial_voices=False, _env_file=None)
    assert create_tts(s3).languages() == ["en"]
