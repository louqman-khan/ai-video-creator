"""FastAPI app: upload audio -> background pipeline -> poll progress -> download the video.

Run it with `avc serve`. The CLI keeps working on its own; this is a thin layer over Pipeline.
"""

from __future__ import annotations

import json
import logging
import tempfile
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.api import captions as captions_api
from app.api import media as media_api
from app.api import scenes as scenes_api
from app.api import timeline as timeline_api
from app.api.jobs import JobRunner, ProvidersFactory
from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.config import Settings, get_settings
from app.media import ffmpeg
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.runner import ASPECTS, Providers
import app.maintenance as maintenance
from app.api import avatars as avatars_api
from app.accounts import routes as auth_routes
from app.accounts.db import Accounts
from app.accounts.guard import Guard
from app.accounts.mailer import create_mailer
from app.accounts.quotas import Quotas
from app.accounts.ratelimit import RateLimiter
from app.pipeline import export_speed
from app.providers.tts import TTSUnavailable
from app.pipeline.sizes import PORTRAIT, render_size

log = logging.getLogger("avc.api")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
MAX_SCRIPT_CHARS = 100_000
# The same URL serves a different file after every re-render: browsers must revalidate (ETag) instead of
# reusing an old copy for minutes (heuristic freshness).
NO_STALE = {"Cache-Control": "no-cache"}


class ExportRequest(BaseModel):
    aspect: Literal["16:9", "9:16", "1:1", "4:5"] | None = None  # default: the project's own format
    preset: Literal["720p", "1080p", "4k"] = "1080p"  # size: the short side of the picture
    encoder: Literal["software", "hardware"] = "software"  # software: best quality per file size; hardware: several times faster, bigger files
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
        landscape = options.get("aspect", "16:9") not in PORTRAIT
        return Providers(shared["transcriber"], shared["planner"], shared["search"],
                         create_ranker(settings, landscape), create_cleaner(settings))

    return factory


def _safe_name(filename: str) -> str:
    stem = Path(filename or "project").stem
    return re.sub(r"[^\w\- ]+", "", stem).strip()[:60] or "project"


def _backfill_durations(store: ProjectStore) -> None:
    """Projects made before the card showed a length get it from their preview video (cheap; once)."""
    from app.media import ffmpeg

    for p in store.list():
        f = store.path(p.id) / "preview.mp4"
        if p.video_ready and p.duration is None and f.is_file():
            try:
                store.update(p.id, duration=round(ffmpeg.probe_duration(f), 1))
            except Exception:  # noqa: BLE001  a broken file just has no length
                continue


def create_app(settings: Settings | None = None, providers_factory: ProvidersFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = ProjectStore(Path(settings.projects_dir))
    jobs = JobRunner(store, settings, providers_factory or default_providers_factory())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _backfill_durations(store)
        n = store.recover_interrupted()
        if n:
            log.warning("marked %d interrupted project(s) as failed", n)
        yield
        jobs.shutdown()
        app.state.media.shutdown()

    hosted = settings.mode == "hosted"
    accounts = Accounts(settings) if hosted else None
    quotas = Quotas(settings, store) if hosted else None
    limiter = RateLimiter()
    guard = Guard(settings, store, accounts, quotas, limiter)
    app = FastAPI(title="AI Video Creator", version="0.1.0", lifespan=lifespan, dependencies=[Depends(guard)])
    origins = [] if hosted else [o.strip() for o in settings.cors_origins.split(",") if o.strip()]  # the hosted site is one origin: no other site may talk to it
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.state.store, app.state.jobs = store, jobs
    app.include_router(auth_routes.build_router(settings, store, accounts, quotas, create_mailer(settings) if hosted else None, limiter))
    if not hosted:
        from app.api import setup as setup_routes

        app.include_router(setup_routes.build_router(settings))

    if hosted:
        secure = settings.public_url.startswith("https://")
        csp = ("default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
               "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

        @app.middleware("http")
        async def security_headers(request, call_next):
            response = await call_next(request)
            response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                                     "Permissions-Policy": "camera=(), microphone=(), geolocation=()", "Content-Security-Policy": csp})
            if secure:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

    def owner_of(request: Request) -> str | None:
        """The account that owns what is being made (hosted mode); None for the single local user."""
        return request.state.user.id if hosted else None

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
            "mode": settings.mode,
            "speech": jobs.tts.languages(),  # languages a typed script can be spoken in
            "speech_paid": bool(getattr(jobs.tts, "paid", False)),  # the voice is a paid outside service
            "hardware_encoder": ffmpeg.hardware_encoder() is not None,
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
        request: Request,
        file: UploadFile | None = File(None, description="Narration audio (leave out to have the script spoken)"),
        name: str = Form(""),
        language: str = Form("", description="en, ur, or empty for auto-detect"),
        aspect: str = Form("16:9"),
        script: str = Form("", description="Optional known script; captions use its exact words. Without audio it is spoken by a synthetic voice"),
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
        speak = file is None or not (file.filename or "")
        ext = ".wav" if speak else Path(file.filename or "").suffix.lower()
        if speak:
            if not script.strip():
                raise HTTPException(422, "Upload an audio file, or type the script to have it spoken.")
            if language not in ("en", "ur"):
                raise HTTPException(422, "Choose English or Urdu: the voice needs to know which language to speak.")
            if language not in jobs.tts.languages():
                try:
                    jobs.tts.synthesize("x", language, Path(tempfile.gettempdir()) / "avc_probe.wav")
                except TTSUnavailable as e:
                    raise HTTPException(422, str(e)) from None
        elif ext not in AUDIO_EXTENSIONS:
            raise HTTPException(415, f"Unsupported file type '{ext}'. Use: {', '.join(sorted(AUDIO_EXTENSIONS))}")
        style_dict = None
        if style.strip():
            try:
                style_dict = CaptionStyle.model_validate_json(style).model_dump(exclude_none=True)
            except ValidationError as e:
                raise HTTPException(422, f"Invalid caption style: {e.errors()[0]['msg']}") from None

        info = store.create(
            name.strip()[:80] or (" ".join(script.split()[:6])[:80] if speak else _safe_name(file.filename or "")),
            original_filename="" if speak else (file.filename or "")[:200], audio_file="narration.wav" if speak else f"upload{ext}",
            language=language or None, aspect=aspect, owner=owner_of(request),
            options={"language": language or None, "remove_silence": remove_silence, "min_gap": min_gap,
                     "clean": clean and not speak, "normalize": normalize, "lufs": lufs, "captions": captions,
                     "style": style_dict, **({"speak": True} if speak else {})},
        )
        d = store.path(info.id)
        try:
            if not speak:
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
    def list_projects(request: Request) -> list[ProjectInfo]:
        return store.list(owner=owner_of(request))

    @app.get("/api/projects/{pid}", response_model=ProjectInfo)
    def project(pid: str) -> ProjectInfo:
        return get_project(pid)

    @app.get("/api/projects/{pid}/video")
    def video(pid: str) -> FileResponse:
        info = get_project(pid)
        d = store.path(pid)
        # the fast preview if there is one; projects made before previews existed only have output.mp4
        f = next((p for p in (d / "preview.mp4", d / "output.mp4") if p.is_file()), None)
        if not (info.video_ready and f):
            raise HTTPException(409, "The video is not ready yet")
        return FileResponse(f, media_type="video/mp4", filename=f"{_safe_name(info.name)}-preview.mp4",
                            headers=NO_STALE)

    @app.post("/api/projects/{pid}/export", status_code=202, response_model=ProjectInfo)
    def start_export(pid: str, body: ExportRequest | None = None) -> ProjectInfo:
        """Render the full-quality 1080p video (16:9 or 9:16). Edits use the fast preview instead."""
        info = get_project(pid)
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")
        d = store.path(pid)
        if not ((d / "scenes.json").is_file() and (d / "assets.json").is_file()):
            raise HTTPException(409, "The project is not ready to export")
        aspect = (body.aspect if body else None) or info.aspect
        preset = body.preset if body else "1080p"
        encoder = body.encoder if body else "software"
        if encoder == "hardware" and ffmpeg.hardware_encoder() is None:
            raise HTTPException(422, "This computer has no hardware video encoder. Use the software encoder.")
        queued = store.update(pid, status="queued", stage="export", progress=0.0, message="Preparing the export",
                              error=None, export_ready=False)
        jobs.submit(pid, export_aspect=aspect, export_preset=preset, export_encoder=encoder)
        return queued

    @app.get("/api/storage")
    def storage(days: float = 7.0) -> dict:
        """Disk use by category and how much a clean-up could free (`days`: only things unused for that long)."""
        items = maintenance.survey(settings, days, segments=True)
        return {"items": [{"key": i.key, "label": i.label, "bytes": i.bytes, "reclaimable": i.reclaimable} for i in items],
                "total": sum(i.bytes for i in items), "reclaimable": sum(i.reclaimable for i in items)}

    @app.post("/api/storage/clean")
    def storage_clean(days: float = 7.0, segments: bool = False) -> dict:
        if any(p.status in ("queued", "running") for p in store.list()):
            raise HTTPException(409, "Something is being processed right now. Try again when it has finished.")
        return maintenance.clean(settings, days, segments)

    @app.get("/api/projects/{pid}/export/estimate")
    def export_estimate(pid: str, preset: Literal["720p", "1080p", "4k"] = "1080p", encoder: Literal["software", "hardware"] = "software",
                        aspect: Literal["16:9", "9:16", "1:1", "4:5"] | None = None) -> dict:
        """About how long an export will take on this computer (learns from the exports it has done)."""
        info = get_project(pid)
        d = store.path(pid)
        tl = timeline_api.convert.load(d)
        seconds = tl.duration / tl.fps if tl else 0.0
        if not seconds:
            try:
                scenes = json.loads((d / "scenes.json").read_text("utf-8"))
                seconds = max((float(s.get("end", 0)) for s in scenes), default=0.0)
            except (OSError, ValueError):
                seconds = 0.0
        w, h = render_size(aspect or info.aspect, "final", preset)
        return {**export_speed.estimate(settings.work_dir, encoder, preset, aspect or info.aspect, seconds), "width": w, "height": h}

    @app.get("/api/projects/{pid}/export")
    def download_export(pid: str) -> FileResponse:
        info = get_project(pid)
        f = store.path(pid) / "output.mp4"
        if not (info.export_ready and f.is_file()):
            raise HTTPException(409, "No export yet. Start one first, or the edits changed since the last export.")
        return FileResponse(f, media_type="video/mp4", headers=NO_STALE,
                            filename=f"{_safe_name(info.name)}-{info.export_aspect or info.aspect}.mp4".replace(":", "x"))

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

    scenes_api.register(app, store, jobs, settings)
    captions_api.register(app, store, jobs, settings)
    media_worker = media_api.MediaWorker(settings)
    timeline_api.register(app, store, settings, on_built=media_worker.ensure_timeline, jobs=jobs)
    media_api.register(app, store, settings, media_worker)
    avatars_api.register(app, store, settings, jobs, media_worker)
    app.state.media = media_worker

    dist = Path(settings.frontend_dist)
    if (dist / "index.html").is_file():  # the built web app is served by the same process: `avc app`, the desktop app and the one-folder installs need nothing else
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def web_app(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Not found")
            target = (root / path).resolve()
            if path and target.is_file() and target.is_relative_to(root):  # files of the app itself only, never anything outside its folder
                hashed = "/assets/" in f"/{path}"
                return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable" if hashed else "no-cache"})
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})  # deep links (/projects/abc) belong to the app's own router

    return app
