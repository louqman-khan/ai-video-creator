"""Output sizes per quality. Kept apart so the pipeline and the timeline renderer can share them."""

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}  # final quality
PREVIEW_SIZES = {"16:9": (960, 540), "9:16": (540, 960), "1:1": (540, 540), "4:5": (560, 700)}  # fast edit-loop renders (about a quarter of the pixels)
PORTRAIT = ("9:16", "4:5")  # formats taller than wide: stock search asks for portrait pictures


EXPORT_PRESETS = {"720p": 2 / 3, "1080p": 1.0, "4k": 2.0}  # relative to the 1080-class sizes above (the short side is 720 / 1080 / 2160)


def _even(v: float) -> int:
    return max(2, 2 * round(v / 2))


def render_size(aspect: str, quality: str, preset: str | None = None) -> tuple[int, int]:
    """Pixel size of a render. `preset` (720p / 1080p / 4k) only matters for the final quality."""
    if quality == "preview":
        return PREVIEW_SIZES[aspect]
    w, h = ASPECTS[aspect]
    f = EXPORT_PRESETS[preset or "1080p"]
    return _even(w * f), _even(h * f)


def base_video_name(quality: str) -> str:
    """The caption-free video of each quality (the caption preview draws onto it)."""
    return "concat_preview.mp4" if quality == "preview" else "concat.mp4"
