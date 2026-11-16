import pytest

from app.models import MediaAsset, Scene, ScenePick, Segment, Transcript, Word
from app.pipeline.assemble import scene_frames
from app.pipeline.captions import ass_time, build_ass
from app.pipeline.runner import credits_text
from app.pipeline.scenes import chunk_scenes
from app.providers.media_ranker.heuristic import HeuristicRanker
from app.providers.scene_planner.gemini import parse_annotations
from app.providers.scene_planner.heuristic import HeuristicPlanner
from app.providers.scene_planner.interface import PlannerError


def make_transcript(text: str, lang="en", step=0.5, pause_after=None, duration=None) -> Transcript:
    pause_after = pause_after or {}
    t, words = 0.0, []
    for i, w in enumerate(text.split()):
        words.append(Word(text=w, start=t, end=t + step * 0.9))
        t += step + pause_after.get(i, 0)
    seg = Segment(text=text, start=0, end=t, words=words)
    return Transcript(language=lang, duration=duration or t, segments=[seg])


def test_scenes_tile_audio_without_gaps():
    tr = make_transcript(" ".join(f"w{i}" if i % 9 else f"w{i}." for i in range(60)))
    scenes = chunk_scenes(tr)
    assert scenes[0].start == 0 and scenes[-1].end == pytest.approx(tr.duration, abs=0.01)
    for a, b in zip(scenes, scenes[1:]):
        assert a.end == b.start
    assert all(s.duration <= 8.5 for s in scenes)
    assert " ".join(s.text for s in scenes) == " ".join(w.text for w in tr.words)


def test_urdu_sentence_end_splits():
    tr = make_transcript("یہ ایک جملہ ہے۔ " * 8, lang="ur", step=0.6)
    scenes = chunk_scenes(tr, min_s=2.0)
    assert len(scenes) > 1


def test_empty_transcript_errors():
    with pytest.raises(ValueError):
        chunk_scenes(Transcript(language="en", duration=3, segments=[]))


def test_scene_frames_do_not_drift():
    scenes = [Scene(id=i + 1, start=i * 3.337, end=(i + 1) * 3.337, text="x") for i in range(30)]
    assert sum(scene_frames(scenes, 30)) == round(30 * 3.337 * 30)


def test_ass_time_and_urdu_style():
    assert ass_time(3725.5) == "1:02:05.50"
    tr = make_transcript("یہ ایک جملہ ہے۔", lang="ur")
    ass = build_ass(tr)
    assert "Jameel Noori Nastaleeq" in ass and "Dialogue:" in ass and "یہ ایک" in ass
    assert "Arial" in build_ass(make_transcript("hello world"))


def test_heuristic_planner_english_only():
    tr = make_transcript("The ancient castle stands above the misty mountain valley. " * 3)
    scenes = HeuristicPlanner().plan(tr)
    assert all(s.query_en for s in scenes)
    with pytest.raises(PlannerError):
        HeuristicPlanner().plan(make_transcript("سلام دنیا", lang="ur"))


def test_gemini_annotation_parsing_handles_fences_and_wrapper():
    raw = '```json\n[{"id": 1, "query_en": "old castle", "keywords": ["fort"], "preferred_kind": "video"}]\n```'
    [a] = parse_annotations(raw)
    assert a.query_en == "old castle" and a.preferred_kind == "video"
    [b] = parse_annotations('{"scenes": [{"id": 2, "query_en": "sea"}]}')
    assert b.id == 2


def test_ranker_prefers_unused_landscape_video():
    scene = Scene(id=1, start=0, end=6, text="x", query_en="q")

    def a(i, kind="image", w=1920, h=1080, dur=None):
        return MediaAsset(id=f"s:{i}", source="s", kind=kind, url="u", license="L", width=w, height=h, duration=dur)

    cands = [a(1, w=1080, h=1920), a(2), a(3, kind="video", dur=10)]
    ranked = HeuristicRanker().rank(scene, cands, used={"s:3"})
    # reuse (-100) is penalised harder than wrong orientation (-20)
    assert [x.id for x in ranked] == ["s:2", "s:1", "s:3"]


def test_credits_dedupe_and_include_license():
    asset = MediaAsset(id="wikimedia:1", source="wikimedia", kind="image", url="u", license="CC BY 4.0",
                       license_url="https://cc/by", attribution='"Bridge" by Jane')
    text = credits_text([ScenePick(scene_id=1, asset=asset), ScenePick(scene_id=2, asset=asset),
                         ScenePick(scene_id=3)])
    assert text.count("Bridge") == 1 and "CC BY 4.0" in text
