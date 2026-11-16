"""Scene list, visual candidates and visual swapping for one project.

Safety: the browser never supplies a URL. A swap names an asset id that this server itself
returned from a search (stored in candidates.json); the download URL stays on the server.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.jobs import JobRunner
from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.config import Settings
from app.media import ffmpeg
from app.media.cache import MediaCache
from app.models import MediaAsset, MediaKind, Scene, ScenePick
from app.pipeline.runner import Providers
from app.timeline import convert
from app.timeline.models import Clip, Effect, Timeline
from app.timeline.validate import check

log = logging.getLogger("avc.scenes")
MAX_CANDIDATES = 16


class AssetView(BaseModel):
    """What the browser may know about a visual (no download URL, no local path)."""

    id: str
    source: str
    kind: MediaKind
    thumb_url: str = ""
    page_url: str = ""
    title: str = ""
    width: int = 0
    height: int = 0
    duration: float | None = None
    license: str
    license_url: str = ""
    author: str = ""
    attribution: str = ""
    attribution_required: bool = False

    @classmethod
    def of(cls, a: MediaAsset) -> "AssetView":
        return cls(**a.model_dump(include=set(cls.model_fields)))


class SceneView(BaseModel):
    id: int
    start: float
    end: float
    text: str
    query_en: str = ""
    keywords: list[str] = Field(default_factory=list)
    preferred_kind: MediaKind | None = None
    asset: AssetView | None = None
    has_thumb: bool = False


class AttributionView(BaseModel):
    """One visual used in the project, once, with every scene it appears in."""

    asset: AssetView
    scenes: list[int]


class SwapRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def load_scenes(d: Path) -> tuple[list[Scene], list[ScenePick]]:
    if convert.has_edits(d):  # an edited timeline is the truth: the scene list is a view over it
        tl = convert.load(d)
        if tl is not None:
            return convert.scenes_from_timeline(tl)
    scenes, picks = _read_json(d / "scenes.json"), _read_json(d / "assets.json")
    if scenes is None or picks is None:
        raise HTTPException(409, "The scenes are not ready yet")
    return [Scene.model_validate(s) for s in scenes], [ScenePick.model_validate(p) for p in picks]


def thumb_path(d: Path, pick: ScenePick) -> Path | None:
    if not (pick.asset and pick.local_path):
        return None
    tag = hashlib.sha1(pick.asset.id.encode()).hexdigest()[:10]  # a swap gives a new file name
    return d / "thumbs" / f"scene_{pick.scene_id}_{tag}.jpg"


def make_thumb(src: Path, dst: Path, kind: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    base = ["-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(dst)]
    try:
        ffmpeg.run((["-ss", "0.5"] if kind == "video" else []) + base)
    except ffmpeg.FfmpegError:
        ffmpeg.run(base)  # very short clip: no seek


def build_router(store: ProjectStore, jobs: JobRunner, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{pid}")

    def project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    def scene_or_404(scenes: list[Scene], sid: int) -> Scene:
        for s in scenes:
            if s.id == sid:
                return s
        raise HTTPException(404, "Scene not found")

    @router.get("/scenes", response_model=list[SceneView])
    def scenes(pid: str) -> list[SceneView]:
        project(pid)
        d = store.path(pid)
        sc, picks = load_scenes(d)
        by = {p.scene_id: p for p in picks}
        out = []
        for s in sc:
            p = by.get(s.id)
            out.append(SceneView(**s.model_dump(), asset=AssetView.of(p.asset) if p and p.asset else None,
                                 has_thumb=bool(p and p.asset and p.local_path)))
        return out

    @router.get("/attributions", response_model=list[AttributionView])
    def attributions(pid: str) -> list[AttributionView]:
        """Unique visuals of the project with license and attribution (source of the credits panel)."""
        project(pid)
        _, picks = load_scenes(store.path(pid))
        seen: dict[str, AttributionView] = {}
        for p in picks:
            if not p.asset:
                continue
            if p.asset.id in seen:
                seen[p.asset.id].scenes.append(p.scene_id)
            else:
                seen[p.asset.id] = AttributionView(asset=AssetView.of(p.asset), scenes=[p.scene_id])
        # visuals that legally need a credit first, then the rest
        return sorted(seen.values(), key=lambda a: (not a.asset.attribution_required, a.scenes[0]))

    @router.get("/scenes/{sid}/thumb")
    async def thumb(pid: str, sid: int) -> FileResponse:
        project(pid)
        d = store.path(pid)
        _, picks = load_scenes(d)
        pick = next((p for p in picks if p.scene_id == sid), None)
        dst = thumb_path(d, pick) if pick else None
        if not (pick and dst and pick.asset and pick.local_path and Path(pick.local_path).is_file()):
            raise HTTPException(404, "This scene has no visual")
        if not dst.is_file():
            try:
                await run_in_threadpool(make_thumb, Path(pick.local_path), dst, pick.asset.kind)
            except ffmpeg.FfmpegError:
                raise HTTPException(404, "No preview available") from None
        return FileResponse(dst, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @router.get("/scenes/{sid}/candidates", response_model=list[AssetView])
    async def candidates(pid: str, sid: int, query: str = Query("", max_length=100)) -> list[AssetView]:
        info = project(pid)
        d = store.path(pid)
        sc, picks = load_scenes(d)
        scene = scene_or_404(sc, sid)
        q = " ".join(query.split()) or scene.query_en
        if not q:
            raise HTTPException(422, "Type what the scene should show")
        providers: Providers = jobs.factory(settings, info.options)
        used = {p.asset.id for p in picks if p.asset and p.scene_id != sid}
        orientation = "portrait" if info.aspect == "9:16" else "landscape"

        def search() -> list[MediaAsset]:
            found: list[MediaAsset] = []
            for kind in ("video", "image"):
                found += providers.search.search(q, kind, orientation=orientation, limit=10)
            seen, unique = set(), []
            for a in providers.ranker.rank(scene, found, used=used):
                if a.id not in seen:
                    seen.add(a.id)
                    unique.append(a)
            return unique[:MAX_CANDIDATES]

        found = await run_in_threadpool(search)
        stored = _read_json(d / "candidates.json") or {}
        stored[str(sid)] = [a.model_dump() for a in found]  # what a later swap may choose from
        (d / "candidates.json").write_text(json.dumps(stored), "utf-8")
        return [AssetView.of(a) for a in found]

    @router.post("/scenes/{sid}/swap", status_code=202, response_model=ProjectInfo)
    def swap(pid: str, sid: int, body: SwapRequest) -> ProjectInfo:
        info = project(pid)
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")
        d = store.path(pid)
        sc, _ = load_scenes(d)
        scene_or_404(sc, sid)
        offered = (_read_json(d / "candidates.json") or {}).get(str(sid), [])
        raw = next((a for a in offered if a.get("id") == body.asset_id), None)
        if raw is None:
            raise HTTPException(400, "That visual was not offered for this scene. Search again and pick one from the results.")
        asset = MediaAsset.model_validate(raw)

        def prepare_timeline() -> None:
            """The timeline has been edited: swap the visual inside the timeline itself."""
            local = MediaCache(Path(settings.work_dir) / "cache" / "media").get(asset)
            with store.lock:
                tl = convert.load(d)
                if tl is None:
                    raise ValueError("The timeline is missing")
                frames = None
                if asset.kind == "video":
                    frames = max(1, round(ffmpeg.probe_duration(local) * tl.fps))
                new = convert.asset_from_media(asset, str(local), tl.fps, frames)
                clips, found = [], False
                for c in tl.clips:
                    if c.track == "V1" and c.meta.get("scene_id") == sid:
                        found = True
                        kb = [Effect(type="kenburns", value=convert.KENBURNS_PERCENT)] if new.kind == "image" else []
                        c = c.model_copy(update={"asset": new.id, "kind": new.kind, "in_point": 0, "effects": kb,
                                                 "loop": bool(new.kind == "video" and new.duration and c.duration > new.duration)})
                    clips.append(c)
                meta = dict(tl.meta)
                if not found:  # a scene that had no picture yet gets its clip now
                    empty = [e for e in meta.get("empty_scenes", [])]
                    e = next((x for x in empty if x.get("scene_id") == sid), None)
                    if e is None:
                        raise ValueError("That scene is no longer on the timeline")
                    meta["empty_scenes"] = [x for x in empty if x is not e]
                    kb = [Effect(type="kenburns", value=convert.KENBURNS_PERCENT)] if new.kind == "image" else []
                    clips.append(Clip(id=f"scene-{sid}", track="V1", kind=new.kind, asset=new.id, start=e["start"], duration=e["duration"],
                                      loop=bool(new.kind == "video" and new.duration and e["duration"] > new.duration), effects=kb,
                                      meta={k: v for k, v in e.items() if k not in ("start", "duration")}))
                updated = Timeline.model_validate({**tl.model_dump(), "rev": tl.rev + 1, "meta": meta,
                                                   "assets": {**{k: v.model_dump() for k, v in tl.assets.items()}, new.id: new.model_dump()},
                                                   "clips": [c.model_dump() for c in clips]})
                problems = check(updated)
                if problems:
                    raise ValueError("; ".join(problems[:3]))
                convert.save(d, updated)

        def prepare() -> None:
            if convert.has_edits(d):
                return prepare_timeline()
            local = MediaCache(Path(settings.work_dir) / "cache" / "media").get(asset)  # may take a while
            _, current = load_scenes(d)
            new = [ScenePick(scene_id=sid, asset=asset, local_path=str(local)) if p.scene_id == sid else p
                   for p in current]
            (d / "assets.json").write_text(json.dumps([p.model_dump() for p in new], ensure_ascii=False, indent=2), "utf-8")

        queued = store.update(pid, status="queued", stage="swap", progress=0.0, message="Swapping the visual", error=None)
        jobs.submit(pid, prepare)
        return queued

    return router


def register(app: FastAPI, store: ProjectStore, jobs: JobRunner, settings: Settings) -> None:
    app.include_router(build_router(store, jobs, settings))
