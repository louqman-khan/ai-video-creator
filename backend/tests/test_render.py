import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.media import loudness
from app.pipeline import assemble
from app.timeline import render
from app.timeline.models import Asset, ChromaKey, Clip, Effect, Timeline, Track, Transform
from app.timeline.render import RenderUnsupported, plan_segments, render_timeline, segment_key, unsupported_features

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
SETTINGS = Settings(_env_file=None)
FPS = 30


def sh(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def avg_rgb(path, t):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return tuple(out[:3])


def probe(path, entries, stream="v:0"):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries, "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return out


def ssim(a, b):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"All:([0-9.]+)", p.stderr).group(1))


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("render_media")
    for name, color in (("red", "red"), ("green", "lime"), ("blue", "blue")):
        sh("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / f"{name}.mp4"))
    sh("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "moving.mp4"))   # 1 s: 30 frames
    sh("-f", "lavfi", "-i", "testsrc=s=640x360", "-frames:v", "1", str(d / "pic.png"))
    sh("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-ac", "1", str(d / "tone.wav"))
    sh("-f", "lavfi", "-i", "sine=frequency=880:duration=6", "-ac", "1", str(d / "music.wav"))
    (d / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)        # right signature, undecodable
    return d


def asset(media, name, kind, frames=None):
    ext = {"video": "mp4", "image": "png", "audio": "wav"}[kind]
    return Asset(id=name, kind=kind, path=str(media / f"{name}.{ext}"), duration=frames, license="User-provided")


def make_tl(media, clips, tracks=None, extra_assets=(), caption_style=None):
    assets = {a.id: a for a in [asset(media, "red", "video", 120), asset(media, "green", "video", 120), asset(media, "blue", "video", 120),
                                asset(media, "moving", "video", 30), asset(media, "pic", "image"),
                                asset(media, "tone", "audio", 180), asset(media, "music", "audio", 180), *extra_assets]}
    tracks = tracks or [Track(id="V1", kind="video"), Track(id="V2", kind="video"), Track(id="A1", kind="audio"), Track(id="A2", kind="audio"),
                        Track(id="C1", kind="caption")]
    return Timeline(fps=FPS, aspect="16:9", tracks=tracks, clips=clips, assets=assets, caption_style=caption_style, meta={"language": "en"})


def vclip(id, asset_id, start, dur, track="V1", kind="video", **kw):
    return Clip(id=id, track=track, kind=kind, asset=asset_id, start=start, duration=dur, **kw)


# ------------------------------------------------------------------ planning

def test_segments_follow_clip_edges_and_gaps_become_black(media):
    tl = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "blue", 45, 30)])
    segs = plan_segments(tl)
    assert [(s.start, s.end, [c.id for c in s.layers]) for s in segs] == [(0, 30, ["a"]), (30, 45, []), (45, 75, ["b"])]
    assert sum(s.frames for s in segs) == tl.duration == 75


def test_layers_are_ordered_by_track_and_split_where_the_visible_set_changes(media):
    tl = make_tl(media, [vclip("bottom", "red", 0, 90), vclip("top", "green", 30, 30, track="V2")])
    segs = plan_segments(tl)
    assert [(s.start, s.end, [c.id for c in s.layers]) for s in segs] == [(0, 30, ["bottom"]), (30, 60, ["bottom", "top"]), (60, 90, ["bottom"])]
    tl2 = make_tl(media, [vclip("bottom", "red", 0, 90), vclip("top", "green", 30, 30, track="V2")],
                  tracks=[Track(id="V1", kind="video"), Track(id="V2", kind="video", muted=True), Track(id="A1", kind="audio")])
    assert [[c.id for c in s.layers] for s in plan_segments(tl2)] == [["bottom"]]      # a muted video track is hidden, no pointless split


def test_audio_only_timelines_get_one_black_segment(media):
    tl = make_tl(media, [Clip(id="n", track="A1", kind="audio", asset="tone", start=0, duration=60)])
    assert [(s.start, s.end, s.layers) for s in plan_segments(tl)] == [(0, 60, ())]


# ------------------------------------------------------------------ what is refused

def test_unsupported_features_are_named_not_ignored(media):
    ok = make_tl(media, [vclip("i", "pic", 0, 30, kind="image", effects=[Effect(type="kenburns", value=10), Effect(type="blur", value=20)],
                               transform=Transform(opacity=0.5), fade_in=5),
                         vclip("v", "red", 30, 30, transition_in={"type": "crossfade", "duration": 10}, effects=[Effect(type="contrast", value=30)])])
    assert unsupported_features(ok) == []
    bad = make_tl(media, [
        vclip("kb", "red", 30, 30, effects=[Effect(type="kenburns", value=5)]),
        Clip(id="au", track="A1", kind="audio", asset="tone", start=0, duration=30, effects=[Effect(type="blur", value=5)]),
    ])
    msg = " | ".join(unsupported_features(bad))
    for word in ("zoom on video", "effects or transitions on audio"):
        assert word in msg


def test_render_refuses_before_doing_any_work(media, tmp_path):
    tl = make_tl(media, [vclip("fx", "red", 0, 30, effects=[Effect(type="kenburns", value=5)])])
    with pytest.raises(RenderUnsupported, match="zoom on video"):
        render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=tmp_path / "o.mp4")
    assert not (tmp_path / "tl_segments_preview").exists()
    with pytest.raises(ValueError, match="empty"):
        render_timeline(make_tl(media, []), tmp_path, SETTINGS, quality="preview", out=tmp_path / "o.mp4")


# ------------------------------------------------------------------ cache keys

def test_segment_keys_depend_only_on_what_is_visible_in_the_segment(media):
    base = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "blue", 30, 30)])
    seg_a, seg_b = plan_segments(base)
    k = lambda tl, s, w=960, h=540, p=assemble.PREVIEW: segment_key(tl, s, w, h, p)  # noqa: E731
    assert k(base, seg_a) == k(base, seg_a)
    # changing the OTHER clip leaves this segment's key alone (that is the whole point of the cache)
    changed = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "green", 30, 30)])
    assert k(changed, plan_segments(changed)[0]) == k(base, seg_a) and k(changed, plan_segments(changed)[1]) != k(base, seg_b)
    # ids are labels: renaming a clip changes no pixel
    renamed = make_tl(media, [vclip("zzz", "red", 0, 30), vclip("b", "blue", 30, 30)])
    assert k(renamed, plan_segments(renamed)[0]) == k(base, seg_a)
    # things that do change the pixels
    assert k(base, seg_a, 1920, 1080, assemble.FINAL) != k(base, seg_a)
    assert k(base, seg_a, 540, 960) != k(base, seg_a)
    in_pt = make_tl(media, [vclip("a", "red", 0, 30, in_point=10), vclip("b", "blue", 30, 30)])
    assert k(in_pt, plan_segments(in_pt)[0]) != k(base, seg_a)
    op = make_tl(media, [vclip("a", "red", 0, 30, transform=Transform(opacity=0.5)), vclip("b", "blue", 30, 30)])
    assert k(op, plan_segments(op)[0]) != k(base, seg_a)
    # the same file changed on disk invalidates it
    f = media / "red.mp4"
    before = k(base, seg_a)
    st = f.stat()
    import os
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    try:
        assert k(base, seg_a) != before
    finally:
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert FINAL_FAST_KEY(base, seg_a) != k(base, seg_a, 960, 540, assemble.PREVIEW)


def FINAL_FAST_KEY(tl, seg):
    return segment_key(tl, seg, 960, 540, assemble.FINAL_FAST)


# ------------------------------------------------------------------ real renders

def test_cuts_gaps_and_stacked_layers_have_the_right_pixels(media, tmp_path):
    tl = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "blue", 45, 45),
                         vclip("half", "green", 60, 30, track="V2", transform=Transform(opacity=0.5))])
    out = tmp_path / "out.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=out, captions=False, normalize=False)
    assert probe(out, "stream=width,height") == "960,540" and probe(out, "stream=nb_frames") == "90"
    assert abs(float(probe(out, "format=duration", stream="v:0")) - 3.0) < 0.05
    r, g, b = avg_rgb(out, 0.5)
    assert r > 200 and g < 60 and b < 60                           # red
    assert sum(avg_rgb(out, 1.2)) < 60                              # the gap is black
    r, g, b = avg_rgb(out, 1.7)
    assert b > 200 and r < 60                                       # blue
    r, g, b = avg_rgb(out, 2.5)                                     # 50 % green over blue
    assert 80 < g < 180 and 80 < b < 180 and r < 60


def frame_ssim(a, b, log):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(a), "-i", str(b), "-lavfi", f"ssim=stats_file={log}", "-f", "null", "-"], check=True)
    return [float(re.search(r"All:([0-9.]+)", line).group(1)) for line in open(log)]


def test_clip_relative_time_survives_cutting_a_clip_into_segments(media):
    kb = [Effect(type="kenburns", value=20)]
    tl = make_tl(media, [vclip("img", "pic", 0, 90, kind="image", effects=kb), vclip("mv", "moving", 90, 90, kind="video", loop=True, in_point=0),
                         vclip("g1", "red", 33, 20, track="V2"), vclip("g2", "red", 100, 25, track="V2")])
    segs = {(s.start, s.end): s for s in plan_segments(tl)}
    by_id = lambda s, cid: next(c for c in s.layers if c.id == cid)  # noqa: E731
    # the zoom always runs over the WHOLE clip: each segment only says how far into it the segment starts
    assert render._layer_spec(tl, segs[(0, 33)], by_id(segs[(0, 33)], "img"))["kb"] == [20, 0, 90]
    assert render._layer_spec(tl, segs[(33, 53)], by_id(segs[(33, 53)], "img"))["kb"] == [20, 33, 90]
    assert render._layer_spec(tl, segs[(53, 90)], by_id(segs[(53, 90)], "img"))["kb"] == [20, 53, 90]
    # a looping 30-frame video continues where it left off, wrapping around its own length
    assert render._layer_spec(tl, segs[(90, 100)], by_id(segs[(90, 100)], "mv"))["offset"] == 0
    assert render._layer_spec(tl, segs[(100, 125)], by_id(segs[(100, 125)], "mv"))["offset"] == 10
    assert render._layer_spec(tl, segs[(125, 180)], by_id(segs[(125, 180)], "mv"))["offset"] == 5      # 35 frames in -> 35 % 30


def test_whole_and_split_renders_show_the_same_pictures(media, tmp_path):
    """Cutting a clip into segments (because another layer starts/stops) must not change its pixels."""
    kb = [Effect(type="kenburns", value=20)]
    whole = make_tl(media, [vclip("img", "pic", 0, 90, kind="image", effects=kb), vclip("mv", "moving", 90, 90, kind="video", loop=True)])
    split = make_tl(media, [vclip("img", "pic", 0, 90, kind="image", effects=kb), vclip("mv", "moving", 90, 90, kind="video", loop=True),
                            vclip("ghost1", "red", 33, 20, track="V2", transform=Transform(opacity=0)),   # invisible, but cuts the segments
                            vclip("ghost2", "red", 100, 25, track="V2", transform=Transform(opacity=0))])
    covered = set(range(33, 53)) | set(range(100, 125))                                                   # frames with an overlay in the graph
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    # near-lossless encoding, so that any difference left is a difference in the pictures and not encoder noise
    exact = assemble.RenderProfile("test-exact", "ultrafast", 1, "ultrafast", 1, "96k")
    render_timeline(whole, a, SETTINGS, quality="preview", out=a / "o.mp4", captions=False, normalize=False, profile=exact)
    render_timeline(split, b, SETTINGS, quality="preview", out=b / "o.mp4", captions=False, normalize=False, profile=exact)
    assert probe(a / "o.mp4", "stream=nb_frames") == probe(b / "o.mp4", "stream=nb_frames") == "180"
    per_frame = frame_ssim(a / "o.mp4", b / "o.mp4", tmp_path / "s.log")
    plain = [v for i, v in enumerate(per_frame) if i not in covered]
    through_overlay = [v for i, v in enumerate(per_frame) if i in covered]
    # everywhere without an overlay (including the first frames after each cut) the pictures are the same ...
    assert min(plain) > 0.9995, [i for i, v in enumerate(per_frame) if i not in covered and v <= 0.9995]
    # ... compositing through a fully transparent layer is not bit-exact (colour-format conversion) but is visually the same
    assert min(through_overlay) > 0.97


def test_editing_one_clip_rerenders_only_its_segments(media, tmp_path):
    def files():
        return {p.name: p.stat().st_mtime_ns for p in (tmp_path / "tl_segments_preview").glob("seg_*.mp4")}

    tl = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "blue", 30, 30), vclip("c", "green", 60, 30)])
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=tmp_path / "o.mp4", captions=False, normalize=False)
    first = files()
    assert len(first) == 3
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=tmp_path / "o.mp4", captions=False, normalize=False)
    assert files() == first                                          # nothing changed: nothing re-rendered
    tl2 = make_tl(media, [vclip("a", "red", 0, 30), vclip("b", "blue", 30, 30, in_point=20), vclip("c", "green", 60, 30)])
    render_timeline(tl2, tmp_path, SETTINGS, quality="preview", out=tmp_path / "o.mp4", captions=False, normalize=False)
    second = files()
    assert len(second) == 3
    kept = set(first) & set(second)
    assert len(kept) == 2 and all(first[n] == second[n] for n in kept)   # the untouched two are the very same files
    assert set(first) - set(second) and set(second) - set(first)         # one replaced, the stale one removed


def test_a_clip_that_cannot_be_decoded_becomes_black_instead_of_failing_the_render(media, tmp_path):
    broken = Asset(id="broken", kind="image", path=str(media / "broken.png"), license="L")
    tl = make_tl(media, [vclip("ok", "red", 0, 30), vclip("bad", "broken", 30, 30, kind="image"), vclip("ok2", "blue", 60, 30)],
                 extra_assets=[broken])
    out = tmp_path / "o.mp4"
    started = time.time()
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=out, captions=False, normalize=False)
    assert time.time() - started < 30                      # it used to hang until the timeout: ffmpeg -loop on a broken picture never ends
    assert probe(out, "stream=nb_frames") == "90"
    assert avg_rgb(out, 0.5)[0] > 200 and sum(avg_rgb(out, 1.5)) < 60 and avg_rgb(out, 2.5)[2] > 200


# ------------------------------------------------------------------ audio

def mix_levels(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[0-9.]+) dB", p.stderr).group(1))


def band_level(path, t0, d, hz=880):
    """Mean level of one tone: a narrow band around it, so the other tone cannot interfere."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(t0), "-t", str(d), "-i", str(path), "-af",
                        f"bandpass=f={hz}:width_type=h:w=150,volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[0-9.]+|-inf) dB", p.stderr).group(1).replace("-inf", "-200"))


def test_audio_is_placed_trimmed_faded_and_mixed(media, tmp_path):
    clips = [vclip("v", "red", 0, 150),
             Clip(id="nar", track="A1", kind="audio", asset="tone", start=0, duration=150),                       # 440 Hz for 5 s
             Clip(id="mus", track="A2", kind="audio", asset="music", start=60, duration=60, volume=1.0, fade_in=10, fade_out=10)]  # 880 Hz, 2 s..4 s
    mix = render.mix_audio(make_tl(media, clips), tmp_path)
    assert abs(float(probe(mix, "format=duration", stream="a:0")) - 5.0) < 0.05          # exactly the timeline length
    assert probe(mix, "stream=sample_rate,channels", stream="a:0") == "48000,2"
    inside, before, after = band_level(mix, 2.5, 1.0), band_level(mix, 0.2, 1.0), band_level(mix, 4.3, 0.5)
    assert inside > before + 15 and inside > after + 15                                  # the 880 Hz tone exists only where it was placed
    assert band_level(mix, 0.2, 1.0, hz=440) > -40 and band_level(mix, 4.3, 0.5, hz=440) > -40   # the narration runs the whole time
    # the fade-in really fades: the first 0.1 s of the music is much quieter than its steady part
    assert band_level(mix, 2.0, 0.1) < inside - 6
    # volume: the same music at a quarter of the volume is about 12 dB lower
    quiet = render.mix_audio(make_tl(media, [*clips[:2], clips[2].model_copy(update={"volume": 0.25})]), tmp_path)
    assert abs((inside - band_level(quiet, 2.5, 1.0)) - 12.0) < 1.5


def test_muted_audio_track_is_left_out_and_no_audio_means_silence(media, tmp_path):
    tl = make_tl(media, [vclip("v", "red", 0, 60), Clip(id="nar", track="A1", kind="audio", asset="tone", start=0, duration=60)],
                 tracks=[Track(id="V1", kind="video"), Track(id="A1", kind="audio", muted=True), Track(id="C1", kind="caption")])
    mix = render.mix_audio(tl, tmp_path)
    assert abs(float(probe(mix, "format=duration", stream="a:0")) - 2.0) < 0.05
    assert mix_levels(mix) < -80                                                         # silence, but a real audio track


def test_mix_is_cached_by_content_and_normalised_to_the_target(media, tmp_path):
    tl = make_tl(media, [vclip("v", "red", 0, 90), Clip(id="nar", track="A1", kind="audio", asset="tone", start=0, duration=90, volume=0.1)])
    m1 = render.mix_audio(tl, tmp_path)
    t1 = m1.stat().st_mtime_ns
    assert render.mix_audio(tl, tmp_path) == m1 and m1.stat().st_mtime_ns == t1
    out = tmp_path / "o.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=out, captions=False, normalize=True, lufs=-16.0)
    final_audio = tmp_path / "a.flac"
    sh("-i", str(out), "-vn", "-c:a", "flac", str(final_audio))
    assert abs(float(loudness.measure(final_audio)["input_i"]) - (-16.0)) < 1.0
    tl2 = make_tl(media, [vclip("v", "red", 0, 90), Clip(id="nar", track="A1", kind="audio", asset="tone", start=0, duration=90, volume=0.5)])
    m2 = render.mix_audio(tl2, tmp_path)
    assert m2 != m1 and not m1.exists()                                                  # a changed mix replaces the old file


# ------------------------------------------------------------------ captions + encoders

def test_captions_are_burned_from_the_caption_clips(media, tmp_path):
    cap = Clip(id="c1", track="C1", kind="caption", start=30, duration=30, text="Hello world")
    with_cap = make_tl(media, [vclip("v", "red", 0, 90), cap], caption_style={"color": "#00FF00", "size_pct": 12})
    without = make_tl(media, [vclip("v", "red", 0, 90)])
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    render_timeline(with_cap, a, SETTINGS, quality="preview", out=a / "o.mp4", normalize=False)
    render_timeline(without, b, SETTINGS, quality="preview", out=b / "o.mp4", normalize=False)
    ass = (a / "captions_preview.ass").read_text()
    assert "Hello world" in ass and "0:00:01.00,0:00:02.00" in ass and "&H0000FF00" in ass     # frames -> times, style applied
    # a caption is visible while it is on, and absent before and after
    crop = lambda p, t: subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(p), "-frames:v", "1", "-vf", "scale=96:54,format=rgb24", "-f", "rawvideo", "-"],  # noqa: E731
                                       capture_output=True, check=True).stdout
    assert crop(a / "o.mp4", 1.5) != crop(b / "o.mp4", 1.5)
    assert crop(a / "o.mp4", 0.5) == crop(b / "o.mp4", 0.5) and crop(a / "o.mp4", 2.5) == crop(b / "o.mp4", 2.5)


def test_hardware_encoder_profile_works_or_falls_back(media, tmp_path, monkeypatch):
    tl = make_tl(media, [vclip("v", "red", 0, 45), Clip(id="nar", track="A1", kind="audio", asset="tone", start=0, duration=45)])
    out = tmp_path / "fast.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="final", out=out, captions=False, normalize=False, profile=assemble.FINAL_FAST)
    assert probe(out, "stream=codec_name,width,height") == "h264,1920,1080"
    monkeypatch.setattr(render.ffmpeg, "has_encoder", lambda name: False)                # e.g. a machine without VideoToolbox
    out2 = tmp_path / "soft.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="final", out=out2, captions=False, normalize=False, profile=assemble.FINAL_FAST)
    assert probe(out2, "stream=codec_name") == "h264" and out2.stat().st_size > 0


def test_picture_in_picture_has_the_right_size_and_place(media, tmp_path):
    # a green half-size window, moved a quarter of the frame to the right, over red
    tl = make_tl(media, [vclip("bg", "red", 0, 60), vclip("pip", "green", 0, 60, track="V2", transform=Transform(scale=0.5, x=0.25, y=0.0))])
    out = tmp_path / "pip.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=out, captions=False, normalize=False)
    def rgb_at(x, y):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(out), "-frames:v", "1", "-vf", f"crop=4:4:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return tuple(sum(raw[i::3]) // (len(raw) // 3) for i in range(3))
    # the window is 480 wide, centred at 480 + 0.25 * 960 = 720: x 480..960, y 135..405
    r, g, b = rgb_at(720, 270); assert g > 200 and r < 60                     # inside the window: green
    r, g, b = rgb_at(100, 270); assert r > 200 and g < 60                     # left of it: the red background
    r, g, b = rgb_at(720, 40); assert r > 200 and g < 60                      # above it: still red
    r, g, b = rgb_at(400, 270); assert r > 200 and g < 60                     # just left of its edge (x=480)
    # a window alone on the bottom layer sits on black
    solo = make_tl(media, [vclip("pip", "green", 0, 60, transform=Transform(scale=0.5))])
    out2 = tmp_path / "solo.mp4"
    render_timeline(solo, tmp_path, SETTINGS, quality="preview", out=out2, captions=False, normalize=False)
    out = out2
    assert sum(rgb_at(20, 20)) < 40 and rgb_at(480, 270)[1] > 200


def test_music_is_ducked_under_the_narration_only_on_a_ducked_track(media, tmp_path):
    clips = [vclip("v", "red", 0, 150),
             Clip(id="nar", track="A1", kind="audio", asset="tone", start=30, duration=60),                      # 440 Hz, 1 s..3 s
             Clip(id="mus", track="A2", kind="audio", asset="music", start=0, duration=150)]                      # 880 Hz, whole 5 s
    plain = render.mix_audio(make_tl(media, clips), tmp_path)
    plain_free, plain_under = band_level(plain, 4.0, 0.8), band_level(plain, 2.0, 0.8)   # measured now: the next mix replaces this file
    plain_nar = band_level(plain, 2.0, 0.8, hz=440)
    tracks = [Track(id="V1", kind="video"), Track(id="V2", kind="video"), Track(id="A1", kind="audio"), Track(id="A2", kind="audio", duck=True), Track(id="C1", kind="caption")]
    ducked = render.mix_audio(make_tl(media, clips, tracks=tracks), tmp_path)
    assert abs(float(probe(ducked, "format=duration", stream="a:0")) - 5.0) < 0.05
    free = band_level(ducked, 4.0, 0.8)                                       # after the narration: full music
    under = band_level(ducked, 2.0, 0.8)                                      # while it speaks
    assert free - under > 6                                                   # clearly lowered
    assert abs(plain_under - plain_free) < 1.5   # without ducking the music is steady
    assert band_level(ducked, 2.0, 0.8, hz=440) > plain_nar - 1.5   # the narration itself is not touched
    assert band_level(ducked, 4.0, 0.8) > plain_free - 1.5   # and the music comes back to full volume


# ------------------------------------------------------------------ transitions, fades, effects

def render_to(tl, tmp_path, name="t.mp4"):
    out = tmp_path / name
    render_timeline(tl, tmp_path, SETTINGS, quality="preview", out=out, captions=False, normalize=False)
    return out


def px(path, t, x, y):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", f"crop=4:4:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return tuple(sum(raw[i::3]) // (len(raw) // 3) for i in range(3))


def two_clips(media, kind, d=30, **kw):
    # red 2 s, then green 2 s; the transition runs over the first `d` frames of green (frames 60..90)
    return make_tl(media, [vclip("a", "red", 0, 60), vclip("b", "green", 60, 60, transition_in={"type": kind, "duration": d}, **kw)])


def test_crossfade_blends_the_outgoing_and_incoming_pictures(media, tmp_path):
    out = render_to(two_clips(media, "crossfade"), tmp_path)
    assert px(out, 0.9, 480, 270)[0] > 200                                    # before: red
    r, g, b = px(out, 2.5, 480, 270)                                         # halfway through (frame 75)
    assert 90 < r < 170 and 90 < g < 170 and b < 40
    r, g, b = px(out, 3.3, 480, 270)
    assert g > 200 and r < 40                                                 # after: green
    assert abs(float(probe(out, "format=duration", stream="v:0")) - 4.0) < 0.05   # the transition does not change the length


def test_dip_goes_through_black(media, tmp_path):
    out = render_to(two_clips(media, "dip"), tmp_path)
    assert sum(px(out, 2.5, 480, 270)) < 40                                  # the middle is black
    assert px(out, 2.2, 480, 270)[0] > 40 and px(out, 2.2, 480, 270)[1] < 40  # first half: red going dark
    assert px(out, 2.8, 480, 270)[1] > 40 and px(out, 2.8, 480, 270)[0] < 40  # second half: green coming up
    assert px(out, 3.3, 480, 270)[1] > 200


def test_slide_pushes_the_new_picture_in_from_the_right(media, tmp_path):
    out = render_to(two_clips(media, "slide"), tmp_path)
    left, right = px(out, 2.5, 100, 270), px(out, 2.5, 860, 270)
    assert left[0] > 200 and left[1] < 40                                    # the old picture is still on the left
    assert right[1] > 200 and right[0] < 40                                  # the new one covers the right half
    assert px(out, 3.3, 100, 270)[1] > 200


def test_zoom_transition_fades_in_while_settling(media, tmp_path):
    out = render_to(two_clips(media, "zoom"), tmp_path)
    r, g, b = px(out, 2.5, 480, 270)
    assert 80 < r < 180 and 80 < g < 180
    assert px(out, 3.3, 480, 270)[1] > 200 and px(out, 3.3, 20, 20)[1] > 200   # settled: the picture fills the frame again


def test_a_transition_cut_into_several_segments_is_the_same_picture(media, tmp_path):
    whole = two_clips(media, "crossfade")
    cut = two_clips(media, "crossfade").model_copy(update={"clips": [*whole.clips, vclip("pip", "blue", 70, 10, track="V2", transform=Transform(scale=0.2))]})
    out = render_to(cut, tmp_path)
    r, g, _ = px(out, 2.3, 480, 270)                                         # frame 69: p = 0.3, before the overlay appears: still on the same ramp
    assert 130 < r < 200 and 30 < g < 110


def test_a_video_that_has_run_out_is_held_under_the_transition(media, tmp_path):
    # "moving" is 1 s long; the transition starts when it ends: its last frame stays instead of failing or going black
    tl = make_tl(media, [vclip("a", "moving", 0, 30), vclip("b", "green", 30, 60, transition_in={"type": "crossfade", "duration": 20})])
    out = render_to(tl, tmp_path)
    assert sum(px(out, 1.2, 480, 270)) > 60                                   # not black halfway through
    assert px(out, 2.0, 480, 270)[1] > 200


def test_fades_on_pictures_start_from_what_is_underneath(media, tmp_path):
    tl = make_tl(media, [vclip("a", "red", 0, 90, fade_in=30, fade_out=30)])
    out = render_to(tl, tmp_path)
    assert sum(px(out, 0.0, 480, 270)) < 30                                    # starts from black
    assert 90 < px(out, 0.5, 480, 270)[0] < 170                                # half way in
    assert px(out, 1.5, 480, 270)[0] > 200
    assert 90 < px(out, 2.5, 480, 270)[0] < 170 and sum(px(out, 2.9, 480, 270)) < 60   # and out again


def test_colour_effects_and_blur_change_the_picture(media, tmp_path):
    base = render_to(make_tl(media, [vclip("a", "red", 0, 30)]), tmp_path, "base.mp4")
    gray = render_to(make_tl(media, [vclip("a", "red", 0, 30, effects=[Effect(type="saturation", value=-100)])]), tmp_path, "gray.mp4")
    r, g, b = px(gray, 0.5, 480, 270)
    assert abs(r - g) < 25 and abs(g - b) < 25 and px(base, 0.5, 480, 270)[0] > 200    # red became grey
    dark = render_to(make_tl(media, [vclip("a", "red", 0, 30, effects=[Effect(type="brightness", value=-60)])]), tmp_path, "dark.mp4")
    assert 90 < px(dark, 0.5, 480, 270)[0] < 160 and px(base, 0.5, 480, 270)[0] > 200        # 255 * (1 - 0.48) = 133
    flat = render_to(make_tl(media, [vclip("a", "red", 0, 30, effects=[Effect(type="contrast", value=-100)])]), tmp_path, "flat.mp4")
    r, g, b = px(flat, 0.5, 480, 270)
    assert abs(r - g) < 25 and abs(g - b) < 25 and 90 < r < 170                                # no contrast left: mid grey
    contrast = render_to(make_tl(media, [vclip("a", "moving", 0, 30, effects=[Effect(type="contrast", value=-80)])]), tmp_path, "contrast.mp4")
    plain = render_to(make_tl(media, [vclip("a", "moving", 0, 30)]), tmp_path, "plain.mp4")
    blurred = render_to(make_tl(media, [vclip("a", "moving", 0, 30, effects=[Effect(type="blur", value=100)])]), tmp_path, "blur.mp4")
    assert ssim(plain, contrast) < 0.9 and ssim(plain, blurred) < 0.95 and ssim(plain, plain) > 0.99


def frame_row(path, n, y=20):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{n}),crop=960:4:0:{y}", "-fps_mode", "passthrough", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return [(raw[i * 3], raw[i * 3 + 1]) for i in range(960)]


def green_edge(path, n):
    return next((i for i, (r, g) in enumerate(frame_row(path, n)) if g > 128 and r < 100), None)


def test_slide_is_frame_exact_also_when_its_segment_is_cut(media, tmp_path):
    base = two_clips(media, "slide")
    cut = base.model_copy(update={"clips": [*base.clips, vclip("pip", "blue", 70, 10, track="V2", transform=Transform(scale=0.2))]})
    for tl, name in ((base, "a.mp4"), (cut, "b.mp4")):
        out = render_to(tl, tmp_path, name)
        for n in (61, 69, 70, 75, 85):                          # the new picture's left edge is where the maths says, to within 2 pixels
            expected = round(960 * (1 - (n - 60) / 30))
            assert abs(green_edge(out, n) - expected) <= 2, (name, n, green_edge(out, n), expected)
        assert green_edge(out, 60) is None                     # the first frame of the transition shows only the old picture


# ------------------------------------------------------------------ crop, rotation, aspect ratios, reframing

def half_red_half_blue(tmp_path):
    p = tmp_path / "split.png"
    sh("-f", "lavfi", "-i", "color=c=red:s=80x180", "-f", "lavfi", "-i", "color=c=blue:s=80x180", "-filter_complex", "[0][1]hstack", "-frames:v", "1", str(p))
    return p


def test_crop_keeps_the_remaining_part_where_it_was(media, tmp_path):
    # red | blue picture, crop away the left 25 %: the red part that is left stays on the left of the blue part, the rest shows what is underneath (black)
    pic = half_red_half_blue(tmp_path)
    extra = asset(media.parent if False else tmp_path, "split", "image")
    tl = make_tl(media, [vclip("p", "split", 0, 30, kind="image", transform=Transform(crop=(0.25, 0, 0, 0)))], extra_assets=[extra])
    out = render_to(tl, tmp_path)
    assert sum(px(out, 0.5, 40, 270)) < 40                                      # the cropped-away strip is empty
    assert px(out, 0.5, 300, 270)[0] > 200 and px(out, 0.5, 700, 270)[2] > 200   # red then blue, at their old places


def test_rotation_turns_clockwise_and_leaves_the_corners_empty(media, tmp_path):
    pic = half_red_half_blue(tmp_path)
    extra = asset(tmp_path, "split", "image")
    tl = make_tl(media, [vclip("p", "split", 0, 30, kind="image", transform=Transform(rotation=90, scale=0.5))], extra_assets=[extra])
    out = render_to(tl, tmp_path)
    # turned a quarter clockwise: the left (red) half is now on top, the right (blue) half at the bottom
    assert px(out, 0.5, 480, 200)[0] > 150 and px(out, 0.5, 480, 340)[2] > 150
    assert sum(px(out, 0.5, 20, 20)) < 40                                       # outside the turned picture: black


def test_fit_shows_the_whole_picture_with_bars_and_blur_fills_them(media, tmp_path):
    pic = half_red_half_blue(tmp_path)
    extra = asset(tmp_path, "split", "image")
    sq = make_tl(media, [vclip("p", "split", 0, 30, kind="image")], extra_assets=[extra]).model_copy(update={"aspect": "16:9"})
    fill = render_to(sq, tmp_path, "fill.mp4")
    assert px(fill, 0.5, 10, 270)[0] > 200 and px(fill, 0.5, 940, 270)[2] > 200   # 8:9 picture covers the whole 16:9 frame (cropped top/bottom)
    fit = render_to(make_tl(media, [vclip("p", "split", 0, 30, kind="image", fit="fit")], extra_assets=[extra]), tmp_path, "fit.mp4")
    assert sum(px(fit, 0.5, 20, 270)) < 40 and sum(px(fit, 0.5, 940, 270)) < 40   # bars at the sides
    assert px(fit, 0.5, 400, 270)[0] > 200 and px(fit, 0.5, 560, 270)[2] > 200     # the whole picture, red | blue, in the middle
    blur = render_to(make_tl(media, [vclip("p", "split", 0, 30, kind="image", fit="blur")], extra_assets=[extra]), tmp_path, "blur.mp4")
    assert px(blur, 0.5, 20, 270)[0] > 100 and px(blur, 0.5, 940, 270)[2] > 100    # the bars are a blurred copy of the picture
    assert px(blur, 0.5, 400, 270)[0] > 200 and px(blur, 0.5, 560, 270)[2] > 200


@pytest.mark.parametrize("aspect,size", [("16:9", "960,540"), ("9:16", "540,960"), ("1:1", "540,540"), ("4:5", "560,700")])
def test_every_aspect_ratio_renders_at_its_size(media, tmp_path, aspect, size):
    tl = make_tl(media, [vclip("a", "red", 0, 30)]).model_copy(update={"aspect": aspect})
    out = render_to(tl, tmp_path, f"{aspect.replace(':', 'x')}.mp4")
    assert probe(out, "stream=width,height") == size
    assert px(out, 0.5, 100, 100)[0] > 200                                      # the picture fills the frame


# ------------------------------------------------------------------ chroma key

def green_screen(tmp_path):
    p = tmp_path / "screen.mp4"
    sh("-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=30:d=4,drawbox=x=20:y=40:w=100:h=100:color=red:t=fill,drawbox=x=240:y=60:w=60:h=60:color=0xc8e696:t=fill",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(p))
    return p


def keyed_tl(media, tmp_path, key, **kw):
    green_screen(tmp_path)
    extra = asset(tmp_path, "screen", "video", 120)
    return make_tl(media, [vclip("bg", "blue", 0, 60), vclip("fg", "screen", 0, 60, track="V2", key=key, **kw)], extra_assets=[extra])


def test_chroma_key_replaces_the_green_with_what_is_underneath(media, tmp_path):
    out = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=False)), tmp_path, "keyed.mp4")
    assert px(out, 0.5, 500, 100)[2] > 200 and px(out, 0.5, 500, 100)[1] < 40       # the green is gone: the blue picture shows through
    r, g, b = px(out, 0.5, 200, 270); assert r > 200 and g < 60 and b < 60          # the subject stays
    off = render_to(keyed_tl(media, tmp_path, None), tmp_path, "unkeyed.mp4")
    assert px(off, 0.5, 500, 100)[1] > 200                                           # without the key it is green
    # a key colour that is not in the picture keys nothing out
    other = render_to(keyed_tl(media, tmp_path, ChromaKey(color="#ff00ff", despill=False)), tmp_path, "other.mp4")
    assert px(other, 0.5, 500, 100)[1] > 200


def test_shrink_and_feather_clean_up_the_edge_without_touching_the_middle(media, tmp_path):
    plain = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=False)), tmp_path, "e0.mp4")
    shrunk = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=False, shrink=8)), tmp_path, "e1.mp4")
    # the left edge of the red subject is at x = 20/320 of the frame; a few pixels inside it the plain key still shows red, the shrunk one shows what is underneath
    x_edge = round(20 / 320 * 960)                                                   # previews are 960 px wide
    r, g, b = px(plain, 0.5, x_edge + 3, 270); assert r > 200 and b < 80
    r, g, b = px(shrunk, 0.5, x_edge + 3, 270); assert b > 150 and r < 100
    r, g, b = px(shrunk, 0.5, 200, 270); assert r > 200 and g < 60                  # the middle of the subject is untouched
    soft = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=False, feather=6)), tmp_path, "e2.mp4")
    mixed = [px(soft, 0.5, x, 270) for x in range(x_edge - 12, x_edge + 14, 3)]
    assert sum(1 for r, g, b in mixed if 10 < r < 245 and 10 < b < 245) >= 3           # a soft ramp of blends instead of a hard step
    hard = [px(plain, 0.5, x, 270) for x in range(x_edge - 12, x_edge + 14, 3)]
    assert sum(1 for r, g, b in hard if 10 < r < 245 and 10 < b < 245) < 2


def test_despill_pulls_green_reflections_back_to_the_mean_of_red_and_blue(media, tmp_path):
    spill_on = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=True)), tmp_path, "d_on.mp4")
    spill_off = render_to(keyed_tl(media, tmp_path, ChromaKey(despill=False)), tmp_path, "d_off.mp4")
    r1, g1, b1 = px(spill_off, 0.5, 810, 270)                                       # pale green-tinted patch (200, 230, 150): kept by the key, tint left
    r2, g2, b2 = px(spill_on, 0.5, 810, 270)
    assert g1 > 200 and abs(g2 - (r2 + b2) / 2) < 25 and g2 < g1 - 25               # green limited to the mean of red and blue (about 175)


def test_key_works_together_with_fades_transitions_and_effects(media, tmp_path):
    tl = keyed_tl(media, tmp_path, ChromaKey(despill=False), fade_in=30, effects=[Effect(type="contrast", value=10)])
    out = render_to(tl, tmp_path, "kf.mp4")
    assert px(out, 0.0, 200, 270)[2] > 200                                           # the first frame: the subject is still invisible (blue only)
    r, g, b = px(out, 0.5, 200, 270); assert 90 < r < 170 and b > 60               # half way in: subject and blue mixed, the green still keyed
    assert px(out, 0.5, 500, 100)[1] < 40
    r, g, b = px(out, 1.5, 200, 270); assert r > 200


# ------------------------------------------------------------------ other source formats and HDR (task 4.12)

def make_source(tmp_path, name, args, vf="null", src="testsrc2=s=640x360:r=30:d=2"):
    p = tmp_path / name
    sh("-f", "lavfi", "-i", src, "-vf", vf, *args, str(p))
    return p


@pytest.mark.parametrize("name,args", [
    ("hevc.mp4", ["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-crf", "20"]),
    ("prores.mov", ["-c:v", "prores_ks", "-profile:v", "1", "-pix_fmt", "yuv422p10le"]),
    ("vp9.webm", ["-c:v", "libvpx-vp9", "-b:v", "1M", "-pix_fmt", "yuv420p"]),
    ("h264.mkv", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]),
])
def test_common_video_codecs_render_to_the_same_picture_as_h264(media, tmp_path, name, args):
    ref = make_source(tmp_path, "ref.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12"])
    other = make_source(tmp_path, name, args)
    shots = []
    for src in (ref, other):
        tl = make_tl(media, [vclip("v", "src", 0, 45)], extra_assets=[Asset(id="src", kind="video", path=str(src), duration=60, license="User-provided")])
        shots.append(render_to(tl, tmp_path, f"{src.stem}.mp4"))
    assert probe(shots[1], "stream=width,height") == "960,540"
    assert ssim(shots[0], shots[1]) > 0.9, name                                  # the codec makes no visible difference


@pytest.mark.parametrize("trc", ["smpte2084", "arib-std-b67"])
def test_hdr_sources_are_tone_mapped_in_the_render_like_in_the_proxy(media, tmp_path, trc):
    from app.media import derive, ingest
    hdr_args = ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020", "-color_trc", trc, "-colorspace", "bt2020nc",
                "-x265-params", f"colorprim=bt2020:transfer={trc}:colormatrix=bt2020nc:log-level=error", "-crf", "16"]
    flat = "color=c=0xA8A8A8:s=640x360:r=30:d=2"          # a bright flat grey: a PQ/HLG reading of it is very different from an SDR reading
    hdr = make_source(tmp_path, "hdr.mp4", hdr_args, vf="format=yuv420p10le", src=flat)
    sdr = make_source(tmp_path, "sdr.mp4", ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-crf", "16", "-x265-params", "log-level=error"], vf="format=yuv420p10le", src=flat)
    info = ingest.probe(hdr, "video") if False else ingest.probe(hdr, None)
    assert info.hdr
    proxy = tmp_path / "hdr_proxy.mp4"
    derive.make_video_proxy(hdr, info, proxy)
    shots = {}
    for label, src in (("hdr", hdr), ("sdr", sdr)):
        tl = make_tl(media, [vclip("v", "src", 0, 45)], extra_assets=[Asset(id="src", kind="video", path=str(src), duration=60, license="User-provided")])
        shots[label] = render_to(tl, tmp_path, f"{label}_{trc}.mp4")
    # the render of the HDR file matches the (tone-mapped) proxy of it, and is not the untouched, washed-out reading of the same pixels
    scaled = tmp_path / f"proxy_{trc}.mp4"
    sh("-i", str(proxy), "-vf", "scale=960:540", "-c:v", "libx264", str(scaled))
    def mean_y(path):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(path), "-frames:v", "1", "-vf", "scale=32:18,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        return sum(raw) / len(raw)
    assert ssim(shots["hdr"], scaled) > 0.85
    assert abs(mean_y(shots["hdr"]) - mean_y(scaled)) < 8                        # as bright as the tone-mapped proxy ...
    if trc == "smpte2084":                                                       # ... and not the washed-out/dark untouched reading (HLG is nearly SDR-compatible, so only PQ differs)
        assert abs(mean_y(shots["hdr"]) - mean_y(shots["sdr"])) > 15


def test_rotated_phone_video_renders_upright(media, tmp_path):
    base = make_source(tmp_path, "up.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"])                  # 640x360, "top" of the picture is the testsrc2 header
    sh("-display_rotation:v", "90", "-i", str(base), "-c", "copy", str(tmp_path / "rot.mp4"))            # plays as 360x640
    tl = make_tl(media, [vclip("v", "src", 0, 30)], extra_assets=[Asset(id="src", kind="video", path=str(tmp_path / "rot.mp4"), duration=60, license="User-provided")]).model_copy(update={"aspect": "9:16"})
    out = render_to(tl, tmp_path, "rot_out.mp4")
    assert probe(out, "stream=width,height") == "540,960"
    assert sum(px(out, 0.5, 270, 480)) > 60                                                             # a real picture, not black


def test_bars_around_a_fitted_green_screen_picture_are_transparent_too(media, tmp_path):
    # a 16:9 green-screen clip shown whole in a square frame: the bars above and below must show what is underneath (blue), not black
    green_screen(tmp_path)
    extra = asset(tmp_path, "screen", "video", 120)
    tl = make_tl(media, [vclip("bg", "blue", 0, 60), vclip("fg", "screen", 0, 60, track="V2", fit="fit", key=ChromaKey(despill=False))],
                 extra_assets=[extra]).model_copy(update={"aspect": "1:1"})
    out = render_to(tl, tmp_path, "bars.mp4")
    r, g, b = px(out, 0.5, 270, 30)                                              # in the top bar
    assert b > 200 and r < 60 and g < 60
    r, g, b = px(out, 0.5, 270, 270)                                             # the picture's own green area is keyed too
    assert b > 200 and g < 60


# ------------------------------------------------------------------ focus (smart reframing)

def test_the_crop_to_the_frame_is_centred_on_the_focus_point(media, tmp_path):
    # a 2:1 picture, left half red, right half blue, shown in a square frame: the middle shows both, a focus on the left shows only red, on the right only blue
    p = tmp_path / "wide.png"
    sh("-f", "lavfi", "-i", "color=c=red:s=200x200", "-f", "lavfi", "-i", "color=c=blue:s=200x200", "-filter_complex", "[0][1]hstack", "-frames:v", "1", str(p))
    extra = asset(tmp_path, "wide", "image")

    def shot(focus):
        tl = make_tl(media, [vclip("p", "wide", 0, 30, kind="image", focus=focus)], extra_assets=[extra]).model_copy(update={"aspect": "1:1"})
        return render_to(tl, tmp_path, f"f_{focus}.mp4".replace(" ", "").replace("(", "").replace(")", "").replace(",", "_"))
    mid, left, right = shot(None), shot((0.1, 0.5)), shot((0.9, 0.5))
    assert px(mid, 0.5, 100, 270)[0] > 200 and px(mid, 0.5, 440, 270)[2] > 200                 # centred: red on the left, blue on the right
    assert px(left, 0.5, 100, 270)[0] > 200 and px(left, 0.5, 440, 270)[0] > 200               # focus left: red everywhere
    assert px(right, 0.5, 100, 270)[2] > 200 and px(right, 0.5, 440, 270)[2] > 200            # focus right: blue everywhere
    with pytest.raises(ValueError):
        vclip("p", "wide", 0, 30, kind="image", focus=(1.5, 0.5))


def test_a_final_quality_vertical_render_of_pictures_and_videos_is_1080x1920(media, tmp_path):
    tl = make_tl(media, [vclip("v", "red", 0, 30), vclip("p", "pic", 30, 30, kind="image", effects=[Effect(type="kenburns", value=10)])]).model_copy(update={"aspect": "9:16"})
    out = tmp_path / "vertical_final.mp4"
    render_timeline(tl, tmp_path, SETTINGS, quality="final", out=out, captions=False, normalize=False)
    assert probe(out, "stream=width,height") == "1080,1920"
    assert px(out, 0.5, 540, 960)[0] > 200                                       # the video segment
    assert sum(px(out, 1.5, 540, 960)) > 60                                      # the picture segment (testsrc), not black
