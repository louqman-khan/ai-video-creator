"""Caption editing: read the cues, change their text and/or the style, reset, and preview.

The preview is rendered by FFmpeg/libass onto a frame of the caption-free video (concat.mp4),
so it is exactly what the final render will look like, Urdu shaping included.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.jobs import JobRunner
from app.api.store import ProjectInfo, ProjectNotFound, ProjectStore
from app.config import Settings
from app.media import ffmpeg
from app.models import Transcript
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.captions import Cue, build_cues, cues_to_ass
from app.pipeline.runner import ASPECTS, PREVIEW_SIZES
from app.timeline import convert
from app.timeline.models import Timeline
from app.timeline.validate import check

log = logging.getLogger("avc.captions")
MAX_TEXT = 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TRANSCRIPT_FILES = ("transcript.final.json", "transcript.cut.json", "transcript.aligned.json", "transcript.json")


class CueView(BaseModel):
    id: int
    start: float
    end: float
    text: str


class CaptionsView(BaseModel):
    cues: list[CueView]
    edited: bool  # true once the user changed any text (line grouping is then fixed)
    language: str
    style: dict  # the user's style settings (empty = defaults)


class CueEdit(BaseModel):
    id: int = Field(ge=0)
    text: str = Field(max_length=MAX_TEXT)


class CaptionsUpdate(BaseModel):
    cues: list[CueEdit] | None = None
    style: CaptionStyle | None = None


class PreviewRequest(BaseModel):
    cue_id: int = Field(0, ge=0)
    text: str | None = Field(None, max_length=MAX_TEXT)
    style: CaptionStyle | None = None


def clean_text(text: str) -> str:
    return " ".join(_CONTROL.sub(" ", unicodedata.normalize("NFC", text)).split())


def load_transcript(d: Path) -> Transcript:
    for name in _TRANSCRIPT_FILES:
        f = d / name
        if f.is_file():
            return Transcript.model_validate_json(f.read_text("utf-8"))
    raise HTTPException(409, "The captions are not ready yet")


def edited_timeline(d: Path) -> Timeline | None:
    return convert.load(d) if convert.has_edits(d) else None


def timeline_caption_clips(tl: Timeline):
    return sorted((c for c in tl.clips if c.kind == "caption"), key=lambda c: (c.start, c.id))


def style_of(info: ProjectInfo, d: Path | None = None) -> CaptionStyle:
    tl = edited_timeline(d) if d is not None else None
    raw = tl.caption_style if tl is not None else info.options.get("style")
    return CaptionStyle.model_validate(raw) if raw else CaptionStyle()


def current_cues(d: Path, info: ProjectInfo) -> tuple[list[Cue], bool, str]:
    """(cues, edited?, language). Edited cues are persisted; otherwise derived from the transcript."""
    tl = edited_timeline(d)
    if tl is not None:  # the timeline's caption clips are the truth
        return ([Cue(start=c.start / tl.fps, end=(c.start + c.duration) / tl.fps, text=c.text or "") for c in timeline_caption_clips(tl)],
                True, str(tl.meta.get("language", "en")))
    transcript = load_transcript(d)
    edited = d / "captions.json"
    if edited.is_file():
        return [Cue.model_validate(c) for c in json.loads(edited.read_text("utf-8"))], True, transcript.language
    return build_cues(transcript, style_of(info, d)), False, transcript.language


def build_router(store: ProjectStore, jobs: JobRunner, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{pid}/captions")
    preview_slots = threading.BoundedSemaphore(2)  # previews are cheap, but never let them pile up

    def project(pid: str) -> ProjectInfo:
        try:
            return store.get(pid)
        except ProjectNotFound:
            raise HTTPException(404, "Project not found") from None

    def require_idle(info: ProjectInfo) -> None:
        if info.status in ("queued", "running"):
            raise HTTPException(409, "This project is still processing")
        if not info.video_ready:
            raise HTTPException(409, "The video is not ready yet")


    def rerender(pid: str, info: ProjectInfo) -> ProjectInfo:
        queued = store.update(pid, status="queued", stage="captions", progress=0.0, message="Applying caption changes", error=None)
        jobs.submit(pid)
        return queued

    @router.get("", response_model=CaptionsView)
    def get_captions(pid: str) -> CaptionsView:
        info = project(pid)
        cues, edited, language = current_cues(store.path(pid), info)
        return CaptionsView(cues=[CueView(id=i, **c.model_dump()) for i, c in enumerate(cues)], edited=edited,
                            language=language, style=(style_of(info, store.path(pid)).model_dump(exclude_none=True)
                                                      if edited_timeline(store.path(pid)) else info.options.get("style") or {}))

    def update_timeline_captions(pid: str, info: ProjectInfo, d: Path, body: CaptionsUpdate) -> ProjectInfo:
        """Same editing rules, applied to the caption clips of an edited timeline."""
        with store.lock:
            tl = convert.load(d)
            if tl is None:
                raise HTTPException(409, "The timeline is missing")
            caps = timeline_caption_clips(tl)
            texts: dict[str, str] = {}
            if body.cues is not None:
                if sorted(c.id for c in body.cues) != list(range(len(caps))):
                    raise HTTPException(409, "The captions changed since you opened the editor. Reload the page.")
                for e in body.cues:
                    text = clean_text(e.text)
                    if text != (caps[e.id].text or ""):
                        texts[caps[e.id].id] = text
            style = tl.caption_style
            style_changed = False
            if body.style is not None:
                new_style = body.style.model_dump(exclude_none=True)
                if new_style != (tl.caption_style or {}):
                    style, style_changed = new_style, True
            if not texts and not style_changed:
                raise HTTPException(400, "Nothing to change")
            clips = [c.model_dump() | ({"text": texts[c.id]} if c.id in texts else {}) for c in tl.clips]
            try:
                updated = Timeline.model_validate({**tl.model_dump(), "rev": tl.rev + 1, "clips": clips, "caption_style": style})
            except ValueError as e:
                raise HTTPException(422, str(e).splitlines()[0]) from None
            problems = check(updated)
            if problems:
                raise HTTPException(422, "Invalid captions: " + "; ".join(problems[:3]))
            convert.save(d, updated)
        return rerender(pid, info)

    @router.put("", status_code=202, response_model=ProjectInfo)
    def update_captions(pid: str, body: CaptionsUpdate) -> ProjectInfo:
        info = project(pid)
        require_idle(info)
        if body.cues is None and body.style is None:
            raise HTTPException(400, "Nothing to change")
        d = store.path(pid)
        if edited_timeline(d) is not None:
            return update_timeline_captions(pid, info, d, body)
        changed = False
        if body.cues is not None:
            cues, _, _ = current_cues(d, info)  # the list the editor was showing
            if sorted(c.id for c in body.cues) != list(range(len(cues))):
                raise HTTPException(409, "The captions changed since you opened the editor. Reload the page.")
            new = [c.model_copy() for c in cues]
            for e in body.cues:
                text = clean_text(e.text)
                if text != cues[e.id].text:
                    new[e.id].text, changed = text, True
            if changed:
                (d / "captions.json").write_text(json.dumps([c.model_dump() for c in new], ensure_ascii=False, indent=2), "utf-8")
        options = dict(info.options)
        if body.style is not None:
            new_style = body.style.model_dump(exclude_none=True)
            if new_style != (info.options.get("style") or {}):
                options["style"] = new_style
                changed = True
        if not changed:
            raise HTTPException(400, "Nothing to change")
        store.update(pid, options=options)
        return rerender(pid, info)

    @router.delete("", status_code=202, response_model=ProjectInfo)
    def reset_captions(pid: str) -> ProjectInfo:
        """Throw away text edits and go back to the recognised (or script) text."""
        info = project(pid)
        require_idle(info)
        if edited_timeline(store.path(pid)) is not None:
            raise HTTPException(409, "This project's captions live in its edited timeline. Reset the timeline to restore the original captions.")
        f = store.path(pid) / "captions.json"
        if not f.is_file():
            raise HTTPException(400, "The captions have not been edited")
        f.unlink()
        return rerender(pid, info)

    @router.post("/preview")
    async def preview(pid: str, body: PreviewRequest) -> Response:
        info = project(pid)
        d = store.path(pid)
        # the caption-free video: preview quality (960 px wide, crisp at the size shown) or, for projects made
        # before previews existed, the full-size one
        preview_base, full_base = d / "concat_preview.mp4", d / "concat.mp4"
        base = preview_base if preview_base.is_file() else full_base
        if not base.is_file():
            raise HTTPException(409, "The video is not ready yet")
        sizes = PREVIEW_SIZES if base == preview_base else ASPECTS
        cues, _, language = current_cues(d, info)
        if body.cue_id >= len(cues):
            raise HTTPException(404, "Caption not found")
        cue = cues[body.cue_id]
        text = clean_text(body.text) if body.text is not None else cue.text
        if not text:
            raise HTTPException(422, "Type some text to preview")
        style = body.style or style_of(info, d)
        width, height = sizes[info.aspect]
        at = max(0.0, (cue.start + cue.end) / 2)
        ass = cues_to_ass([Cue(start=0, end=30, text=text)], language, width, height, style)

        def render() -> bytes:
            tmp = d / "preview"
            tmp.mkdir(exist_ok=True)
            token = uuid.uuid4().hex
            ass_file, jpg = tmp / f"{token}.ass", tmp / f"{token}.jpg"
            try:
                ass_file.write_text(ass, "utf-8")
                vf = f"subtitles='{ffmpeg.filter_escape(ass_file.name)}'"
                if Path(settings.fonts_dir).is_dir():
                    vf += f":fontsdir='{ffmpeg.filter_escape(str(Path(settings.fonts_dir).resolve()))}'"
                # -ss before -i: the frame's timestamp becomes ~0, which is where the preview cue lives
                with preview_slots:
                    ffmpeg.run(["-ss", f"{at:.2f}", "-i", str(base), "-frames:v", "1",
                                "-vf", vf + ",scale=960:-2", "-q:v", "3", str(jpg)], cwd=tmp)
                return jpg.read_bytes()
            finally:
                ass_file.unlink(missing_ok=True)
                jpg.unlink(missing_ok=True)

        try:
            data = await run_in_threadpool(render)
        except ffmpeg.FfmpegError:
            raise HTTPException(500, "The preview could not be rendered") from None
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    return router


def register(app: FastAPI, store: ProjectStore, jobs: JobRunner, settings: Settings) -> None:
    app.include_router(build_router(store, jobs, settings))
