"""Face detection for smart crop: Ultra-Light-Fast-Generic-Face-Detector (RFB-320, MIT licence, 1.2 MB ONNX) through onnxruntime.
The model file is optional (`avc fetch-models --faces`, or the Setup page): without it the focus falls back to saliency."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image

_sessions: dict[str, object] = {}
_lock = threading.Lock()
W, H = 320, 240


def _session(path: Path):
    key = str(path)
    with _lock:
        if key not in _sessions:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.log_severity_level = 3  # the model file triggers harmless warnings
            _sessions[key] = ort.InferenceSession(key, so, providers=["CPUExecutionProvider"])
        return _sessions[key]


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_max: float = 0.3) -> list[int]:
    order = list(np.argsort(-scores))
    keep: list[int] = []
    while order:
        i = order.pop(0)
        keep.append(i)
        rest = []
        for j in order:
            x0, y0 = max(boxes[i, 0], boxes[j, 0]), max(boxes[i, 1], boxes[j, 1])
            x1, y1 = min(boxes[i, 2], boxes[j, 2]), min(boxes[i, 3], boxes[j, 3])
            inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            area = lambda b: max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])  # noqa: E731
            if inter / (area(boxes[i]) + area(boxes[j]) - inter + 1e-9) <= iou_max:
                rest.append(j)
        order = rest
    return keep


def decode(scores: np.ndarray, boxes: np.ndarray, threshold: float = 0.95) -> list[tuple[float, float, float, float, float]]:
    """Model output -> [(x0, y0, x1, y1, score)] as fractions of the picture, after non-maximum suppression."""
    s = scores.reshape(-1, 2)[:, 1]
    b = boxes.reshape(-1, 4)
    m = s > threshold
    if not m.any():
        return []
    s, b = s[m], np.clip(b[m], 0.0, 1.0)
    return [(*map(float, b[i]), float(s[i])) for i in _nms(b, s)]


def detect(img: Image.Image, model: Path, threshold: float = 0.95) -> list[tuple[float, float, float, float, float]]:
    rgb = img.convert("RGB").resize((W, H), Image.BILINEAR)
    x = ((np.asarray(rgb, dtype=np.float32) - 127.0) / 128.0).transpose(2, 0, 1)[None]
    scores, boxes = _session(model).run(None, {"input": x})  # type: ignore[attr-defined]
    return decode(scores, boxes, threshold)


def focus_from_faces(faces: list[tuple[float, float, float, float, float]]) -> tuple[float, float] | None:
    """The centre of the faces, each weighted by its size (a big face in front matters more than small ones behind)."""
    if not faces:
        return None
    w = np.array([(f[2] - f[0]) * (f[3] - f[1]) * f[4] for f in faces])
    if w.sum() <= 0:
        return None
    cx = np.array([(f[0] + f[2]) / 2 for f in faces])
    cy = np.array([(f[1] + f[3]) / 2 for f in faces])
    return round(float(min(0.95, max(0.05, (cx * w).sum() / w.sum()))), 3), round(float(min(0.95, max(0.05, (cy * w).sum() / w.sum()))), 3)
