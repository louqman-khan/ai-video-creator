"""Media for the timeline editor (task 4.2): uploads, background preparation of derived files
(proxies, waveform, filmstrip) and the endpoints that serve them.

Assets are append-only on the timeline: adding one never changes the revision, so it can never make
somebody's unsaved edit conflict. Uploaded files are stored under a server-chosen name; the user's file
name is only kept as a (sanitised) title."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from typing import Literal

from pydantic import BaseModel, Field

from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.api.timeline import load_or_build
from app.config import Settings
from app.media import derive, ffmpeg, ingest
from app.media.ingest import Limits, MediaInfo, MediaRejected
from app.timeline import convert
from app.api.scenes import AssetView
from app.media.cache import MediaCache
from app.models import MediaAsset
from app.providers.media_search import create_search
from app.providers.media_search.openverse import OpenverseSearch
from app.timeline.models import Asset, AssetOut, Timeline

log = logging.getLogger("avc.media")
CHUNK = 1024 * 1024
_ROLES = {  # role -> (media type)
    "proxy": None, "audio": "audio/mp4", "peaks": "application/json", "film": "image/jpeg", "film_meta": "application/json",
}
_PROXY_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png"}


class MediaView(BaseModel):
    asset_id: str
    kind: str
    title: str
    status: str  # pending | processing | ready | failed
    stage: str = ""
    error: str | None = None
    uploaded: bool
    duration: float | None = None  # seconds
    width: int = 0
    height: int = 0
    fps: float | None = None
    vfr: bool = False
    rotation: int = 0
    hdr: bool = False
    has_audio: bool = False
    derived: list[str] = []  # roles that exist: proxy, audio, peaks, film
    bytes: int = 0  # size of the derived files


class DiskUsage(BaseModel):
    project_bytes: int  # the project's own folder (renders, uploads, working files)
    uploads_bytes: int  # part of the above
    derived_bytes: int  # proxies/waveforms/filmstrips of its assets (shared cache)
    total_bytes: int


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


class MediaWorker:
    """Prepares derived files in the background (one at a time: ffmpeg is CPU heavy)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.proxy_dir) if settings.proxy_dir else Path(settings.work_dir) / "cache" / "proxies"
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avc-media")
        self._inflight: dict[str, str] = {}  # key -> current stage
        self._lock = threading.Lock()

    # ---- state on disk -------------------------------------------------------------------
    def key_dir(self, path: Path) -> Path:
        return self.root / derive.asset_key(path)

    def _state(self, path: Path) -> dict | None:
        try:
            return json.loads((self.key_dir(path) / "state.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def status(self, path: Path) -> tuple[str, str, dict | None]:
        """(status, stage-or-error, state)"""
        if not path.is_file():
            return "failed", "the media file is missing", None
        key = derive.asset_key(path)
        with self._lock:
            if key in self._inflight:
                return "processing", self._inflight[key], None
        st = self._state(path)
        if st and st.get("version") == derive.VERSION:
            files = st.get("files", {})
            if st.get("status") == "ready" and all((self.key_dir(path) / n).is_file() for n in files.values()):
                return "ready", "", st
            if st.get("status") == "failed":
                return "failed", st.get("error", "failed"), st
        return "pending", "", None

    # ---- work ----------------------------------------------------------------------------
    def ensure(self, path: Path, retry_failed: bool = False) -> None:
        """Make sure the derived files exist (idempotent; does nothing if ready or already running)."""
        if not path.is_file():
            return
        status, _, _ = self.status(path)
        if status in ("ready", "processing") or (status == "failed" and not retry_failed):
            return
        key = derive.asset_key(path)
        with self._lock:
            if key in self._inflight:
                return
            self._inflight[key] = "queued"
        self._pool.submit(self._work, path, key)

    def ensure_timeline(self, _pid: str, tl: Timeline) -> None:
        for a in tl.assets.values():
            self.ensure(Path(a.path))

    def _set_stage(self, key: str, stage: str) -> None:
        with self._lock:
            if key in self._inflight:
                self._inflight[key] = stage

    def _work(self, path: Path, key: str) -> None:
        out = self.root / key
        state: dict = {"version": derive.VERSION}
        try:
            family = (ingest.sniff(path) or (None, None))[1]
            info = ingest.probe(path, family)
            files = derive.derive_all(path, info, out, on_step=lambda s: self._set_stage(key, s))
            state.update(status="ready", files=files, info=info.model_dump(),
                         bytes=sum((out / n).stat().st_size for n in files.values()))
        except Exception as e:  # noqa: BLE001  one broken file must not stop the worker
            log.warning("preparing %s failed: %s", path.name, e)
            msg = str(e) if isinstance(e, (MediaRejected, ValueError)) else "this file could not be processed"
            state.update(status="failed", error=msg[:300], files={})
        finally:
            out.mkdir(parents=True, exist_ok=True)
            (out / "state.json").write_text(json.dumps(state), "utf-8")
            with self._lock:
                self._inflight.pop(key, None)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def reject_oversize(request: Request, limit_bytes: int) -> None:
    """Refuse an announced-too-large body before reading it (Starlette spools uploads to disk first)."""
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        length = 0
    if length > limit_bytes + 64 * 1024:
        raise HTTPException(413, "File is too large")


def _title(filename: str) -> str:
    return (re.sub(r"[^\w\- .()]+", "", Path(filename or "media").stem).strip()[:80]) or "media"


class BinAdd(BaseModel):
    asset_id: str = Field(..., max_length=200)


def build_router(store: ProjectStore, settings: Settings, worker: MediaWorker) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{pid}")
    limits = Limits(settings.max_media_minutes, settings.max_image_megapixels, settings.max_media_fps)

    def project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    def timeline_of(pid: str, info: ProjectInfo) -> Timeline:
        return load_or_build(store, settings, pid, info, True, worker.ensure_timeline)

    def asset_of(tl: Timeline, asset_id: str) -> Asset:
        a = tl.assets.get(asset_id)  # looked up by key: an id is never turned into a path
        if a is None:
            raise HTTPException(404, "Unknown media")
        return a

    def view(a: Asset) -> MediaView:
        path = Path(a.path)
        status, detail, st = worker.status(path)
        info = MediaInfo.model_validate(st["info"]) if st and st.get("info") else None
        files = (st or {}).get("files", {}) if status == "ready" else {}
        return MediaView(
            asset_id=a.id, kind=a.kind, title=a.title or a.id, status=status,
            stage=detail if status == "processing" else "", error=detail if status == "failed" else None,
            uploaded=a.id.startswith("upload:"),
            duration=info.duration if info else (a.duration / 30 if a.duration else None),
            width=info.width if info else a.width, height=info.height if info else a.height,
            fps=info.fps if info else None, vfr=bool(info and info.vfr), rotation=info.rotation if info else 0,
            hdr=bool(info and info.hdr), has_audio=bool(info and info.has_audio),
            derived=[r for r in ("proxy", "audio", "peaks", "film") if r in files], bytes=int((st or {}).get("bytes", 0)),
        )

    @router.get("/media", response_model=list[MediaView])
    def list_media(pid: str) -> list[MediaView]:
        info = project(pid)
        tl = timeline_of(pid, info)
        for a in tl.assets.values():
            worker.ensure(Path(a.path))  # self-healing: after a restart, anything still unprepared starts again
        return [view(a) for a in tl.assets.values()]

    @router.post("/media/prepare", status_code=202, response_model=list[MediaView])
    def prepare(pid: str) -> list[MediaView]:
        """(Re)start preparing every asset whose derived files are missing or failed."""
        info = project(pid)
        tl = timeline_of(pid, info)
        for a in tl.assets.values():
            worker.ensure(Path(a.path), retry_failed=True)
        return [view(a) for a in tl.assets.values()]

    @router.post("/media", status_code=201, response_model=MediaView)
    async def upload(
        pid: str, request: Request, file: UploadFile = File(...), rights_confirmed: bool = Form(False), title: str = Form(""),
    ) -> MediaView:
        info = project(pid)
        if not rights_confirmed:
            raise HTTPException(400, "Confirm that you have the right to use this file.")
        limit = settings.max_media_upload_mb * 1024 * 1024
        reject_oversize(request, limit)
        d = store.path(pid)
        updir = d / "uploads"
        updir.mkdir(exist_ok=True)
        if len(list(updir.iterdir())) >= settings.max_uploads_per_project:
            raise HTTPException(409, f"A project can hold at most {settings.max_uploads_per_project} uploaded files.")
        token = uuid.uuid4().hex[:12]
        part = updir / f"{token}.part"
        final: Path | None = None
        try:
            size = 0
            with part.open("wb") as out:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"File is larger than {settings.max_media_upload_mb} MB")
                    out.write(chunk)
            try:
                ext, minfo = await run_in_threadpool(ingest.inspect_file, part, limits)
            except MediaRejected as e:
                raise HTTPException(400, str(e)) from None
            final = updir / f"{token}.{ext}"  # server-chosen name and an extension from the real content
            part.replace(final)
            with store.lock:
                tl = timeline_of(pid, info)
                fps = tl.fps
                asset = Asset(
                    id=f"upload:{token}", kind=minfo.kind, path=str(final),
                    duration=None if minfo.kind == "image" else max(1, round((minfo.duration or 0) * fps)),
                    width=minfo.width, height=minfo.height, source="upload", license="User-provided",
                    attribution="User-provided media", title=(title.strip()[:80] or _title(file.filename or "")),
                )
                tl.assets[asset.id] = asset  # append-only: the revision does not change
                convert.save(d, tl)
        except BaseException:
            part.unlink(missing_ok=True)
            if final:
                final.unlink(missing_ok=True)
            raise
        worker.ensure(final)
        return view(asset)

    # ---- stock media for the bin (search, then add to the project); the browser only ever names an id this server offered

    candidates_file = lambda pid: store.path(pid) / "bin_candidates.json"  # noqa: E731

    @router.get("/bin/search", response_model=list[AssetView])
    async def bin_search(pid: str, q: str = Query(..., min_length=1, max_length=100),
                         kind: Literal["video", "image", "music", "sound"] = "video") -> list[AssetView]:
        info = project(pid)
        query = " ".join(q.split())
        if not query:
            raise HTTPException(422, "Type what to look for")
        orientation = "portrait" if info.aspect == "9:16" else "landscape"

        def search() -> list[MediaAsset]:
            if kind in ("music", "sound"):
                return OpenverseSearch().search_audio(query, "music" if kind == "music" else "sound_effect", limit=12)
            return create_search(settings).search(query, kind, orientation=orientation, limit=12)

        try:
            found = await run_in_threadpool(search)
        except Exception as e:  # noqa: BLE001 - the user needs a sentence, the log has the detail
            log.warning("bin search failed: %s", type(e).__name__)
            raise HTTPException(502, "The stock media source could not be reached. Try again in a moment.") from None
        f = candidates_file(pid)
        try:
            stored = json.loads(f.read_text("utf-8")) if f.is_file() else {}
        except ValueError:
            stored = {}
        stored.update({a.id: a.model_dump() for a in found})
        if len(stored) > 400:  # keep the newest
            stored = dict(list(stored.items())[-400:])
        f.write_text(json.dumps(stored), "utf-8")
        return [AssetView.of(a) for a in found]

    @router.post("/bin/add", status_code=201, response_model=AssetOut)
    async def bin_add(pid: str, body: BinAdd) -> AssetOut:
        info = project(pid)
        f = candidates_file(pid)
        try:
            stored = json.loads(f.read_text("utf-8")) if f.is_file() else {}
        except ValueError:
            stored = {}
        raw = stored.get(body.asset_id)
        if raw is None:
            raise HTTPException(400, "That item was not offered by a search. Search again and pick one from the results.")
        media = MediaAsset.model_validate(raw)
        with store.lock:
            existing = timeline_of(pid, info).assets.get(media.id)
        if existing is not None:
            return AssetOut.of(existing)

        def fetch() -> tuple[Path, float | None]:
            local = MediaCache(Path(settings.work_dir) / "cache" / "media").get(media)
            return local, (ffmpeg.probe_duration(local) if media.kind != "image" else None)

        try:
            local, seconds = await run_in_threadpool(fetch)
        except Exception as e:  # noqa: BLE001
            log.warning("bin add failed: %s", type(e).__name__)
            raise HTTPException(502, "That file could not be downloaded. Pick another one.") from None
        with store.lock:
            tl = timeline_of(pid, info)
            if media.id not in tl.assets:
                frames = None if seconds is None else max(1, round(seconds * tl.fps))
                tl.assets[media.id] = convert.asset_from_media(media, str(local), tl.fps, frames)  # append-only: no new revision
                convert.save(store.path(pid), tl)
            asset = tl.assets[media.id]
        worker.ensure(local)
        return AssetOut.of(asset)

    @router.delete("/media", status_code=204)
    def delete_media(pid: str, asset: str = Query(..., max_length=200)) -> None:
        info = project(pid)
        with store.lock:
            tl = timeline_of(pid, info)
            a = asset_of(tl, asset)
            if not a.id.startswith("upload:"):
                raise HTTPException(400, "Only files you uploaded can be removed.")
            if any(c.asset == a.id for c in tl.clips):
                raise HTTPException(409, "This file is used on the timeline. Remove its clips first.")
            del tl.assets[a.id]
            convert.save(store.path(pid), tl)
        path = Path(a.path)
        kd = worker.key_dir(path) if path.is_file() else None
        path.unlink(missing_ok=True)
        if kd and kd.is_dir():
            for f in kd.iterdir():
                f.unlink(missing_ok=True)
            kd.rmdir()

    def derived_file(pid: str, asset: str, role: str) -> FileResponse:
        info = project(pid)
        tl = timeline_of(pid, info)
        a = asset_of(tl, asset)
        path = Path(a.path)
        status, detail, st = worker.status(path)
        name = (st or {}).get("files", {}).get(role) if status == "ready" else None
        if not name:
            raise HTTPException(409 if status in ("pending", "processing") else 404,
                                "Still being prepared" if status in ("pending", "processing") else "Not available for this media")
        f = worker.key_dir(path) / name
        media_type = _PROXY_TYPES.get(f.suffix) if role == "proxy" else _ROLES[role]
        return FileResponse(f, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})  # content-addressed

    @router.get("/media/proxy")
    def media_proxy(pid: str, asset: str = Query(..., max_length=200)) -> FileResponse:
        return derived_file(pid, asset, "proxy")

    @router.get("/media/audio")
    def media_audio(pid: str, asset: str = Query(..., max_length=200)) -> FileResponse:
        return derived_file(pid, asset, "audio")

    @router.get("/media/peaks")
    def media_peaks(pid: str, asset: str = Query(..., max_length=200)) -> FileResponse:
        return derived_file(pid, asset, "peaks")

    @router.get("/media/film")
    def media_film(pid: str, asset: str = Query(..., max_length=200)) -> FileResponse:
        return derived_file(pid, asset, "film")

    @router.get("/media/film.json")
    def media_film_meta(pid: str, asset: str = Query(..., max_length=200)) -> FileResponse:
        return derived_file(pid, asset, "film_meta")

    @router.get("/disk", response_model=DiskUsage)
    def disk(pid: str) -> DiskUsage:
        info = project(pid)
        d = store.path(pid)
        derived_bytes = 0
        for a in timeline_of(pid, info).assets.values():
            st = worker._state(Path(a.path)) if Path(a.path).is_file() else None  # noqa: SLF001
            derived_bytes += int((st or {}).get("bytes", 0))
        project_bytes, uploads = _dir_bytes(d), _dir_bytes(d / "uploads")
        return DiskUsage(project_bytes=project_bytes, uploads_bytes=uploads, derived_bytes=derived_bytes,
                         total_bytes=project_bytes + derived_bytes)

    return router


def register(app: FastAPI, store: ProjectStore, settings: Settings, worker: MediaWorker) -> None:
    app.include_router(build_router(store, settings, worker))
