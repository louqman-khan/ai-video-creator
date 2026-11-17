"""Output sizes per quality. Kept apart so the pipeline and the timeline renderer can share them."""

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}  # final quality
PREVIEW_SIZES = {"16:9": (960, 540), "9:16": (540, 960), "1:1": (540, 540), "4:5": (560, 700)}  # fast edit-loop renders (about a quarter of the pixels)
PORTRAIT = ("9:16", "4:5")  # formats taller than wide: stock search asks for portrait pictures


def render_size(aspect: str, quality: str) -> tuple[int, int]:
    return (PREVIEW_SIZES if quality == "preview" else ASPECTS)[aspect]


def base_video_name(quality: str) -> str:
    """The caption-free video of each quality (the caption preview draws onto it)."""
    return "concat_preview.mp4" if quality == "preview" else "concat.mp4"
