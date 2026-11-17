"""Downloading the model files the app uses (speech recognition, noise removal, picture ranking): one place for the command line (`avc fetch-models`)
and for the first-run set-up screen of the desktop app."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.http import make_client

RNNOISE_URL = "https://raw.githubusercontent.com/GregorR/rnnoise-models/master/conjoined-burgers-2018-08-28/cb.rnnn"
CLIP_BASE = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
CLIP_FILES = (("onnx/vision_model_quantized.onnx", "vision_model_quantized.onnx"), ("onnx/text_model_quantized.onnx", "text_model_quantized.onnx"),
              ("tokenizer.json", "tokenizer.json"), ("preprocessor_config.json", "preprocessor_config.json"))
WHISPER_SIZES_MB = {"tiny": 75, "base": 145, "small": 465, "medium": 1500, "large-v3": 3000}

Progress = Callable[[str], None]


class ModelError(RuntimeError):
    pass


def whisper_ready(model: str) -> bool:
    """True when the faster-whisper model is already in the local cache (so loading it needs no network)."""
    hub = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    for repo in (f"models--Systran--faster-whisper-{model}", f"models--guillaumekln--faster-whisper-{model}"):
        for snap in (hub / repo / "snapshots").glob("*") if (hub / repo / "snapshots").is_dir() else []:
            if (snap / "model.bin").exists():
                return True
    return False


def rnnoise_ready(s: Settings) -> bool:
    return (Path(s.models_dir) / s.rnnoise_model).is_file()


def clip_ready(s: Settings) -> bool:
    return all((Path(s.clip_dir) / name).is_file() for _, name in CLIP_FILES[:3])


def fetch_rnnoise(s: Settings, say: Progress = lambda m: None) -> Path:
    dst = Path(s.models_dir) / s.rnnoise_model
    dst.parent.mkdir(parents=True, exist_ok=True)
    say("Downloading the noise-removal model ...")
    with make_client() as c:
        r = c.get(RNNOISE_URL)
        if r.is_error:
            raise ModelError(f"Download failed: HTTP {r.status_code}")
    dst.write_bytes(r.content)
    return dst


def fetch_clip(s: Settings, say: Progress = lambda m: None) -> list[Path]:
    folder = Path(s.clip_dir)
    folder.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for remote, name in CLIP_FILES:
        target = folder / name
        if target.is_file() and target.stat().st_size > 0:
            out.append(target)
            continue
        say(f"Downloading {name} ...")
        part = target.with_suffix(target.suffix + ".part")
        with make_client(read_timeout=120.0) as c, c.stream("GET", CLIP_BASE + remote) as r:
            if r.is_error:
                raise ModelError(f"Download of {name} failed: HTTP {r.status_code}")
            with part.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        part.replace(target)
        out.append(target)
    return out


def fetch_whisper(model: str, say: Progress = lambda m: None) -> None:
    say(f"Downloading the speech-recognition model '{model}' (about {WHISPER_SIZES_MB.get(model, 500)} MB) ...")
    try:
        from faster_whisper.utils import download_model

        download_model(model)
    except Exception as e:  # noqa: BLE001  network, disk, unknown model name: one sentence for the person
        raise ModelError(f"Could not download the speech model: {type(e).__name__}: {str(e)[:150]}") from None
