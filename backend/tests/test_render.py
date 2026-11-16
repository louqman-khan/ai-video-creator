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
from app.timeline.models import Asset, Clip, Effect, Timeline, Track, Transform
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
    ok = make_tl(media, [vclip("i", "pic", 0, 30, kind="image", effects=[Effect(type="kenburns", value=10)],
                               transform=Transform(opacity=0.5)), vclip("v", "red", 30, 30)])
    assert unsupported_features(ok) == []
    bad = make_tl(media, [
        vclip("fx", "red", 0, 30, effects=[Effect(type="blur", value=5)]),
        vclip("kb", "red", 30, 30, effects=[Effect(type="kenburns", value=5)]),
        vclip("tr", "red", 60, 30, transition_in={"type": "crossfade", "duration": 10}),
        vclip("fd", "red", 90, 30, fade_in=5),
        vclip("tf", "red", 120, 30, transform=Transform(scale=2)),
        vclip("ps", "red", 150, 30, transform=Transform(crop=(0.1, 0, 0, 0))),
    ])
    msg = " | ".join(unsupported_features(bad))
    for word in ("blur", "zoom on video", "transitions", "fades on pictures", "crop, position, scale and rotation"):
        assert word in msg


def test_render_refuses_before_doing_any_work(media, tmp_path):
    tl = make_tl(media, [vclip("fx", "red", 0, 30, effects=[Effect(type="blur", value=5)])])
    with pytest.raises(RenderUnsupported, match="blur"):
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
