import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import Segment, Transcript, Word as TWord
from app.timeline import convert
from app.timeline.models import MAX_CLIPS, Asset, Clip, Timeline, Track, Transform
from app.timeline.validate import check

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")


# ------------------------------------------------------------------ models

def asset(id="a", kind="video", duration=300, **kw):
    return Asset(id=id, kind=kind, path="/x", duration=None if kind == "image" else duration, license="L", **kw)


def clip(id="c", track="V1", kind="video", asset_id="a", start=0, duration=30, **kw):
    return Clip(id=id, track=track, kind=kind, asset=asset_id, start=start, duration=duration, **kw)


def tl(clips, assets=None, tracks=None):
    return Timeline(tracks=tracks or [Track(id="V1", kind="video"), Track(id="A1", kind="audio"), Track(id="C1", kind="caption")],
                    clips=clips, assets=assets or {"a": asset(), "snd": asset("snd", "audio"), "img": asset("img", "image")})


def test_defaults_and_duration():
    t = tl([clip(start=10, duration=20), clip("d", start=40, duration=5)])
    assert t.schema_version == 1 and t.rev == 1 and t.fps == 30
    assert t.duration == 45
    assert check(t) == []


def test_unknown_fields_and_bad_values_are_rejected():
    with pytest.raises(ValidationError):
        Clip(id="c", track="V1", kind="video", asset="a", start=0, duration=1, bogus=1)
    for bad in (dict(start=-1), dict(duration=0), dict(volume=5), dict(in_point=-1), dict(id="bad id!"),
                dict(track="../x"), dict(fade_in=-1), dict(text="x" * 301), dict(text="a\x00b")):
        with pytest.raises(ValidationError):
            clip(**bad)
    for t in (dict(scale=0), dict(opacity=2), dict(rotation=400), dict(crop=(0.6, 0, 0.5, 0)), dict(crop=(1, 0, 0, 0))):
        with pytest.raises(ValidationError):
            Transform(**t)
    with pytest.raises(ValidationError):
        clip(meta={"k": "x" * 5000})
    with pytest.raises(ValidationError):
        clip(meta={"k": float("nan")})
    with pytest.raises(ValidationError):
        Asset(id="a", kind="video", path="/x", license="")  # no asset without a license
    with pytest.raises(ValidationError):
        Timeline(clips=[clip(id=f"c{i}") for i in range(MAX_CLIPS + 1)])


def test_asset_ids_may_contain_spaces_but_not_control_characters():
    assert asset("local:blue sky.jpg").id == "local:blue sky.jpg"
    assert clip(asset_id="local:blue sky.jpg").asset == "local:blue sky.jpg"
    for bad in ("a\x00b", "", "x" * 201):
        with pytest.raises(ValidationError):
            asset(bad)
        with pytest.raises(ValidationError):
            clip(asset_id=bad)
    with pytest.raises(ValidationError):
        clip(id="has space")                                  # clip and track ids stay strict


def test_floats_that_are_not_finite_are_rejected():
    for v in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            clip(volume=v)
        with pytest.raises(ValidationError):
            Transform(x=v)


# ------------------------------------------------------------------ validator

def problems(*clips, assets=None):
    return check(tl(list(clips), assets))


def has(ps, text):
    return any(text in p for p in ps)


def test_overlap_on_one_track_is_a_problem_but_touching_is_not():
    assert problems(clip("a1", start=0, duration=30), clip("a2", start=30, duration=30)) == []
    assert has(problems(clip("a1", start=0, duration=30), clip("a2", start=29, duration=30)), "overlap")
    assert problems(clip("a1", start=0, duration=30), clip("s", track="A1", kind="audio", asset_id="snd", start=10, duration=30)) == []  # other track


def test_tracks_and_assets_must_exist_and_match():
    assert has(problems(clip(track="V9")), "unknown track")
    assert has(problems(clip(asset_id="nope")), "unknown asset")
    assert has(problems(clip(kind="audio", asset_id="snd")), "cannot sit on the video track")
    assert has(problems(clip(asset_id="snd")), "cannot use the audio asset")
    assert has(problems(clip(kind="image", asset_id="a")), "cannot use the video asset")
    assert has(problems(clip("a1"), clip("a1", start=100)), "duplicate clip id")
    assert has(check(Timeline(tracks=[Track(id="V1", kind="video"), Track(id="V1", kind="video")])), "duplicate track")


def test_clips_cannot_run_past_their_media_unless_looping_or_an_image():
    assert has(problems(clip(duration=301)), "runs past the end")
    assert has(problems(clip(in_point=290, duration=20)), "runs past the end")
    assert has(problems(clip(in_point=300, duration=1)), "starts after the end")
    assert problems(clip(duration=900, loop=True)) == []
    assert problems(clip(kind="image", asset_id="img", duration=900)) == []
    assert has(problems(clip(kind="image", asset_id="img", in_point=5)), "images have no in-point")


def test_fades_transitions_captions_and_words():
    assert has(problems(clip(duration=30, fade_in=20, fade_out=20)), "fades are longer")
    assert has(problems(clip(duration=30, transition_in={"type": "crossfade", "duration": 31})), "transition is longer")
    cap = lambda **kw: Clip(id="cap", track="C1", kind="caption", start=0, duration=10, **kw)  # noqa: E731
    assert check(tl([cap(text="hello")])) == []
    assert has(check(tl([cap(text="  ")])), "caption text is empty")
    assert has(check(tl([cap(text="x", asset="a")])), "captions have no asset")
    w = [{"text": "a", "start": 5, "end": 2}]
    assert has(problems(Clip(id="n", track="A1", kind="audio", asset="snd", start=0, duration=10, words=w)), "ends before it starts")
    assert has(problems(clip(words=[{"text": "a", "start": 0, "end": 1}])), "only audio clips carry words")


def test_all_problems_are_reported_not_just_the_first():
    ps = problems(clip("x", track="V9"), clip("y", asset_id="nope", start=0), clip("z", duration=999, start=100))
    assert len(ps) == 3


# ------------------------------------------------------------------ conversion

def sh(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture()
def project(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    sh("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(media / "short.mp4"))    # 2 s: shorter than its scene
    sh("-f", "lavfi", "-i", "color=c=red:s=320x180", "-frames:v", "1", str(media / "pic.jpg"))
    sh("-f", "lavfi", "-i", "sine=frequency=300:duration=10", str(d / "upload.wav"))
    scenes = [
        {"id": 1, "start": 0.0, "end": 4.017, "text": "first scene", "query_en": "q1", "keywords": ["k"], "preferred_kind": "video"},
        {"id": 2, "start": 4.017, "end": 7.5, "text": "no media here", "query_en": "q2", "keywords": [], "preferred_kind": None},
        {"id": 3, "start": 7.5, "end": 10.0, "text": "third", "query_en": "q3", "keywords": [], "preferred_kind": "image"},
    ]
    def media_asset(aid, kind, path, **kw):
        return {"id": aid, "source": "pixabay", "kind": kind, "url": f"https://cdn.example/{aid}", "license": "Pixabay Content License",
                "license_url": "https://l", "author": "bob", "attribution": "by bob", "page_url": "https://p", **kw}
    picks = [
        {"scene_id": 1, "asset": media_asset("pixabay:1", "video", ""), "local_path": str(media / "short.mp4")},
        {"scene_id": 2, "asset": None, "local_path": None},
        {"scene_id": 3, "asset": media_asset("pixabay:3", "image", ""), "local_path": str(media / "pic.jpg")},
    ]
    (d / "scenes.json").write_text(json.dumps(scenes))
    (d / "assets.json").write_text(json.dumps(picks))
    words = [TWord(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(20)]
    tr = Transcript(language="en", duration=10.0, segments=[Segment(text="x", start=0, end=10, words=words)])
    (d / "transcript.final.json").write_text(tr.model_dump_json())
    info = SimpleNamespace(audio_file="upload.wav", options={}, aspect="16:9")
    return d, info, scenes, picks


@needs_ffmpeg
def test_build_timeline_structure_and_exact_tiling(project):
    d, info, scenes, _ = project
    t = convert.build_timeline(d, info, Settings(_env_file=None))
    assert check(t) == [] and t.rev == 1 and t.fps == 30
    assert [(x.id, x.kind) for x in t.tracks] == [("V1", "video"), ("A1", "audio"), ("C1", "caption")]
    v = sorted((c for c in t.clips if c.track == "V1"), key=lambda c: c.start)
    assert [c.id for c in v] == ["scene-1", "scene-3"]                      # scene 2 has no media: no clip
    assert v[0].start == 0 and v[0].duration == round(4.017 * 30) and v[1].start + v[1].duration == 300
    assert v[1].start == round(7.5 * 30)
    assert v[0].loop is True and v[1].loop is False                        # the 2 s clip must loop to fill ~4 s; the image never loops
    assert t.assets["pixabay:1"].duration == 60 and t.assets["pixabay:3"].duration is None
    nar = next(c for c in t.clips if c.track == "A1")
    assert nar.duration == 300 and len(nar.words) == 20 and nar.words[1].start == 15 and nar.words[1].end == 27
    assert t.assets["narration"].kind == "audio"


@needs_ffmpeg
def test_captions_become_non_overlapping_clips(project):
    d, info, *_ = project
    t = convert.build_timeline(d, info, Settings(_env_file=None))
    caps = sorted((c for c in t.clips if c.track == "C1"), key=lambda c: c.start)
    assert caps and all(c.text for c in caps)
    assert all(a.start + a.duration <= b.start for a, b in zip(caps, caps[1:]))
    # edited cues win over derived ones
    (d / "captions.json").write_text(json.dumps([{"start": 0.0, "end": 2.0, "text": "my edit"}]))
    t2 = convert.build_timeline(d, info, Settings(_env_file=None))
    assert [c.text for c in t2.clips if c.track == "C1"] == ["my edit"]


@needs_ffmpeg
def test_scenes_survive_the_round_trip_including_the_one_without_media(project):
    d, info, scenes, picks = project
    t = convert.build_timeline(d, info, Settings(_env_file=None))
    back, back_picks = convert.scenes_from_timeline(t)
    assert [s.id for s in back] == [1, 2, 3]
    for orig, new in zip(scenes, back):
        assert (new.text, new.query_en, new.keywords, new.preferred_kind) == (orig["text"], orig["query_en"], orig["keywords"], orig["preferred_kind"])
        assert abs(new.start - orig["start"]) <= 0.5 / 30 + 1e-9 and abs(new.end - orig["end"]) <= 0.5 / 30 + 1e-9  # frame grid
    assert [s.start for s in back][1:] == [s.end for s in back][:-1]       # still tiles
    assert back_picks[1].asset is None and back_picks[1].local_path is None
    for orig, new in ((picks[0], back_picks[0]), (picks[2], back_picks[2])):
        assert new.local_path == orig["local_path"]
        for f in ("id", "source", "kind", "url", "license", "license_url", "author", "attribution", "page_url"):
            assert getattr(new.asset, f) == orig["asset"][f], f


@needs_ffmpeg
def test_project_that_is_not_ready_cannot_be_converted(tmp_path):
    with pytest.raises(convert.ProjectNotReady):
        convert.build_timeline(tmp_path, SimpleNamespace(audio_file="x", options={}, aspect="16:9"), Settings(_env_file=None))


@needs_ffmpeg
def test_save_load_edit_tracking(project):
    d, info, *_ = project
    t = convert.build_timeline(d, info, Settings(_env_file=None))
    assert convert.load(d) is None and not convert.has_edits(d)
    convert.save(d, t)
    assert convert.load(d) == t and not convert.has_edits(d)
    convert.discard_unedited(d)
    assert convert.load(d) is None                                         # an unedited timeline is disposable
    convert.save(d, t.model_copy(update={"rev": 2}))
    convert.discard_unedited(d)
    assert convert.has_edits(d) and convert.load(d) is not None            # an edited one never is
    (d / "timeline.json").write_text("{broken")
    assert convert.has_edits(d) is False                                   # unreadable: treated as absent, no crash
