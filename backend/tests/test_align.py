import pytest

from app.models import Segment, Transcript, Word
from app.pipeline.align import align_script, split_script


def asr(text, lang="en", step=0.5, start=0.0):
    t, words = start, []
    for w in text.split():
        words.append(Word(text=w, start=round(t, 3), end=round(t + step * 0.9, 3)))
        t += step
    return Transcript(language=lang, duration=t + 1, segments=[Segment(text=text, start=0, end=t, words=words)])


def test_exact_match_keeps_times_and_script_punctuation():
    a = asr("hello brave new world")
    out, st = align_script("Hello, brave new world!", a)
    assert [w.text for w in out.words] == ["Hello,", "brave", "new", "world!"]  # script spelling wins
    assert [w.start for w in out.words] == [w.start for w in a.words]
    assert (st.exact, st.script_words, st.match_ratio) == (4, 4, 1.0)


def test_misheard_word_gets_script_text_and_the_same_time_slot():
    a = asr("the castle stands above the vally")  # ASR error: 'vally'
    out, st = align_script("The castle stands above the valley.", a)
    assert out.words[-1].text == "valley."
    assert out.words[-1].start == a.words[-1].start and out.words[-1].end == a.words[-1].end
    assert st.exact == 5


def test_word_missing_from_audio_is_interpolated_between_neighbours():
    a = asr("one two four five")  # speaker skipped 'three'
    out, st = align_script("one two three four five", a)
    w = out.words
    assert [x.text for x in w] == ["one", "two", "three", "four", "five"]
    assert w[1].end <= w[2].start and w[2].end <= w[3].start + 1e-6  # fits in the gap, in order
    assert st.exact == 4


def test_extra_spoken_words_are_dropped():
    out, st = align_script("one two three", asr("one um two uh three"))
    assert [x.text for x in out.words] == ["one", "two", "three"] and st.exact == 3


def test_times_are_monotonic_with_positive_length():
    out, _ = align_script("a b c d e f g", asr("a x y z g"))
    prev = 0.0
    for w in out.words:
        assert w.start >= prev - 1e-9 and w.end > w.start
        prev = w.end


def test_sentences_become_segments_and_blank_lines_break():
    segs = split_script("First one. Second one?\n\nthird without stop", urdu=False)
    assert segs == [["First", "one."], ["Second", "one?"], ["third", "without", "stop"]]
    out, _ = align_script("First one. Second one?\n\nthird without stop", asr("first one second one third without stop"))
    assert [s.text for s in out.segments] == ["First one.", "Second one?", "third without stop"]
    assert out.segments[1].start >= out.segments[0].end - 1e-9


def test_urdu_script_is_normalised_and_matched_despite_asr_letter_errors():
    script = "پاکستان کے شمالی علاقوں میں برف سے ڈھکے ہوئے پہاڑ ہیں۔"
    heard = "پاکستان کے شمالی علاقوں میں برف سے دھکے ہوئے پہاڑ ہیں"  # ڈھکے misheard as دھکے
    out, st = align_script(script, asr(heard, lang="ur"))
    assert " ".join(w.text for w in out.words) == script  # captions get the correct spelling
    assert st.exact == 10 and st.script_words == 11  # only the misheard word differs
    # Arabic letter forms in the script are normalised to Urdu ones
    out2, _ = align_script("ايك كتاب۔", asr("ایک کتاب", lang="ur"))
    assert [w.text for w in out2.words] == ["ایک", "کتاب۔"]


def test_wrong_script_gives_low_match_ratio_and_empty_inputs_error():
    _, st = align_script("completely different words here now", asr("the castle stands above"))
    assert st.match_ratio < 0.5
    with pytest.raises(ValueError):
        align_script("   ", asr("hello"))
    with pytest.raises(ValueError):
        align_script("hello", Transcript(language="en", duration=3, segments=[]))


def test_confidence_is_kept_for_matching_words_and_unmatched_words_get_the_given_value():
    from app.models import Segment, Transcript, Word
    from app.pipeline.align import align_script

    words = [Word(text="the", start=0, end=0.3, prob=0.9), Word(text="cat", start=0.3, end=0.6, prob=0.8), Word(text="sat", start=0.6, end=1.0, prob=0.3)]
    asr = Transcript(language="en", duration=1.0, segments=[Segment(text="the cat sat", start=0, end=1, words=words)])
    out, _ = align_script("the cat sit", asr, unmatched_prob=0.5)
    assert [w.prob for w in out.words] == [0.9, 0.8, 0.5]                     # "sit" was changed: ask a person to look at it
    out, _ = align_script("the cat sit", asr)
    assert [w.prob for w in out.words] == [0.9, 0.8, None]                    # a user's script is exact: nothing to check


def test_cleanup_step_applies_checked_corrections_and_never_fails_the_run(tmp_path, monkeypatch):
    from app.config import Settings
    from app.models import Segment, Transcript, Word
    from app.pipeline import correct
    from app.pipeline.runner import Pipeline

    words = [Word(text=t, start=i * 0.4, end=i * 0.4 + 0.35, prob=0.9) for i, t in enumerate("the cat sat on the mat".split())]
    tr = Transcript(language="en", duration=3, segments=[Segment(text="x", start=0, end=3, words=words)])
    s = Settings(_env_file=None, gemini_api_key="k", cleanup="on")
    p = Pipeline(s, None, tmp_path)  # type: ignore[arg-type]
    monkeypatch.setattr(correct.GeminiCorrector, "_ask", lambda self, lang, text: text.replace("cat", "cart"))
    out = p.cleanup(tr, force=True)
    assert " ".join(w.text for w in out.words) == "the cart sat on the mat"
    assert [w.prob for w in out.words] == [0.9, 0.5, 0.9, 0.9, 0.9, 0.9]
    monkeypatch.setattr(correct.GeminiCorrector, "_ask", lambda self, lang, text: None)    # the service is down
    assert p.cleanup(tr, force=True) is tr
    monkeypatch.setattr(correct.GeminiCorrector, "_ask", lambda self, lang, text: "totally different words about something else entirely now")
    assert p.cleanup(tr, force=True) is tr                                                  # too different: rejected
    assert Pipeline(Settings(_env_file=None, cleanup="off", gemini_api_key="k"), None, tmp_path).cleanup(tr, True) is tr  # type: ignore[arg-type]
