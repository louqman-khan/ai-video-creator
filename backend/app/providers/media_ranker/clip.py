"""CLIP ranker: how well does each candidate's picture match what the scene is about?

OpenAI CLIP ViT-B/32 (MIT licence), the int8-quantised ONNX files made by Xenova, run with onnxruntime on the CPU: no PyTorch.
The candidate's small preview picture (`thumb_url`) is embedded once and remembered on disk; the scene's query is embedded as text;
the score is the cosine similarity. It is added to the heuristic score (resolution, orientation, duration, ...), so everything the
heuristic knows still counts and a candidate without a usable preview simply keeps its heuristic score."""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import numpy as np

from app.http import make_client
from app.models import MediaAsset, Scene

from .heuristic import HeuristicRanker

log = logging.getLogger("avc.clip")
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
FILES = ("vision_model_quantized.onnx", "text_model_quantized.onnx", "tokenizer.json")
MAX_PREVIEW_BYTES = 8 * 1024 * 1024


def models_present(folder: Path) -> bool:
    return all((folder / f).is_file() for f in FILES)


class ClipRanker:
    def __init__(self, folder: Path, cache_dir: Path | None = None, landscape: bool = True, weight: float = 100.0) -> None:
        self.folder, self.cache_dir, self.weight = folder, cache_dir, weight
        self.heuristic = HeuristicRanker(landscape)
        self._vision = self._text = self._tok = None
        self._lock = Lock()  # onnxruntime sessions are fine to share; loading them is not
        self._client = None
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- models
    def _load(self) -> None:
        with self._lock:
            if self._vision is not None:
                return
            import onnxruntime as ort
            from tokenizers import Tokenizer

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            self._vision = ort.InferenceSession(str(self.folder / FILES[0]), opts, providers=["CPUExecutionProvider"])
            self._text = ort.InferenceSession(str(self.folder / FILES[1]), opts, providers=["CPUExecutionProvider"])
            self._tok = Tokenizer.from_file(str(self.folder / FILES[2]))
            self._tok.no_padding()
            self._tok.enable_truncation(77)

    def embed_text(self, text: str) -> np.ndarray:
        self._load()
        ids = np.asarray([self._tok.encode(text.strip() or "a picture").ids], dtype=np.int64)  # type: ignore[union-attr]
        out = self._text.run(None, {"input_ids": ids})[0][0]  # type: ignore[union-attr]
        return _unit(out)

    def embed_image(self, data: bytes) -> np.ndarray:
        from PIL import Image

        self._load()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        s = 224 / min(w, h)
        img = img.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
        w, h = img.size
        left, top = (w - 224) // 2, (h - 224) // 2
        arr = (np.asarray(img.crop((left, top, left + 224, top + 224)), dtype=np.float32) / 255.0 - MEAN) / STD
        out = self._vision.run(None, {"pixel_values": arr.transpose(2, 0, 1)[None]})[0][0]  # type: ignore[union-attr]
        return _unit(out)

    # ---- candidates
    def _cache_file(self, asset: MediaAsset) -> Path | None:
        return self.cache_dir / f"{hashlib.sha1(asset.id.encode()).hexdigest()[:20]}.npy" if self.cache_dir else None

    def _preview(self, asset: MediaAsset) -> bytes | None:
        url = asset.thumb_url or (asset.url if asset.kind == "image" else "")
        if not url:
            return None
        if url.startswith("file:"):
            p = Path(url2pathname(unquote(urlparse(url).path)))
            return p.read_bytes() if p.is_file() and p.stat().st_size <= MAX_PREVIEW_BYTES else None
        if not url.startswith(("http://", "https://")):
            return None
        self._client = self._client or make_client(read_timeout=10.0)
        r = self._client.get(url)
        return r.content if r.status_code == 200 and len(r.content) <= MAX_PREVIEW_BYTES else None

    def image_embedding(self, asset: MediaAsset) -> np.ndarray | None:
        cache = self._cache_file(asset)
        if cache and cache.is_file():
            try:
                return np.load(cache)
            except (OSError, ValueError):
                cache.unlink(missing_ok=True)
        try:
            data = self._preview(asset)
            emb = self.embed_image(data) if data else None
        except Exception as e:  # noqa: BLE001  one unreadable preview must not stop the ranking
            log.info("no CLIP score for %s: %s", asset.id, type(e).__name__)
            return None
        if emb is not None and cache:
            np.save(cache, emb)
        return emb

    def similarities(self, text: str, candidates: list[MediaAsset]) -> list[float | None]:
        """Cosine similarity of each candidate's picture with the text (None: no usable preview)."""
        q = self.embed_text(text)
        with ThreadPoolExecutor(max_workers=6) as pool:  # previews are small downloads: fetch them side by side
            embs = list(pool.map(self.image_embedding, candidates))
        return [None if e is None else float(np.dot(q, e)) for e in embs]

    def rank(self, scene: Scene, candidates: list[MediaAsset], *, used: Collection[str] = ()) -> list[MediaAsset]:
        if not candidates:
            return []
        text = scene.query_en or scene.text
        try:
            sims = self.similarities(text, candidates)
        except Exception as e:  # noqa: BLE001  a broken model must not break the pipeline: fall back to the heuristic
            log.warning("CLIP ranking failed (%s): using the heuristic only", type(e).__name__)
            return self.heuristic.rank(scene, candidates, used=used)
        scored = []
        for i, (a, sim) in enumerate(zip(candidates, sims)):
            s = self.heuristic._score(scene, a, used) - i * 0.01  # noqa: SLF001
            if sim is not None:
                s += self.weight * sim
            scored.append((s, a))
        return [a for _, a in sorted(scored, key=lambda t: -t[0])]


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    return v / (float(np.linalg.norm(v)) or 1.0)
