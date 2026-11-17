"""Smart reframing: where is the interesting part of a picture? A picture that is wider than the video frame is cropped to fill it; instead of always
cutting equally from both sides the crop window is centred on this point (the "focus"), so the subject stays in the frame.

Method: spectral-residual saliency (Hou & Zhang 2007) on the luminance of a small copy of the picture: what stands out from the usual
spectrum of the image is salient. The focus is the saliency-weighted centre of the most salient tenth of the picture, softly pulled towards the
middle so that noise at the borders does not win. No model files, numpy + Pillow only. It finds the most conspicuous *thing*; it does not know faces."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from app.media import ffmpeg  # noqa: F401  (puts the bundled ffmpeg on PATH)

SMALL = 96


def focus_of_image(img: Image.Image) -> tuple[float, float]:
    """(x, y) as fractions of the picture (0..1)."""
    w, h = img.size
    gray = img.convert("L").resize((SMALL, max(8, round(SMALL * h / w))), Image.BILINEAR)
    a = np.asarray(gray, dtype=np.float64) / 255.0
    spectrum = np.fft.fft2(a)
    log_amp = np.log(np.abs(spectrum) + 1e-8)
    k = np.ones((3, 3)) / 9.0
    pad = np.pad(log_amp, 1, mode="edge")
    avg = sum(pad[i:i + log_amp.shape[0], j:j + log_amp.shape[1]] * k[i, j] for i in range(3) for j in range(3))
    sal = np.abs(np.fft.ifft2(np.exp(log_amp - avg + 1j * np.angle(spectrum)))) ** 2
    sal = np.asarray(Image.fromarray((255 * sal / (sal.max() or 1)).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5)), dtype=np.float64)
    ys, xs = np.mgrid[0:sal.shape[0], 0:sal.shape[1]]
    centre = np.exp(-(((xs / sal.shape[1] - 0.5) ** 2) + ((ys / sal.shape[0] - 0.5) ** 2)) / (2 * 0.45 ** 2))  # a mild pull towards the middle
    sal = sal * centre
    top = sal >= np.quantile(sal, 0.9)
    wgt = sal * top
    total = float(wgt.sum())
    if total <= 0:
        return 0.5, 0.5
    fx = float((wgt * (xs + 0.5)).sum() / total / sal.shape[1])
    fy = float((wgt * (ys + 0.5)).sum() / total / sal.shape[0])
    return round(min(0.95, max(0.05, fx)), 3), round(min(0.95, max(0.05, fy)), 3)


def focus_of_file(path: Path, kind: str, seconds: float | None = None) -> tuple[float, float] | None:
    """The focus of an image file, or of a video (looked at a quarter of the way in). None when the file cannot be read."""
    try:
        if kind == "image":
            with Image.open(path) as im:
                return focus_of_image(im.convert("RGB"))
        at = max(0.0, (seconds or 0.0) * 0.25)
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=320:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, timeout=60)
        if p.returncode != 0 or not p.stdout:
            return None
        return focus_of_image(Image.open(io.BytesIO(p.stdout)).convert("RGB"))
    except Exception:  # noqa: BLE001  an unreadable picture just has no focus (it stays centred)
        return None
