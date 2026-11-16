from app.models import Segment, Transcript, Word
from app.pipeline.scenes import chunk_scenes
from app.text.urdu import normalize_text, normalize_transcript


def test_arabic_letter_forms_become_urdu():
    assert normalize_text("ايك كتاب") == "ایک کتاب"  # ي->ی, ك->ک
    assert normalize_text("پاكستان") == "پاکستان"
    assert normalize_text("هم") == "ہم"  # Arabic heh -> Urdu heh goal


def test_digits_punctuation_and_marks():
    assert normalize_text("سال 2024 ٢٠٢٤") == "سال 2024 ۲۰۲۴"  # only Arabic-Indic digits change
    assert normalize_text("کیا ہے ?") == "کیا ہے؟"  # space before mark removed
    assert normalize_text("ٹھیک ہے.") == "ٹھیک ہے۔"
    assert normalize_text("ســلام") == "سلام"  # tatweel removed
    assert normalize_text("  دو   لفظ ") == "دو لفظ"


def test_keeps_correct_urdu_untouched():
    s = "پاکستان کے شمالی علاقوں میں برف سے ڈھکے ہوئے پہاڑ ہیں۔"
    assert normalize_text(s) == s


def _t(*groups):
    segs, t = [], 0.0
    for g in groups:
        words = []
        for w in g.split():
            words.append(Word(text=w, start=t, end=t + 0.4)); t += 0.5
        segs.append(Segment(text=g, start=words[0].start, end=words[-1].end, words=words))
        t += 0.6  # pause between segments
    return Transcript(language="ur", duration=t, segments=segs)


def test_segment_ending_in_pause_gets_urdu_full_stop():
    out = normalize_transcript(_t("یہ پہلا جملہ ہے", "یہ دوسرا جملہ ہے۔", "اور تیسرا"))
    ends = [s.words[-1].text for s in out.segments]
    assert ends == ["ہے۔", "ہے۔", "تیسرا۔"]  # the existing stop is not doubled
    assert out.segments[0].text.endswith("ہے۔")


def test_full_stop_lets_scene_splitter_cut_at_sentence_end():
    tr = normalize_transcript(_t(*["یہ ایک جملہ ہے"] * 6))
    assert len(chunk_scenes(tr, min_s=1.0, max_s=8.0)) > 1
