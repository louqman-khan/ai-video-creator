"""Background processing: one worker thread (the pipeline is CPU-heavy on a laptop)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.api.store import ProjectStore
from app.config import Settings
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.runner import Pipeline, Providers, credits_text
from app.timeline import convert
from app.timeline.render import RenderUnsupported, render_timeline

log = logging.getLogger("avc.jobs")
ProvidersFactory = Callable[[Settings, dict], Providers]


def redact(text: str, settings: Settings) -> str:
    """Error messages go to the browser: never let a configured secret through."""
    for secret in (settings.pixabay_api_key, settings.pexels_api_key, settings.gemini_api_key):
        if secret and len(secret) > 6:
            text = text.replace(secret, "***")
    return text


class JobRunner:
    def __init__(self, store: ProjectStore, settings: Settings, providers_factory: ProvidersFactory) -> None:
        self.store, self.settings, self.factory = store, settings, providers_factory
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avc-job")
        self._pending: set[str] = set()  # projects with a coalesced preview render already waiting
        self._lock = threading.Lock()

    def submit(self, project_id: str, prepare: Callable[[], None] | None = None, *, export_aspect: str | None = None) -> None:
        """Queue a render. Default: the fast preview (edits re-render this). With `export_aspect`:
        the full-quality 1080p export. `prepare` runs first inside the worker (e.g. download the
        replacement visual of a swap); if it fails the previous video is kept."""
        self._pool.submit(self._run, project_id, prepare, export_aspect)

    def request_render(self, project_id: str) -> bool:
        """Ask for a preview render while one may already be running. Requests that arrive while another is
        waiting are merged into it (it reads the newest saved timeline when it starts). False = merged."""
        with self._lock:
            if project_id in self._pending:
                return False
            self._pending.add(project_id)
        self._pool.submit(self._run_pending, project_id)
        return True

    def _run_pending(self, pid: str) -> None:
        with self._lock:
            self._pending.discard(pid)  # from here on a new request starts another render
        self._run(pid)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, pid: str, prepare: Callable[[], None] | None = None, export_aspect: str | None = None) -> None:
        store = self.store
        export = export_aspect is not None
        try:
            info = store.update(pid, status="running", stage="start", progress=0.0, message="Starting", error=None,
                                export_ready=False)
        except Exception:  # project deleted while queued
            return
        d = store.path(pid)
        if not export:
            (d / "output.mp4").unlink(missing_ok=True)  # an older export no longer matches the edits
            store.update(pid, export_aspect=None)
        if prepare:
            try:
                prepare()
            except Exception as e:
                log.exception("project %s: preparing the change failed", pid)
                # the old video is still fine: report the problem without breaking the project
                store.update(pid, status="done" if info.video_ready else "failed", stage="done", progress=1.0,
                             message="", error=redact(f"Could not apply the change: {e}", self.settings)[:500])
                return
        try:
            opts = info.options
            settings = self.settings.model_copy(update={"audio_cleaner": "ffmpeg" if opts.get("clean", True) else "noop"})
            progress = lambda stage, frac, msg: store.update(pid, stage=stage, progress=round(frac, 3), message=msg)  # noqa: E731
            out = d / ("output.mp4" if export else "preview.mp4")
            if convert.has_edits(d):
                # an edited timeline is the truth: no transcription/planning/fetching, just render it
                tl = convert.load(d)
                if tl is None:
                    raise ValueError("The timeline is missing")
                (d / "CREDITS.txt").write_text(credits_text(convert.scenes_from_timeline(tl)[1]), "utf-8")
                render_timeline(tl, d, settings, quality="final" if export else "preview", aspect=export_aspect or info.aspect, out=out,
                                captions=opts.get("captions", True), normalize=opts.get("normalize", True),
                                lufs=opts.get("lufs") if opts.get("lufs") is not None else settings.target_lufs, progress=progress)
                store.update(pid, status="done", stage="done", progress=1.0, message="Finished", video_ready=True,
                             export_ready=export, export_aspect=export_aspect,
                             **({} if export else {"preview_rev": tl.rev}))
                return
            pipe = Pipeline(settings, self.factory(settings, opts), d)
            pipe.progress = progress
            script_file = d / "script.txt"
            style = CaptionStyle.model_validate(opts["style"]) if opts.get("style") else None
            pipe.run(
                d / info.audio_file, d / ("output.mp4" if export else "preview.mp4"), opts.get("language") or None,
                export_aspect or info.aspect,
                captions=opts.get("captions", True), style=style,
                remove_silence=opts.get("remove_silence", False), min_gap=opts.get("min_gap"),
                normalize=opts.get("normalize", True), lufs=opts.get("lufs"),
                script=script_file.read_text("utf-8") if script_file.exists() else None,
                quality="final" if export else "preview",
            )
            rendered = convert.load(d)  # the pipeline built (or kept) it just now
            store.update(pid, status="done", stage="done", progress=1.0, message="Finished", video_ready=True,
                         export_ready=export, export_aspect=export_aspect,
                         **({} if export or rendered is None else {"preview_rev": rendered.rev}))
        except Exception as e:  # report to the user, keep the worker alive for the next job
            log.exception("project %s failed", pid)
            msg = redact(str(e) if isinstance(e, RenderUnsupported) else f"{type(e).__name__}: {e}", self.settings)[:500]
            if (export or isinstance(e, RenderUnsupported)) and (d / "preview.mp4").is_file():  # must not break the project
                store.update(pid, status="done", stage="done", progress=1.0, message="", video_ready=True, export_ready=False,
                             error=msg if isinstance(e, RenderUnsupported) else f"The export failed: {msg}")
            else:
                store.update(pid, status="failed", error=msg)
