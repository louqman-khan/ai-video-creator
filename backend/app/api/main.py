"""FastAPI app: upload audio -> background pipeline -> poll progress -> download the video.

Run it with `avc serve`. The CLI keeps working on its own; this is a thin layer over Pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.api.jobs import JobRunner, ProvidersFactory
from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.config import Settings, get_settings
from app.media import ffmpeg
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.runner import ASPECTS, Providers

log = logging.getLogger("avc.api")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
MAX_SCRIPT_CHARS = 100_000
CHUNK = 1024 * 1024


def default_providers_factory() -> ProvidersFactory:
    """Real providers. The heavy parts (Whisper model, planner, search) are built once and shared."""
    from app.providers.audio_cleaner import create_cleaner
    from app.providers.media_ranker import create_ranker
    from app.providers.media_search import create_search
    from app.providers.scene_planner import create_planner
    from app.providers.transcriber import create_transcriber

    lock, shared = threading.Lock(), {}

    def factory(settings: Settings, options: dict) -> Providers:
        with lock:
            if not shared:
                shared.update(transcriber=create_transcriber(settings), planner=create_planner(settings),
                              search=create_search(settings))
        landscape = options.get("aspect", "16:9") != "9:16"
        return Providers(shared["transcriber"], shared["planner"], shared["search"],
                         create_ranker(settings, landscape), create_cleaner(settings))

    return factory


def _safe_name(filename: str) -> str:
    stem = Path(filename or "project").stem
    return re.sub(r"[^\w\- ]+", "", stem).strip()[:60] or "project"


def create_app(settings: Settings | None = None, providers_factory: ProvidersFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = ProjectStore(Path(settings.projects_dir))
    jobs = JobRunner(store, settings, providers_factory or default_providers_factory())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        n = store.recover_interrupted()
        if n:
            log.warning("marked %d interrupted project(s) as failed", n)
        yield
        jobs.shutdown()

    app = FastAPI(title="AI Video Creator", version="0.1.0", lifespan=lifespan)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.state.store, app.state.jobs = store, jobs

    def get_project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "ffmpeg": ffmpeg.has_tools(),
            # the UI validates against the same limits the server enforces
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "max_audio_minutes": settings.max_audio_minutes,
                "max_script_chars": MAX_SCRIPT_CHARS,
                "extensions": sorted(AUDIO_EXTENSIONS),
            },
        }

    @app.post("/api/projects", status_code=202, response_model=ProjectInfo)
    async def create_project(
        file: UploadFile = File(..., description="Narration audio"),
        name: str = Form(""),
        language: str = Form("", description="en, ur, or empty for auto-detect"),
        aspect: str = Form("16:9"),
        script: str = Form("", description="Optional known script; captions use its exact words"),
        remove_silence: bool = Form(False),
        min_gap: float | None = Form(None, ge=0.5, le=10),
        clean: bool = Form(True),
        normalize: bool = Form(True),
        lufs: float | None = Form(None, ge=-30, le=-5),
        captions: bool = Form(True),
        style: str = Form("", description="Caption style as JSON"),
    ) -> ProjectInfo:
        if aspect not in ASPECTS:
            raise HTTPException(422, f"aspect must be one of {', '.join(ASPECTS)}")
        if language not in ("", "en", "ur"):
            raise HTTPException(422, "language must be 'en', 'ur' or empty (auto-detect)")
        if len(script) > MAX_SCRIPT_CHARS:
            raise HTTPException(413, "Script is too long")
        ext = Path(file.filename or "").suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            raise HTTPException(415, f"Unsupported file type '{ext}'. Use: {', '.join(sorted(AUDIO_EXTENSIONS))}")
        style_dict = None
        if style.strip():
            try:
                style_dict = CaptionStyle.model_validate_json(style).model_dump(exclude_none=True)
            except ValidationError as e:
                raise HTTPException(422, f"Invalid caption style: {e.errors()[0]['msg']}") from None

        info = store.create(
            name.strip()[:80] or _safe_name(file.filename or ""),
            original_filename=(file.filename or "")[:200], audio_file=f"upload{ext}",
            language=language or None, aspect=aspect,
            options={"language": language or None, "remove_silence": remove_silence, "min_gap": min_gap,
                     "clean": clean, "normalize": normalize, "lufs": lufs, "captions": captions,
                     "style": style_dict},
        )
        d = store.path(info.id)
        try:
            size, limit = 0, settings.max_upload_mb * 1024 * 1024
            with (d / info.audio_file).open("wb") as out:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
                    out.write(chunk)
            try:  # a real, readable audio file of acceptable length?
                seconds = await run_in_threadpool(ffmpeg.probe_duration, d / info.audio_file)
            except ffmpeg.FfmpegError:
                raise HTTPException(400, "This file could not be read as audio") from None
            if seconds > settings.max_audio_minutes * 60:
                raise HTTPException(413, f"Audio is longer than {settings.max_audio_minutes:g} minutes")
            if script.strip():
                (d / "script.txt").write_text(script, "utf-8")
        except Exception:
            store.delete(info.id)  # never keep a half-created project
            raise
        jobs.submit(info.id)
        return store.get(info.id)

    @app.get("/api/projects", response_model=list[ProjectInfo])
    def list_projects() -> list[ProjectInfo]:
        return store.list()

    @app.get("/api/projects/{pid}", response_model=ProjectInfo)
    def project(pid: str) -> ProjectInfo:
        return get_project(pid)

    @app.get("/api/projects/{pid}/video")
    def video(pid: str) -> FileResponse:
        info = get_project(pid)
        f = store.path(pid) / "output.mp4"
        if not (info.video_ready and f.is_file()):
            raise HTTPException(409, "The video is not ready yet")
        return FileResponse(f, media_type="video/mp4", filename=f"{_safe_name(info.name)}.mp4")

    @app.get("/api/projects/{pid}/credits")
    def credits(pid: str) -> FileResponse:
        get_project(pid)
        f = store.path(pid) / "CREDITS.txt"
        if not f.is_file():
            raise HTTPException(409, "Credits are not ready yet")
        return FileResponse(f, media_type="text/plain; charset=utf-8")

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: str) -> None:
        info = get_project(pid)
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")
        store.delete(pid)

    return app
