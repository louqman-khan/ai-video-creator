import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from app.media import derive, ingest
from app.media.ingest import Limits, MediaRejected

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
LIM = Limits()


def sh(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def probe_json(path, *entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=" + ",".join(entries), "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    v = ["-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=4"]
    a = ["-f", "lavfi", "-i", "sine=frequency=440:duration=4"]
    sh(*v, *a, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "normal.mp4"))
    sh(*v, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "noaudio.mp4"))
    # variable frame rate: frames dropped but the original timestamps kept
    sh("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=6", "-vf", "select='lt(mod(n,5),2)'", "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "vfr.mp4"))
    sh("-display_rotation:v", "90", "-i", str(d / "normal.mp4"), "-c", "copy", str(d / "rotated.mp4"))
    sh(*v, "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", str(d / "hevc.mp4"))
    sh(*v, "-vf", "format=yuv420p10le", "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020", "-color_trc", "smpte2084",
       "-colorspace", "bt2020nc", "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=none", "-tag:v", "hvc1", str(d / "hdr.mp4"))
    sh(*v, *a, "-c:v", "libvpx-vp9", "-b:v", "200k", "-c:a", "libopus", "-shortest", str(d / "clip.webm"))
    sh(*a, "-c:a", "libmp3lame", str(d / "tone.mp3"))
    sh(*a, str(d / "tone.wav"))
    sh(*a, "-c:a", "aac", str(d / "tone.m4a"))
    sh("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-af", "volume=4", str(d / "half.wav"))  # sine defaults to 0.125: x4 = 0.5
    sh("-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "2", str(d / "silence.wav"))
    sh("-f", "lavfi", "-i", "testsrc=s=320x180", "-frames:v", "1", str(d / "pic.png"))
    sh("-f", "lavfi", "-i", "testsrc=s=320x180", "-frames:v", "1", str(d / "pic.jpg"))
    sh("-f", "lavfi", "-i", "testsrc=s=320x180", "-frames:v", "1", str(d / "pic.webp"))
    sh("-f", "lavfi", "-i", "color=c=red@0.5:s=64x64,format=rgba", "-frames:v", "1", str(d / "alpha.png"))
    sh("-i", str(d / "tone.wav"), "-i", str(d / "pic.jpg"), "-map", "0", "-map", "1", "-c:a", "libmp3lame", "-c:v", "copy", str(d / "cover.mp3"))
    sh("-f", "lavfi", "-i", "testsrc=s=17000x16", "-frames:v", "1", str(d / "wide.png"))
    sh("-f", "lavfi", "-i", "testsrc=s=64x64:r=300:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "fast.mp4"))
    return d


# ------------------------------------------------------------------ sniffing

@pytest.mark.parametrize("name,ext", [
    ("normal.mp4", "mp4"), ("clip.webm", "mkv"), ("tone.mp3", "mp3"), ("tone.wav", "wav"), ("tone.m4a", "mp4"),
    ("pic.png", "png"), ("pic.jpg", "jpg"), ("pic.webp", "webp"), ("cover.mp3", "mp3"), ("rotated.mp4", "mp4"),
])
def test_files_are_recognised_by_content_not_by_name(media, tmp_path, name, ext):
    disguised = tmp_path / "whatever.txt"  # the name is irrelevant
    disguised.write_bytes((media / name).read_bytes())
    assert ingest.sniff(disguised)[0] == ext


def test_unsupported_and_disguised_files_are_not_recognised(tmp_path):
    cases = {
        "playlist.mp4": "#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n",
        "concat.mp4": "ffconcat version 1.0\nfile '/etc/hosts'\n",
        "sdp.mp4": "v=0\nm=video 9 RTP/AVP 96\n",
        "text.png": "hello",
        "page.jpg": "<html></html>",
        "empty.wav": "",
    }
    for name, body in cases.items():
        f = tmp_path / name
        f.write_text(body)
        assert ingest.sniff(f) is None, name
    z = tmp_path / "a.mp4"
    z.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    assert ingest.sniff(z) is None
    assert ingest.sniff(tmp_path / "missing.mp4") is None


def test_disguised_playlist_causes_no_network_request(tmp_path):
    """Regression guard for the bundled ffmpeg: a playlist posing as a video must never make us fetch a URL."""
    hits: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path); self.send_response(404); self.end_headers()
        do_HEAD = do_GET
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        f = tmp_path / "video.mp4"
        f.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:{srv.server_port}/seg.ts\n#EXT-X-ENDLIST\n")
        with pytest.raises(MediaRejected):
            ingest.inspect_file(f, LIM)
        with pytest.raises(MediaRejected):  # even if the signature check were bypassed, probing must not fetch
            ingest.probe(f)
    finally:
        srv.shutdown()
    assert hits == []


# ------------------------------------------------------------------ probing

def test_probe_normal_video(media):
    i = ingest.probe(media / "normal.mp4")
    assert (i.kind, i.width, i.height, i.has_audio, i.rotation, i.vfr, i.hdr) == ("video", 320, 180, True, 0, False, False)
    assert round(i.fps) == 30 and 3.9 < i.duration < 4.2 and i.video_codec == "h264" and i.audio_rate == 44100


def test_probe_detects_variable_frame_rate_rotation_hdr(media):
    assert ingest.probe(media / "vfr.mp4").vfr is True
    r = ingest.probe(media / "rotated.mp4")
    assert r.rotation in (90, 270) and (r.width, r.height) == (180, 320)       # displayed upright: portrait
    assert ingest.probe(media / "hdr.mp4").hdr is True
    assert ingest.probe(media / "hevc.mp4").video_codec == "hevc"
    assert ingest.probe(media / "clip.webm").has_audio is True


def test_probe_audio_images_and_cover_art(media):
    for name in ("tone.mp3", "tone.wav", "tone.m4a", "silence.wav"):
        i = ingest.probe(media / name, "audio")
        assert (i.kind, i.has_audio, i.width) == ("audio", True, 0) and i.duration > 1, name
    c = ingest.probe(media / "cover.mp3", "audio")
    assert c.kind == "audio"                                  # embedded cover art is not video
    for name in ("pic.png", "pic.jpg", "pic.webp"):
        i = ingest.probe(media / name, "image")
        assert (i.kind, i.width, i.height, i.duration, i.has_audio) == ("image", 320, 180, None, False), name
    assert ingest.probe(media / "alpha.png", "image").alpha is True and ingest.probe(media / "pic.png", "image").alpha is False
    assert ingest.probe(media / "noaudio.mp4").has_audio is False


def test_limits_have_clear_messages(media):
    with pytest.raises(MediaRejected, match="longer than"):
        ingest.inspect_file(media / "normal.mp4", Limits(max_minutes=0.01))
    with pytest.raises(MediaRejected, match="16384"):
        ingest.inspect_file(media / "wide.png", LIM)
    with pytest.raises(MediaRejected, match="megapixels"):
        ingest.inspect_file(media / "pic.png", Limits(max_megapixels=0))
    with pytest.raises(MediaRejected, match="frame rate"):
        ingest.inspect_file(media / "fast.mp4", Limits(max_fps=120))
    ext, info = ingest.inspect_file(media / "normal.mp4", LIM)
    assert ext == "mp4" and info.kind == "video"
    with pytest.raises(MediaRejected, match="not a supported file"):
        ingest.inspect_file(media / "missing.bin", LIM)


def test_truncated_file_with_a_valid_header_is_rejected_by_probe(media, tmp_path):
    f = tmp_path / "cut.mp4"
    f.write_bytes((media / "normal.mp4").read_bytes()[:64])
    assert ingest.sniff(f) is not None
    with pytest.raises(MediaRejected):
        ingest.inspect_file(f, LIM)


# ------------------------------------------------------------------ derived files

def derived(media, name, tmp_path, family=None):
    info = ingest.probe(media / name, family)
    out = tmp_path / name
    files = derive.derive_all(media / name, info, out)
    return info, out, files


def keyframes(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.split()
    return [float(x.strip(",")) for x in out]


def test_video_proxy_is_constant_rate_with_a_keyframe_every_half_second(media, tmp_path):
    info, out, files = derived(media, "normal.mp4", tmp_path)
    assert set(files) == {"proxy", "film", "film_meta", "audio", "peaks"}
    p = probe_json(out / "proxy.mp4", "width", "height", "r_frame_rate", "avg_frame_rate", "pix_fmt", "codec_name")
    assert (p["width"], p["height"], p["codec_name"], p["pix_fmt"]) == (320, 180, "h264", "yuv420p")  # never upscaled: fits inside 960x540
    assert p["r_frame_rate"] == p["avg_frame_rate"] == "30/1"
    keys = keyframes(out / "proxy.mp4")
    gaps = [b - a for a, b in zip(keys, keys[1:])]
    assert keys[0] == 0 and max(gaps) <= 0.51 and len(keys) >= 7           # 4 s at one keyframe per 0.5 s


def test_variable_frame_rate_becomes_constant(media, tmp_path):
    info, out, _ = derived(media, "vfr.mp4", tmp_path)
    assert info.vfr is True
    p = probe_json(out / "proxy.mp4", "r_frame_rate", "avg_frame_rate")
    assert p["r_frame_rate"] == p["avg_frame_rate"] == "30/1"


def test_rotation_is_baked_into_the_proxy(media, tmp_path):
    info, out, _ = derived(media, "rotated.mp4", tmp_path)
    p = probe_json(out / "proxy.mp4", "width", "height")
    assert (p["width"], p["height"]) == (180, 320)                          # upright portrait
    side = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream_side_data=rotation", "-of", "csv=p=0",
                           str(out / "proxy.mp4")], capture_output=True, text=True).stdout.strip()
    assert side in ("", "0", "0.0")                                         # and no rotation flag left to apply twice


def test_hdr_is_tone_mapped_to_sdr_in_the_proxy(media, tmp_path):
    info, out, _ = derived(media, "hdr.mp4", tmp_path)
    assert info.hdr is True
    p = probe_json(out / "proxy.mp4", "pix_fmt", "color_transfer")
    assert p["pix_fmt"] == "yuv420p" and p.get("color_transfer") not in ("smpte2084", "arib-std-b67")


def test_large_sources_are_reduced_to_the_box_and_portrait_gets_a_portrait_box(media, tmp_path):
    big = tmp_path / "big.mp4"
    sh("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(big))
    info = ingest.probe(big)
    out = tmp_path / "bigproxy"
    derive.derive_all(big, info, out)
    assert (lambda p: (p["width"], p["height"]))(probe_json(out / "proxy.mp4", "width", "height")) == (960, 540)
    tall = tmp_path / "tall.mp4"
    sh("-f", "lavfi", "-i", "testsrc=s=1080x1920:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tall))
    out2 = tmp_path / "tallproxy"
    derive.derive_all(tall, ingest.probe(tall), out2)
    assert (lambda p: (p["width"], p["height"]))(probe_json(out2 / "proxy.mp4", "width", "height")) == (540, 960)


def test_other_video_codecs_and_no_audio(media, tmp_path):
    for name in ("hevc.mp4", "clip.webm"):
        info, out, files = derived(media, name, tmp_path)
        assert probe_json(out / "proxy.mp4", "codec_name")["codec_name"] == "h264", name
    info, out, files = derived(media, "noaudio.mp4", tmp_path)
    assert "audio" not in files and "peaks" not in files and not (out / "proxy_audio.m4a").exists()


def test_audio_proxy_and_waveform(media, tmp_path):
    info, out, files = derived(media, "half.wav", tmp_path, "audio")
    assert set(files) == {"audio", "peaks"}
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,channels,sample_rate", "-of", "csv=p=0",
                        str(out / "proxy_audio.m4a")], capture_output=True, text=True).stdout.strip()
    assert a == "aac,48000,2"  # codec, sample rate, channels (ffprobe's own order)
    peaks = json.loads((out / "peaks.json").read_text())
    fine, coarse = peaks["rates"]["100"], peaks["rates"]["10"]
    assert abs(len(fine) - 300) <= 2 and abs(len(coarse) - 30) <= 2          # 3 s: 100 and 10 peaks per second
    mid = sorted(fine[10:-10])[len(fine[10:-10]) // 2]
    assert 120 <= mid <= 134                                                  # amplitude 0.5 -> about 127 of 255
    assert max(fine) <= 255 and max(coarse) >= max(fine) - 3


def test_silence_has_flat_peaks_and_cover_art_mp3_works(media, tmp_path):
    info, out, files = derived(media, "silence.wav", tmp_path, "audio")
    assert max(json.loads((out / "peaks.json").read_text())["rates"]["100"]) == 0
    info, out, files = derived(media, "cover.mp3", tmp_path, "audio")
    assert set(files) == {"audio", "peaks"}                                   # the cover picture is ignored


def test_filmstrip_layout_and_sprite(media, tmp_path):
    info, out, files = derived(media, "normal.mp4", tmp_path)
    meta = json.loads((out / "film.json").read_text())
    assert (meta["thumb_width"], meta["thumb_height"]) == (160, 90) and meta["interval"] == 0.5
    w = probe_json(out / "film.jpg", "width", "height")
    assert w["height"] == 90 and w["width"] == meta["count"] * 160 and meta["count"] == 9
    # long media never gets more than ~120 thumbnails
    for minutes in (1, 10, 30):
        interval, count = derive.film_layout(minutes * 60)
        assert count <= 122 and interval >= 0.5
    assert derive.film_layout(0.2) == (0.5, 1)


def test_image_proxies(media, tmp_path):
    info, out, files = derived(media, "pic.png", tmp_path, "image")
    assert files == {"proxy": "proxy.jpg"} and probe_json(out / "proxy.jpg", "width")["width"] == 320
    info, out, files = derived(media, "alpha.png", tmp_path, "image")
    assert files == {"proxy": "proxy.png"}                                    # transparency is kept
    big = tmp_path / "big.png"
    sh("-f", "lavfi", "-i", "testsrc=s=3000x2000", "-frames:v", "1", str(big))
    bi, bo = ingest.probe(big, "image"), tmp_path / "bigout"
    derive.derive_all(big, bi, bo)
    assert probe_json(bo / "proxy.jpg", "width")["width"] == 1280             # downscaled


def test_asset_key_changes_when_the_file_changes(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"1")
    k1 = derive.asset_key(f)
    assert derive.asset_key(f) == k1
    f.write_bytes(b"22")
    assert derive.asset_key(f) != k1
