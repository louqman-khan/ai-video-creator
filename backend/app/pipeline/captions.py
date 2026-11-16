"""Transcript words -> ASS subtitles (rendered by libass through FFmpeg).
Urdu is right-to-left; libass shapes it with HarfBuzz/FriBidi, so the text is passed through as-is."""

from __future__ import annotations

from app.models import Transcript, Word

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
    # no one-word orphan at the end of a run: fold it into the previous cue (allow some overflow)
    if len(cues) > 1 and len(cues[-1]) == 1:
        merged = cues[-2] + cues[-1]
        if sum(len(x.text) + 1 for x in merged) <= max_chars * 1.5 and merged[-1].end - merged[0].start <= max_s * 1.5:
            cues[-2:] = [merged]
    return cues


def build_ass(
    transcript: Transcript, width: int = 1920, height: int = 1080, font: str | None = None
) -> str:
    urdu = transcript.language == "ur"
    font = font or ("Noto Nastaliq Urdu" if urdu else "Arial")
    size = round(height * (0.11 if urdu else 0.06))  # Nastaleeq glyphs render small
    margin_v = round(height * 0.07)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        f"0,0,0,0,100,100,0,0,1,3,1,2,{round(width * 0.05)},{round(width * 0.05)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    cues: list[list[Word]] = []
    for seg in transcript.segments:  # never merge words across ASR segment boundaries
        cues += group_words([w for w in seg.words if w.text.strip()])
    lines = []
    for i, cue in enumerate(cues):
        start, end = cue[0].start, cue[-1].end
        if i + 1 < len(cues) and cues[i + 1][0].start - end < 0.3:
            end = cues[i + 1][0].start  # close tiny gaps: no flicker between cues
        text = _escape(" ".join(w.text for w in cue))
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"
