import json
import subprocess
import wave
from pathlib import Path

import httpx
import pytest
import respx

from app.api.jobs import redact
from app.config import Settings
from app.media import ffmpeg  # noqa: F401  (puts the bundled ffmpeg on PATH)
from app.providers.avatar_renderer import AvatarUnavailable, create_avatar_renderer
from app.providers.avatar_renderer.heygen import HeygenAvatars
from app.providers.tts import TTSUnavailable, create_tts
from app.providers.tts.elevenlabs import ElevenLabsTTS

KEY = "sk_live_1234567890abcdef"


def mp3(tmp_path, seconds=1.0):
    p = tmp_path / "x.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", str(p)], check=True)
    return p.read_bytes()


def wav(tmp_path):
    p = tmp_path / "n.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", str(p)], check=True)
    return p


def test_paid_providers_are_off_unless_chosen_and_keyed():
    s = Settings(_env_file=None)
    assert s.tts == "auto" and s.avatar_renderer == "simple"                         # defaults are the free local ones
    assert "elevenlabs" not in [type(e).__name__.lower() for e in create_tts(s).engines]          # auto never includes the paid voice
    assert ElevenLabsTTS(Settings(_env_file=None, elevenlabs_voice_ur="")).languages() == []      # no key: nothing offered
    assert ElevenLabsTTS(Settings(_env_file=None, elevenlabs_api_key=KEY)).languages() == ["en"]  # key but no Urdu voice: English only
    assert ElevenLabsTTS(Settings(_env_file=None, elevenlabs_api_key=KEY, elevenlabs_voice_ur="v")).languages() == ["en", "ur"]
    assert HeygenAvatars("").avatars() == []
    with pytest.raises(AvatarUnavailable, match="HEYGEN_API_KEY"):
        HeygenAvatars("").render("a", Path("x"), Path("o"))


def test_secrets_never_reach_error_messages():
    s = Settings(_env_file=None, elevenlabs_api_key=KEY, heygen_api_key=KEY + "H", avatar_token=KEY + "T")
    text = redact(f"boom {KEY} {KEY}H {KEY}T", s)
    assert KEY not in text and "***" in text


@respx.mock
def test_elevenlabs_speaks_in_chunks_and_sends_the_key_only_to_elevenlabs(tmp_path):
    route = respx.post("https://api.elevenlabs.io/v1/text-to-speech/voiceA").mock(return_value=httpx.Response(200, content=mp3(tmp_path)))
    tts = ElevenLabsTTS(Settings(_env_file=None, elevenlabs_api_key=KEY, elevenlabs_voice_en="voiceA", elevenlabs_model="m1"))
    out = tts.synthesize("Hello there. " + "This is a sentence. " * 300, "en", tmp_path / "o.wav")
    assert route.call_count >= 2                                                      # a long script is sent in several requests
    req = route.calls[0].request
    assert req.headers["xi-api-key"] == KEY and json.loads(req.content)["model_id"] == "m1"
    assert req.url.params["output_format"] == "mp3_44100_128"
    w = wave.open(str(out))
    assert w.getframerate() == 24000 and w.getnframes() / 24000 > route.call_count * 0.9


@respx.mock
def test_elevenlabs_failures_are_explained_without_the_key(tmp_path):
    tts = ElevenLabsTTS(Settings(_env_file=None, elevenlabs_api_key=KEY, elevenlabs_voice_en="v"))
    for status, word in ((401, "refused"), (429, "quota"), (402, "quota"), (500, "error")):
        respx.post("https://api.elevenlabs.io/v1/text-to-speech/v").mock(return_value=httpx.Response(status))
        with pytest.raises(TTSUnavailable, match=word) as e:
            tts.synthesize("Hi.", "en", tmp_path / "o.wav")
        assert KEY not in str(e.value)
    respx.post("https://api.elevenlabs.io/v1/text-to-speech/v").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TTSUnavailable, match="reached"):
        tts.synthesize("Hi.", "en", tmp_path / "o.wav")
    with pytest.raises(TTSUnavailable, match="ELEVENLABS_VOICE_UR"):
        tts.synthesize("سلام", "ur", tmp_path / "o.wav")
    respx.post("https://api.elevenlabs.io/v1/text-to-speech/v").mock(return_value=httpx.Response(200, content=b"not audio"))
    with pytest.raises(TTSUnavailable, match="could not be read"):
        tts.synthesize("Hi.", "en", tmp_path / "o.wav")


@respx.mock
def test_heygen_lists_uploads_generates_polls_and_downloads(tmp_path):
    respx.get("https://api.heygen.com/v2/avatars").mock(return_value=httpx.Response(200, json={"data": {"avatars": [
        {"avatar_id": "a1", "avatar_name": "Anna", "preview_image_url": "https://img.example/a1.png"}, {"avatar_name": "no id"}]}}))
    respx.get("https://img.example/a1.png").mock(return_value=httpx.Response(200, content=b"\x89PNG"))
    up = respx.post("https://upload.heygen.com/v1/asset").mock(return_value=httpx.Response(200, json={"data": {"id": "asset9"}}))
    gen = respx.post("https://api.heygen.com/v2/video/generate").mock(return_value=httpx.Response(200, json={"data": {"video_id": "vid7"}}))
    status = respx.get("https://api.heygen.com/v1/video_status.get").mock(side_effect=[
        httpx.Response(200, json={"data": {"status": "processing"}}),
        httpx.Response(200, json={"data": {"status": "completed", "video_url": "https://cdn.example/v.mp4?sig=1"}})])
    dl = respx.get("https://cdn.example/v.mp4").mock(return_value=httpx.Response(200, content=b"VIDEO"))
    h = HeygenAvatars(KEY, poll_s=0.01)
    assert [(a.id, a.name) for a in h.avatars()] == [("a1", "Anna")]
    assert h.thumbnail("a1") == b"\x89PNG"
    seen = []
    out = h.render("a1", wav(tmp_path), tmp_path / "o.mp4", seen.append)
    assert out.read_bytes() == b"VIDEO" and status.call_count == 2 and seen
    assert up.calls[0].request.headers["x-api-key"] == KEY and up.calls[0].request.headers["content-type"] == "audio/mpeg"
    body = json.loads(gen.calls[0].request.content)["video_inputs"][0]
    assert body["character"]["avatar_id"] == "a1" and body["voice"]["audio_asset_id"] == "asset9" and body["background"]["value"] == "#00ff00"
    assert "x-api-key" not in dl.calls[0].request.headers                              # the signed download address never receives the key


@respx.mock
def test_heygen_failures_are_explained(tmp_path):
    respx.post("https://upload.heygen.com/v1/asset").mock(return_value=httpx.Response(401))
    with pytest.raises(AvatarUnavailable, match="refused the key"):
        HeygenAvatars(KEY).render("a1", wav(tmp_path), tmp_path / "o.mp4")
    respx.post("https://upload.heygen.com/v1/asset").mock(return_value=httpx.Response(200, json={"data": {"id": "x"}}))
    respx.post("https://api.heygen.com/v2/video/generate").mock(return_value=httpx.Response(200, json={"data": {"video_id": "v"}}))
    respx.get("https://api.heygen.com/v1/video_status.get").mock(return_value=httpx.Response(200, json={"data": {"status": "failed"}}))
    with pytest.raises(AvatarUnavailable, match="could not make"):
        HeygenAvatars(KEY, poll_s=0.01).render("a1", wav(tmp_path), tmp_path / "o.mp4")
    respx.get("https://api.heygen.com/v1/video_status.get").mock(return_value=httpx.Response(200, json={"data": {"status": "processing"}}))
    with pytest.raises(AvatarUnavailable, match="too long"):
        HeygenAvatars(KEY, poll_s=0.01, timeout_s=0.05).render("a1", wav(tmp_path), tmp_path / "o.mp4")
    assert create_avatar_renderer(Settings(_env_file=None, avatar_renderer="heygen", heygen_api_key=KEY)).paid is True
