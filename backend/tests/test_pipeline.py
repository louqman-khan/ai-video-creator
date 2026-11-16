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
    assert "Noto Nastaliq Urdu" in ass and "Dialogue:" in ass and "یہ ایک" in ass
    assert "Jameel Noori Nastaleeq" in build_ass(tr, font="Jameel Noori Nastaleeq")  # --font override
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


def test_ranker_keyword_match_beats_source_order():
    scene = Scene(id=1, start=0, end=6, text="x", query_en="old castle", keywords=["fortress"])

    def a(i, tags=(), title=""):
        return MediaAsset(id=f"s:{i}", source="s", kind="image", url="u", license="L",
                          width=1920, height=1080, tags=list(tags), title=title)

    cands = [a(1, tags=["beach"]), a(2, tags=["castle", "old", "stone"]), a(3, title="Fortress wall")]
    ranked = HeuristicRanker().rank(scene, cands)
    assert [x.id for x in ranked] == ["s:2", "s:3", "s:1"]


def test_credits_dedupe_and_include_license():
    asset = MediaAsset(id="wikimedia:1", source="wikimedia", kind="image", url="u", license="CC BY 4.0",
                       license_url="https://cc/by", attribution='"Bridge" by Jane')
    text = credits_text([ScenePick(scene_id=1, asset=asset), ScenePick(scene_id=2, asset=asset),
                         ScenePick(scene_id=3)])
    assert text.count("Bridge") == 1 and "CC BY 4.0" in text


def test_doctor_reports_missing_keys_without_network():
    from app.config import Settings
    from app.doctor import run_checks

    checks = {c.name: c for c in run_checks(Settings(_env_file=None), network=False)}
    assert checks["python >= 3.11"].status == "ok"
    assert checks["PIXABAY_API_KEY"].status == "warn"
    assert checks["PEXELS_API_KEY (optional)"].status == "ok"  # optional: never a problem
    assert not any(n.startswith("network") for n in checks)


def test_providers_selected_from_env_without_code_edits(monkeypatch):
    from app.config import Settings
    from app.providers.avatar_renderer import create_avatar_renderer
    from app.providers.audio_cleaner import create_cleaner
    from app.providers.audio_cleaner.ffmpeg_cleaner import FfmpegCleaner
    from app.providers.media_ranker import create_ranker
    from app.providers.scene_planner import create_planner
    from app.providers.scene_planner.heuristic import HeuristicPlanner
    from app.providers.transcriber import create_transcriber
    from app.providers.transcriber.faster_whisper import FasterWhisperTranscriber
    from app.providers.tts import create_tts

    monkeypatch.setenv("SCENE_PLANNER", "heuristic")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    s = Settings(_env_file=None)
    assert isinstance(create_planner(s), HeuristicPlanner)
    t = create_transcriber(s)
    assert isinstance(t, FasterWhisperTranscriber) and t.model_size == "tiny"
    assert isinstance(create_cleaner(s), FfmpegCleaner)  # default since task 2.5
    create_ranker(s), create_tts(s), create_avatar_renderer(s)

    monkeypatch.setenv("SCENE_PLANNER", "nope")
    with pytest.raises(ValueError, match="Available"):
        create_planner(Settings(_env_file=None))


def test_httpx_request_logging_is_silenced_so_api_keys_cannot_leak():
    import logging

    import app.http  # noqa: F401  (import side effect sets the log levels)

    assert logging.getLogger("httpx").level >= logging.WARNING


def test_fallback_planner_uses_heuristic_for_english_and_errors_for_urdu():
    from app.providers.scene_planner import FallbackPlanner

    class Broken:
        def plan(self, t):
            raise PlannerError("down")

    fb = FallbackPlanner(Broken(), HeuristicPlanner())
    scenes = fb.plan(make_transcript("The ancient castle stands above the misty mountain valley. " * 3))
    assert all(s.query_en for s in scenes)
    with pytest.raises(PlannerError, match="English"):
        fb.plan(make_transcript("سلام دنیا", lang="ur"))


def test_load_wav_reads_16k_mono(tmp_path):
    import wave

    from app.providers.transcriber.faster_whisper import FasterWhisperTranscriber

    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes((b"\x00\x40" * 1600))
    arr = FasterWhisperTranscriber._load_wav(p)
    assert arr.shape == (1600,) and 0.49 < float(arr[0]) < 0.51


def test_captions_never_merge_across_segments():
    from app.pipeline.captions import build_ass

    tr = make_transcript("a b c d")  # one segment of 4 words, then split it into two segments
    w = tr.words
    tr = Transcript(language="en", duration=tr.duration, segments=[
        Segment(text="a b", start=0, end=1, words=w[:2]),
        Segment(text="c d", start=1, end=2, words=w[2:]),
    ])
    lines = [x for x in build_ass(tr).splitlines() if x.startswith("Dialogue")]
    assert len(lines) == 2 and lines[0].endswith("a b") and lines[1].endswith("c d")


def test_caption_grouping_avoids_one_word_orphan_without_exceeding_max_words():
    from app.pipeline.captions import group_words

    ws = [Word(text=t, start=i * 0.4, end=i * 0.4 + 0.35) for i, t in enumerate(["ab"] * 8 + ["cd."])]
    assert [len(c) for c in group_words(ws, max_words=8)] == [7, 2]  # 8 + a lone 9th word -> one word moves over
    ws2 = [Word(text=t, start=i * 0.4, end=i * 0.4 + 0.35) for i, t in enumerate(["ab"] * 8 + ["cd", "ef"])]
    assert [len(c) for c in group_words(ws2, max_words=8)] == [8, 2]  # two words is not an orphan: kept
