"""Talking avatar (task 5.2): pick a character, it speaks the project's narration, and lands on the timeline as a small
picture-in-picture clip with the green screen key already on, so it can be moved, resized, trimmed or removed like any clip."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.jobs import JobRunner
from app.api.media import MediaWorker
from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.api.timeline import load_or_build
from app.config import Settings
from app.media import ffmpeg
from app.pipeline.sizes import ASPECTS
from app.providers.avatar_renderer import KEY_COLOUR, AvatarUnavailable, create_avatar_renderer
from app.timeline import convert
from app.timeline.models import Asset, ChromaKey, Clip, Timeline, Track, Transform
from app.timeline.validate import check

log = logging.getLogger("avc.avatars")
Corner = Literal["bottom-right", "bottom-left", "top-right", "top-left"]


class AvatarOut(BaseModel):
    id: str
    name: str
    paid: bool = False  # using it costs money at an outside service


class AvatarRequest(BaseModel):
    avatar: str = Field(..., max_length=60)
    corner: Corner = "bottom-right"
    size: float = Field(0.3, ge=0.15, le=0.7)  # the avatar's side as a fraction of the frame's short side


def placement(aspect: str, corner: Corner, size: float, margin: float = 0.03) -> Transform:
    """Transform for a square picture shown whole (fit) and scaled to `size` of the short side, tucked into a corner."""
    w, h = ASPECTS[aspect]
    side = min(w, h) * size
    x = 0.5 - margin - side / w / 2
    y = 0.5 - margin - side / h / 2
    return Transform(scale=size, x=x if corner.endswith("right") else -x, y=y if corner.startswith("bottom") else -y)


def add_avatar_clip(tl: Timeline, asset: Asset, req: AvatarRequest) -> Timeline:
    narration = next((c for c in tl.clips if c.kind == "audio" and c.asset == "narration"), None) or next((c for c in tl.clips if c.kind == "audio"), None)
    start = narration.start if narration else 0
    used = {t.id for t in tl.tracks}
    n = 1
    while f"V{n}" in used:
        n += 1
    track = Track(id=f"V{n}", kind="video", name="Avatar")
    cid, k = "avatar-1", 1
    ids = {c.id for c in tl.clips}
    while cid in ids:
        k += 1
        cid = f"avatar-{k}"
    length = min(asset.duration or 1, narration.duration if narration else asset.duration or 1)
    clip = Clip(id=cid, track=track.id, kind="video", asset=asset.id, start=start, duration=max(1, length), fit="fit",
                transform=placement(tl.aspect, req.corner, req.size), key=ChromaKey(color=KEY_COLOUR, similarity=0.2, blend=0.1, despill=True),
                meta={"avatar": req.avatar})
    assets = {**{k2: v.model_dump() for k2, v in tl.assets.items()}, asset.id: asset.model_dump()}
    return Timeline.model_validate({**tl.model_dump(), "rev": tl.rev + 1, "assets": assets,
                                    "tracks": [*(t.model_dump() for t in tl.tracks), track.model_dump()], "clips": [*(c.model_dump() for c in tl.clips), clip.model_dump()]})


def build_router(store: ProjectStore, settings: Settings, jobs: JobRunner, worker: MediaWorker) -> APIRouter:
    router = APIRouter(prefix="/api")
    renderer = create_avatar_renderer(settings)

    def project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    @router.get("/avatars", response_model=list[AvatarOut])
    def avatars() -> list[AvatarOut]:
        paid = bool(getattr(renderer, "paid", False))
        return [AvatarOut(id=a.id, name=a.name, paid=paid) for a in renderer.avatars()]

    @router.get("/avatars/{avatar_id}/thumb")
    def thumb(avatar_id: str) -> Response:
        if avatar_id not in {a.id for a in renderer.avatars()}:
            raise HTTPException(404, "Unknown avatar")
        try:
            return Response(renderer.thumbnail(avatar_id), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
        except AvatarUnavailable as e:
            raise HTTPException(503, str(e)) from None

    @router.post("/projects/{pid}/avatar", status_code=202, response_model=ProjectInfo)
    def add_avatar(pid: str, body: AvatarRequest) -> ProjectInfo:
        info = project(pid)
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")
        if not info.video_ready:
            raise HTTPException(409, "The video is not ready yet")
        if body.avatar not in {a.id for a in renderer.avatars()}:
            raise HTTPException(422, "Choose one of the avatars in the list.")
        d = store.path(pid)

        def prepare() -> None:
            with store.lock:
                tl = load_or_build(store, settings, pid, info, True, worker.ensure_timeline)
            narration = next((a for a in tl.assets.values() if a.kind == "audio"), None)
            if narration is None or not Path(narration.path).is_file():
                raise ValueError("The project has no narration for the avatar to speak")
            store.update(pid, message="Drawing the avatar", progress=0.1)
            token = uuid.uuid4().hex[:12]
            updir = d / "uploads"
            updir.mkdir(exist_ok=True)
            final = updir / f"{token}.mp4"
            try:
                renderer.render(body.avatar, Path(narration.path), final, lambda f: store.update(pid, message="Drawing the avatar", progress=round(0.1 + 0.6 * f, 3)))
                seconds = ffmpeg.probe_duration(final)
            except AvatarUnavailable:
                final.unlink(missing_ok=True)
                raise
            with store.lock:
                tl = load_or_build(store, settings, pid, store.get(pid), True, worker.ensure_timeline)
                asset = Asset(id=f"avatar:{token}", kind="video", path=str(final), duration=max(1, round(seconds * tl.fps)), width=512, height=512,
                              source="avatar", license="Generated", attribution="Generated avatar", title=f"Avatar ({body.avatar})")
                new = add_avatar_clip(tl, asset, body)
                problems = check(new)
                if problems:
                    final.unlink(missing_ok=True)
                    raise ValueError("; ".join(problems[:3]))
                convert.save(d, new)
            worker.ensure(final)

        queued = store.update(pid, status="queued", stage="avatar", progress=0.0, message="Preparing the avatar", error=None)
        jobs.submit(pid, prepare)
        return queued

    return router


def register(app: FastAPI, store: ProjectStore, settings: Settings, jobs: JobRunner, worker: MediaWorker) -> None:
    app.include_router(build_router(store, settings, jobs, worker))
