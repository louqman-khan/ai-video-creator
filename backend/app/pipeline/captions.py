"""Transcript words -> ASS subtitles (rendered by libass through FFmpeg).
Urdu is right-to-left; libass shapes it with HarfBuzz/FriBidi, so the text is passed through as-is."""

from __future__ import annotations

from app.models import Transcript, Word
from app.pipeline.caption_style import ALIGNMENT, CaptionStyle, hex_to_ass

SENTENCE_END = set(".?!۔؟…")


def ass_time(t: float) -> str:
    cs = max(0, round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(
    words: list[Word], max_words: int = 7, max_chars: int = 40, max_s: float = 4.0, gap_s: float = 0.7
) -> list[list[Word]]:
    cues: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if (
                len(cur) >= max_words
                or chars > max_chars
                or w.end - cur[0].start > max_s
                or w.start - cur[-1].end > gap_s
                or cur[-1].text[-1:] in SENTENCE_END
            ):
                cues.append(cur)
                cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    # no one-word orphan at the end: borrow a word from the previous cue (never exceeds max_words)
    if len(cues) > 1 and len(cues[-1]) == 1 and len(cues[-2]) >= 3:
        cues[-1].insert(0, cues[-2].pop())
    return cues


def build_ass(
    transcript: Transcript,
    width: int = 1920,
    height: int = 1080,
    style: CaptionStyle | None = None,
    font: str | None = None,
) -> str:
    st = style or CaptionStyle()
    urdu = transcript.language == "ur"
    font = font or st.font or ("Noto Nastaliq Urdu" if urdu else "Arial")
    # Nastaleeq glyphs render small, so Urdu defaults larger
    size = round(height * (st.size_pct or (11.0 if urdu else 6.0)) / 100)
    margin_v = round(height * st.margin_pct / 100)
    outline = st.outline_width * height / 1080
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{hex_to_ass(st.color)},&H000000FF,{hex_to_ass(st.outline_color)},&H64000000,"
        f"{-1 if st.bold else 0},0,0,0,100,100,0,0,1,{outline:.1f},1,{ALIGNMENT[st.position]},"
        f"{round(width * 0.05)},{round(width * 0.05)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    cues: list[list[Word]] = []
    for seg in transcript.segments:  # never merge words across ASR segment boundaries
        cues += group_words(
            [w for w in seg.words if w.text.strip()], max_words=st.words_per_line, max_chars=st.max_chars
        )
    lines = []
    for i, cue in enumerate(cues):
        start, end = cue[0].start, cue[-1].end
        if i + 1 < len(cues) and cues[i + 1][0].start - end < 0.3:
            end = cues[i + 1][0].start  # close tiny gaps: no flicker between cues
        text = _escape(" ".join(w.text for w in cue))
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"
