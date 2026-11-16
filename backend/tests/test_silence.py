import json

import pytest

from app.models import Segment, Transcript, Word
from app.pipeline.silence import (build_cut_filter, kept_intervals, plan_cuts, remap_time,
                                  remap_transcript)


def W(text, a, b):
    return Word(text=text, start=a, end=b)


# 0-1 "a", 1-2 "b", [gap 2..5], 5-6 "c", [gap 6..6.5 short], 6.5-7 "d", [tail 7..10]
WORDS = [W("a", 0.0, 1.0), W("b", 1.1, 2.0), W("c", 5.0, 6.0), W("d", 6.5, 7.0)]


def test_long_gaps_shortened_short_gaps_kept():
    cuts = plan_cuts(WORDS, 10.0, min_gap=0.8, keep_gap=0.4)
    # gap 2..5 keeps 0.2 each side -> cut 2.2..4.8; tail 7..10 keeps 0.2 after the word -> cut 7.2..10
    assert cuts == [(2.2, 4.8), (7.2, 10.0)]  # 0.5 s gap (6.0..6.5) and 0.1 s gap untouched


def test_leading_silence_keeps_half_gap_before_first_word():
    cuts = plan_cuts([W("a", 3.0, 4.0)], 4.0, 0.8, 0.4)
    assert cuts == [(0.0, 2.8)]


def test_no_long_gaps_no_cuts_and_bad_params():
    assert plan_cuts([W("a", 0.0, 1.0), W("b", 1.2, 2.0)], 2.0) == []
    assert plan_cuts([], 5.0) == []
    with pytest.raises(ValueError):
        plan_cuts(WORDS, 10.0, min_gap=0.3, keep_gap=0.4)


def test_remap_time():
    cuts = [(2.2, 4.8), (7.2, 10.0)]
    assert remap_time(1.0, cuts) == 1.0
    assert remap_time(5.0, cuts) == pytest.approx(2.4)   # 5.0 - 2.6 removed
    assert remap_time(7.0, cuts) == pytest.approx(4.4)
    assert remap_time(3.0, cuts) == pytest.approx(2.2)   # inside a cut: collapses to its start
    assert remap_time(10.0, cuts) == pytest.approx(7.2 - 2.6)


def test_remap_transcript_preserves_word_durations_and_order():
    tr = Transcript(language="en", duration=10.0, segments=[Segment(text="a b c d", start=0, end=7.0, words=WORDS)])
    cuts = plan_cuts(WORDS, 10.0)
    out = remap_transcript(tr, cuts)
    assert out.duration == pytest.approx(10.0 - sum(b - a for a, b in cuts))
    for old, new in zip(tr.words, out.words):
        assert new.end - new.start == pytest.approx(old.end - old.start)  # speech untouched
    starts = [w.start for w in out.words]
    assert starts == sorted(starts)
    # the 3 s pause between b and c becomes keep_gap (0.4 s)
    assert out.words[2].start - out.words[1].end == pytest.approx(0.4)


def test_kept_intervals_and_filter():
    cuts = [(2.2, 4.8), (7.2, 10.0)]
    assert kept_intervals(cuts, 10.0) == [(0.0, 2.2), (4.8, 7.2)]
    f = build_cut_filter(cuts, 10.0)
    assert f.count("atrim") == 2 and f.endswith("[a0][a1]concat=n=2:v=0:a=1[out]")


def test_option_changes_invalidate_only_what_depends_on_them(tmp_path):
    from app.config import Settings
    from app.pipeline.runner import Pipeline, Providers

    p = Pipeline(Settings(_env_file=None), Providers(None, None, None, None, None), tmp_path)  # type: ignore[arg-type]
    names = ("scenes.json", "assets.json", "audio_clean.flac", "audio_cut.flac", "audio_norm.flac", "transcript.json")

    def fresh():
        for n in names:
            (tmp_path / n).write_text("x")

    def left():
        return {n for n in names if (tmp_path / n).exists()}

    base = {"cleaner": "ffmpeg", "silence": None, "lufs": -14.0}
    fresh(); p._sync_options(base)
    assert left() == set(names)                                    # first run: nothing deleted
    p._sync_options(base)
    assert left() == set(names)                                    # same options: all kept

    p._sync_options({**base, "lufs": -18.0})                       # loudness: only the normalised audio
    assert left() == set(names) - {"audio_norm.flac"}
    fresh(); p._sync_options({**base, "lufs": -18.0, "cleaner": "noop"})
    assert {"scenes.json", "assets.json"} <= left()                # cleaner never re-plans scenes
    assert not ({"audio_clean.flac", "audio_cut.flac", "audio_norm.flac"} & left())

    fresh(); p._sync_options({"cleaner": "noop", "lufs": -18.0, "silence": [0.8, 0.4]})  # timeline moved
    assert left() == {"audio_clean.flac", "transcript.json"}       # scenes/media/cut audio redone
    assert json.loads((tmp_path / "run_config.json").read_text())["silence"] == [0.8, 0.4]
