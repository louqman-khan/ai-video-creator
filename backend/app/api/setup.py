"""First-run set-up for the installed desktop app: API keys and model downloads. Local mode only (hosted installs are configured by the operator).

Keys are written to <AVC_DATA>/.env (owner-only) and never sent back to the browser: the status only says whether each is set."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.config import Settings
from app.media import models

log = logging.getLogger("avc.setup")
_KEY = re.compile(r"^[A-Za-z0-9_\-\.]{8,200}$")  # keys are plain tokens: refusing anything else also rules out newlines in the .env file
KEYS = {"gemini_api_key": "GEMINI_API_KEY", "pixabay_api_key": "PIXABAY_API_KEY"}


class KeysIn(BaseModel):
    gemini_api_key: str | None = None
    pixabay_api_key: str | None = None


class ModelsIn(BaseModel):
    whisper: str | None = None  # a size from models.WHISPER_SIZES_MB
    clip: bool = True


def env_path(s: Settings) -> Path:
    return (config.DATA or config.ROOT) / ".env"


def write_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text("utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip()
        if k in updates:
            if k not in seen:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    from app import fsutil
    fsutil.replace(tmp, path)


def build_router(settings: Settings) -> APIRouter:
    r = APIRouter(prefix="/api/setup", tags=["setup"])
    state = {"running": False, "message": "", "error": None}
    lock = threading.Lock()

    def status() -> dict:
        from app.media import ffmpeg
        ff = ffmpeg.has_tools()
        return {
            "ffmpeg": ff,
            "keys": {k: bool(getattr(settings, k)) for k in KEYS},
            "models": {"whisper": models.whisper_ready(settings.whisper_model), "whisper_model": settings.whisper_model,
                       "rnnoise": models.rnnoise_ready(settings), "clip": models.clip_ready(settings), "face": models.face_ready(settings)},
            "whisper_sizes_mb": models.WHISPER_SIZES_MB,
            "download": dict(state),
            "data_dir": str(config.DATA) if config.DATA else None,
        }

    @r.get("")
    def get_status() -> dict:
        return status()

    @r.put("/keys")
    def put_keys(body: KeysIn) -> dict:
        updates: dict[str, str] = {}
        for field, env in KEYS.items():
            v = getattr(body, field)
            if v is None:
                continue
            v = v.strip()
            if v and not _KEY.match(v):
                raise HTTPException(422, f"That doesn't look like a valid {env.split('_')[0].title()} key (letters, digits, - _ . only).")
            updates[env] = v
        if updates:
            write_env(env_path(settings), updates)
            for field, env in KEYS.items():
                if env in updates:
                    setattr(settings, field, updates[env])
        return status()

    @r.post("/models", status_code=202)
    def post_models(body: ModelsIn) -> dict:
        size = body.whisper or settings.whisper_model
        if size not in models.WHISPER_SIZES_MB:
            raise HTTPException(422, f"Unknown speech model '{size}'.")
        with lock:
            if state["running"]:
                raise HTTPException(409, "A download is already running.")
            state.update(running=True, message="Starting ...", error=None)

        def work() -> None:
            say = lambda m: state.update(message=m)  # noqa: E731
            try:
                models.fetch_rnnoise(settings, say)
                models.fetch_face(settings, say)
                if body.clip:
                    models.fetch_clip(settings, say)
                if not models.whisper_ready(size):
                    say(f"Downloading the speech model '{size}' (about {models.WHISPER_SIZES_MB[size]} MB) ...")
                    models.fetch_whisper(size, say)
                if size != settings.whisper_model:
                    write_env(env_path(settings), {"WHISPER_MODEL": size})
                    settings.whisper_model = size
                state["message"] = "Done."
            except Exception as e:  # noqa: BLE001
                log.warning("model download failed: %s", e)
                state["error"] = str(e) if isinstance(e, models.ModelError) else "Download failed. Check the internet connection and try again."
            finally:
                state["running"] = False

        threading.Thread(target=work, daemon=True, name="model-download").start()
        return status()

    return r
