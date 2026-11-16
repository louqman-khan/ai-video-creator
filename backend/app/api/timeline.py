"""Timeline document API (task 4.1). The browser reads the timeline, and writes it back with the
revision it was based on; the server validates everything and never exposes paths or download URLs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.config import Settings
from app.pipeline.caption_style import CaptionStyle
from app.timeline import convert
from app.timeline.models import AssetOut, Clip, Timeline, Track
from app.timeline.validate import check

MAX_PROBLEMS_SHOWN = 8
EDITED_MESSAGE = "This project has timeline edits. Change it in the timeline editor instead."


class TimelineView(BaseModel):
    rev: int
    fps: int
    aspect: str
    duration: int  # frames
    tracks: list[Track]
    clips: list[Clip]
    assets: dict[str, AssetOut]
    caption_style: dict | None = None


class TimelineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_rev: int = Field(..., ge=1)  # the revision this edit started from
    tracks: list[Track]
    clips: list[Clip]
    caption_style: dict | None = None


def view_of(tl: Timeline) -> TimelineView:
    return TimelineView(rev=tl.rev, fps=tl.fps, aspect=tl.aspect, duration=tl.duration, tracks=tl.tracks, clips=tl.clips,
                        assets={k: AssetOut.of(a) for k, a in tl.assets.items()}, caption_style=tl.caption_style)


def load_or_build(store: ProjectStore, settings: Settings, pid: str, info: ProjectInfo, create: bool = True,
                  on_built: Callable[[str, Timeline], None] | None = None) -> Timeline:
    """The project's timeline, built from its scenes/captions the first time it is needed."""
    d: Path = store.path(pid)
    try:
        tl = convert.load(d)
    except ValueError:  # unreadable file: treat it as absent and rebuild (never serve a broken document)
        tl = None
    if tl is not None and tl.rev == 1 and tl.meta.get("builder") != convert.BUILDER_VERSION:
        tl = None  # made by an older builder and never edited: rebuild it
    if tl is None:
        if not create:
            raise HTTPException(409, "Open the timeline first")
        try:
            tl = convert.build_timeline(d, info, settings)
        except convert.ProjectNotReady as e:
            raise HTTPException(409, str(e)) from None
        problems = check(tl)
        if problems:  # a migration bug must be loud, not saved
            raise HTTPException(500, "The timeline could not be built: " + "; ".join(problems[:MAX_PROBLEMS_SHOWN]))
        convert.save(d, tl)
        if on_built:
            try:
                on_built(pid, tl)  # e.g. start preparing proxies; must never make reading the timeline fail
            except Exception:  # noqa: BLE001
                pass
    return tl


def build_router(store: ProjectStore, settings: Settings, on_built: Callable[[str, Timeline], None] | None = None,
                 jobs=None) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{pid}/timeline")

    def project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    def idle(info: ProjectInfo) -> None:
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")

    def current(pid: str, info: ProjectInfo, create: bool) -> Timeline:
        return load_or_build(store, settings, pid, info, create, on_built)

    @router.get("", response_model=TimelineView)
    def get_timeline(pid: str) -> TimelineView:
        info = project(pid)
        idle(info)
        with store.lock:
            return view_of(current(pid, info, create=True))

    @router.put("", response_model=TimelineView)
    def put_timeline(pid: str, body: TimelineUpdate) -> TimelineView:
        info = project(pid)
        idle(info)
        with store.lock:  # read-modify-write: two tabs cannot interleave
            tl = current(pid, info, create=False)
            if body.base_rev != tl.rev:
                raise HTTPException(  # headers must be on the exception: FastAPI drops them from an injected Response
                    409, f"The timeline was changed elsewhere (it is now at revision {tl.rev}, you edited {body.base_rev}). Reload to continue.",
                    headers={"X-Current-Rev": str(tl.rev)},
                )
            style = None
            if body.caption_style is not None:
                try:
                    style = CaptionStyle.model_validate(body.caption_style).model_dump(exclude_none=True)
                except ValueError as e:
                    raise HTTPException(422, f"Invalid caption style: {e}") from None
            try:  # re-validates every limit (clip count, track count, ...) on the complete document
                new = Timeline.model_validate({**tl.model_dump(), "rev": tl.rev + 1, "tracks": [t.model_dump() for t in body.tracks],
                                               "clips": [c.model_dump() for c in body.clips], "caption_style": style})
            except ValueError as e:
                raise HTTPException(422, str(e).splitlines()[0]) from None
            problems = check(new)
            if problems:
                more = f" (+{len(problems) - MAX_PROBLEMS_SHOWN} more)" if len(problems) > MAX_PROBLEMS_SHOWN else ""
                raise HTTPException(422, "Invalid timeline: " + "; ".join(problems[:MAX_PROBLEMS_SHOWN]) + more)
            convert.save(store.path(pid), new)
            return view_of(new)

    @router.post("/render", status_code=202, response_model=ProjectInfo)
    def render_preview(pid: str) -> ProjectInfo:
        """Render the fast preview of the timeline as it is saved now (the editor calls this after its autosave)."""
        info = project(pid)
        idle(info)
        if not info.video_ready:
            raise HTTPException(409, "The video is not ready yet")
        if convert.load(store.path(pid)) is None:
            raise HTTPException(409, "Open the timeline first")
        if jobs is None:
            raise HTTPException(501, "Rendering is not available")
        queued = store.update(pid, status="queued", stage="render", progress=0.0, message="Rendering the preview", error=None)
        jobs.submit(pid)
        return queued

    @router.delete("", status_code=204)
    def reset_timeline(pid: str, discard_edits: bool = Query(False)) -> None:
        """Rebuild the timeline from the project's scenes and captions on the next request."""
        info = project(pid)
        idle(info)
        d = store.path(pid)
        with store.lock:
            if convert.has_edits(d) and not discard_edits:
                raise HTTPException(409, "The timeline has edits that would be lost. Confirm to discard them.")
            convert.timeline_path(d).unlink(missing_ok=True)

    return router


def register(app: FastAPI, store: ProjectStore, settings: Settings,
             on_built: Callable[[str, Timeline], None] | None = None, jobs=None) -> None:
    app.include_router(build_router(store, settings, on_built, jobs))
