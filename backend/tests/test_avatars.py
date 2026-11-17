import subprocess
from pathlib import Path

import httpx
import numpy as np
import pytest
import respx

from app.config import Settings
from app.media import ffmpeg  # noqa: F401  (puts the bundled ffmpeg on PATH)
from app.providers.avatar_renderer import AvatarUnavailable, create_avatar_renderer
from app.providers.avatar_renderer.remote import RemoteAvatars
from app.providers.avatar_renderer.simple import CHARACTERS, SimpleAvatars, blink_frames, draw, loudness, mouth_levels


def speech_like(tmp_path):
    """1 s silence, 1 s of tone bursts, 1 s silence."""
    p = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1", "-f", "lavfi", "-i", "sine=frequency=200:duration=1:sample_rate=16000",
                    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(p)], check=True)
    return p


def test_the_mouth_is_closed_in_silence_and_open_while_there_is_sound(tmp_path):
    env = loudness(speech_like(tmp_path))
    assert 88 <= len(env) <= 91
    m = mouth_levels(env)
    assert set(m[:25]) == {0} and set(m[-25:]) == {0}                 # silence: closed
    assert max(m[35:55]) >= 2                                          # sound: open


def test_the_mouth_does_not_flutter():
    m = mouth_levels(np.array([0.0, 0.9, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9]))
    changes = sum(1 for a, b in zip(m, m[1:]) if a != b)
    assert changes <= 4                                                # a shape is held at least two frames


def test_blinks_are_regular_deterministic_and_short():
    b = blink_frames(900)
    assert b == blink_frames(900) and 4 <= len(b) <= 60
    runs = [len(r) for r in np.split(sorted(b), np.where(np.diff(sorted(b)) > 1)[0] + 1)]
    assert set(runs) <= {4}


def test_every_character_has_a_green_background_and_distinct_mouths():
    for ch in CHARACTERS.values():
        shut, open_ = draw(ch, 0, False, 0), draw(ch, 3, False, 0)
        assert shut.getpixel((3, 3)) == (0, 255, 0) and open_.getpixel((3, 3)) == (0, 255, 0)   # corners are the key colour
        assert list(shut.getdata()) != list(open_.getdata())
        assert list(draw(ch, 1, True, 0).getdata()) != list(draw(ch, 1, False, 0).getdata())    # blinking changes the eyes


def test_the_video_is_as_long_as_the_audio_and_the_mouth_moves(tmp_path):
    audio = speech_like(tmp_path)
    out = SimpleAvatars().render("ali", audio, tmp_path / "ali.mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
    assert abs(dur - 3.0) < 0.1
    frame = lambda t: subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout  # noqa: E731
    assert frame(0.5) != frame(1.5)                                    # silence vs speech


def test_unknown_avatars_and_unreadable_audio_are_reported(tmp_path):
    with pytest.raises(AvatarUnavailable, match="nobody"):
        SimpleAvatars().render("nobody", tmp_path / "x.wav", tmp_path / "o.mp4")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(AvatarUnavailable, match="audio"):
        SimpleAvatars().render("sara", bad, tmp_path / "o.mp4")


def test_none_and_remote_providers(tmp_path):
    assert create_avatar_renderer(Settings(_env_file=None, avatar_renderer="none")).avatars() == []
    with pytest.raises(AvatarUnavailable):
        create_avatar_renderer(Settings(_env_file=None, avatar_renderer="none")).render("x", tmp_path / "a.wav", tmp_path / "o.mp4")
    assert [a.id for a in create_avatar_renderer(Settings(_env_file=None)).avatars()] == ["sara", "ali", "nomi"]
    assert RemoteAvatars("", "").avatars() == []                       # not configured: an empty list, not a crash


@respx.mock
def test_the_remote_protocol(tmp_path):
    respx.get("http://gpu:9000/avatars").mock(return_value=httpx.Response(200, json=[{"id": "anna", "name": "Anna"}]))
    respx.get("http://gpu:9000/avatars/anna/thumb").mock(return_value=httpx.Response(200, content=b"\x89PNG"))
    route = respx.post("http://gpu:9000/render").mock(return_value=httpx.Response(200, content=b"VIDEO"))
    r = RemoteAvatars("http://gpu:9000/", "secret")
    assert [(a.id, a.name) for a in r.avatars()] == [("anna", "Anna")]
    assert r.thumbnail("anna") == b"\x89PNG"
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    out = r.render("anna", audio, tmp_path / "o.mp4")
    assert out.read_bytes() == b"VIDEO" and route.calls[0].request.headers["authorization"] == "Bearer secret"
    respx.post("http://gpu:9000/render").mock(return_value=httpx.Response(500))
    with pytest.raises(AvatarUnavailable, match="500"):
        r.render("anna", audio, tmp_path / "o2.mp4")
    respx.post("http://gpu:9000/render").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(AvatarUnavailable, match="could not be reached"):
        r.render("anna", audio, tmp_path / "o3.mp4")
