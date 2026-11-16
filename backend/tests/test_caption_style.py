import pytest

from app.models import Segment, Transcript, Word
from app.pipeline.caption_style import CaptionStyle, hex_to_ass, load_style
from app.pipeline.captions import build_ass


def tr(lang="en", n=10):
    words = [Word(text=f"w{i}", start=i * 0.4, end=i * 0.4 + 0.35) for i in range(n)]
    return Transcript(language=lang, duration=n * 0.4,
                      segments=[Segment(text="x", start=0, end=n * 0.4, words=words)])


def style_line(ass):
    return next(l for l in ass.splitlines() if l.startswith("Style:")).removeprefix("Style: ").split(",")


def test_hex_to_ass_is_bgr():
    assert hex_to_ass("#FF0000") == "&H000000FF"  # red
    assert hex_to_ass("00ff80") == "&H0080FF00"
    with pytest.raises(ValueError):
        hex_to_ass("red")


def test_style_values_reach_the_ass_file():
    st = CaptionStyle(font="Foo", size_pct=10, color="#FFFF00", outline_color="#112233",
                      outline_width=5, position="top", margin_pct=10, bold=True)
    f = style_line(build_ass(tr(), 1920, 1080, st))
    assert f[1] == "Foo" and f[2] == "108"          # 10% of 1080
    assert f[3] == "&H0000FFFF" and f[5] == "&H00332211"
    assert f[7] == "-1" and f[16] == "5.0"           # bold, outline
    assert f[18] == "8" and f[21] == "108"           # top alignment, 10% margin


def test_default_style_is_unchanged_per_language():
    en, ur = style_line(build_ass(tr("en"))), style_line(build_ass(tr("ur")))
    assert (en[1], en[2], en[18]) == ("Arial", "65", "2")
    assert (ur[1], ur[2]) == ("Noto Nastaliq Urdu", "119")


def test_words_per_line_is_a_hard_limit_and_no_orphans():
    lines = [l for l in build_ass(tr(n=10), style=CaptionStyle(words_per_line=3)).splitlines() if l.startswith("Dialogue")]
    counts = [len(l.rsplit(",,", 1)[1].split()) for l in lines]
    assert max(counts) <= 3 and min(counts) >= 2 and sum(counts) == 10


def test_toml_file_then_cli_override(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text('[captions]\ncolor = "#00FF00"\nposition = "center"\nwords_per_line = 4\n')
    st = load_style(f, color="#FF00FF", position=None)  # CLI colour wins, None is ignored
    assert (st.color, st.position, st.words_per_line) == ("#FF00FF", "center", 4)
    top = tmp_path / "t.toml"
    top.write_text('position = "top"\n')  # top-level keys work too
    assert load_style(top).position == "top"


def test_bad_values_are_rejected():
    with pytest.raises(Exception):
        load_style(None, color="yellow")
    with pytest.raises(Exception):
        load_style(None, position="left")
    with pytest.raises(Exception):
        load_style(None, size_pct=90)


def test_unknown_key_in_style_file_is_an_error(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text("[captions]\ncolour = \"#FFFFFF\"\n")  # typo: colour
    with pytest.raises(Exception, match="colour"):
        load_style(f)
