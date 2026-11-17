"""Background processing: one worker thread (the pipeline is CPU-heavy on a laptop)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app import fsutil
from app.api.store import ProjectStore
from app.config import Settings
from app.media import ffmpeg
from app.pipeline import assemble, export_speed
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.sizes import render_size
from app.pipeline.runner import Pipeline, Providers
from app.timeline import convert
from app.timeline.render import RenderUnsupported, render_timeline

log = logging.getLogger("avc.jobs")
ProvidersFactory = Callable[[Settings, dict], Providers]


def redact(text: str, settings: Settings) -> str:
    """Error messages go to the browser: never let a configured secret through."""
    for secret in (settings.pixabay_api_key, settings.pexels_api_key, settings.gemini_api_key, settings.elevenlabs_api_key, settings.heygen_api_key, settings.avatar_token):
        if secret and len(secret) > 6:
            text = text.replace(secret, "***")
    return text


class JobRunner:
    def __init__(self, store: ProjectStore, settings: Settings, providers_factory: ProvidersFactory) -> None:
        self.store, self.settings, self.factory = store, settings, providers_factory
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avc-job")
        self._pending: set[str] = set()  # projects with a coalesced preview render already waiting
        self._lock = threading.Lock()
        self._tts = None

    def submit(self, project_id: str, prepare: Callable[[], None] | None = None, *, export_aspect: str | None = None,
               export_preset: str | None = None, export_encoder: str | None = None) -> None:
        """Queue a render. Default: the fast preview (edits re-render this). With `export_aspect`:
        the full-quality 1080p export. `prepare` runs first inside the worker (e.g. download the
        replacement visual of a swap); if it fails the previous video is kept."""
        self._pool.submit(self._run, project_id, prepare, export_aspect, export_preset, export_encoder)

    @property
    def tts(self):
        """The speech engine (made on first use; loading a voice takes a moment)."""
        if self._tts is None:
            from app.providers.tts import create_tts

            self._tts = create_tts(self.settings)
        return self._tts

    def _finish_export(self, pid: str, export: bool, aspect: str | None, preset: str, encoder: str, video_seconds: float, started: float) -> None:
        self.store.update(pid, status="done", stage="done", progress=1.0, message="Finished", video_ready=True, export_ready=export,
                          export_aspect=aspect, export_preset=preset if export else None, export_encoder=encoder if export else None)
        if export:  # what this export really cost makes the next estimate better
            export_speed.record(self.settings.work_dir, encoder, preset, aspect or "16:9", video_seconds, time.monotonic() - started)

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

    def _run(self, pid: str, prepare: Callable[[], None] | None = None, export_aspect: str | None = None,
             export_preset: str | None = None, export_encoder: str | None = None) -> None:
        store = self.store
        export = export_aspect is not None
        preset, encoder = export_preset or "1080p", export_encoder or "software"
        started = time.monotonic()
        try:
            info = store.update(pid, status="running", stage="start", progress=0.0, message="Starting", error=None,
                                export_ready=False)
        except Exception:  # project deleted while queued
            return
        d = store.path(pid)
        if not export:
            (d / "output.mp4").unlink(missing_ok=True)  # an older export no longer matches the edits
            store.update(pid, export_aspect=None, export_preset=None, export_encoder=None)
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
            final_out = d / ("output.mp4" if export else "preview.mp4")
            out = final_out.with_name(final_out.stem + ".part.mp4")  # written aside and swapped in at the end: on Windows a file a browser is still playing cannot be overwritten
            if opts.get("speak") and not (d / info.audio_file).is_file():  # a typed script: speak it first
                progress("speak", 0.02, "Speaking the script")
                self.tts.synthesize((d / "script.txt").read_text("utf-8"), opts.get("language") or "en", d / info.audio_file)
                if ffmpeg.probe_duration(d / info.audio_file) > settings.max_audio_minutes * 60:
                    (d / info.audio_file).unlink(missing_ok=True)
                    raise ValueError(f"The spoken script is longer than {settings.max_audio_minutes:g} minutes")
            profile = None
            if export:
                profile = assemble.export_profile(encoder, *render_size(export_aspect or info.aspect, "final", preset))
            if convert.has_edits(d):
                # an edited timeline is the truth: no transcription/planning/fetching, just render it
                tl = convert.load(d)
                if tl is None:
                    raise ValueError("The timeline is missing")
                (d / "CREDITS.txt").write_text(convert.credits_from_timeline(tl), "utf-8")
                render_timeline(tl, d, settings, quality="final" if export else "preview", aspect=export_aspect or info.aspect, out=out,
                                captions=opts.get("captions", True), normalize=opts.get("normalize", True),
                                lufs=opts.get("lufs") if opts.get("lufs") is not None else settings.target_lufs, progress=progress,
                                preset=preset, profile=profile)
                fsutil.replace(out, final_out, tries=60, delay=0.25)
                self._finish_export(pid, export, export_aspect, preset, encoder, tl.duration / tl.fps, started)
                if not export:
                    store.update(pid, preview_rev=tl.rev)
                return
                return
            pipe = Pipeline(settings, self.factory(settings, opts), d)
            pipe.progress = progress
            script_file = d / "script.txt"
            style = CaptionStyle.model_validate(opts["style"]) if opts.get("style") else None
            pipe.run(
                d / info.audio_file, out, opts.get("language") or None,
                export_aspect or info.aspect,
                captions=opts.get("captions", True), style=style,
                remove_silence=opts.get("remove_silence", False), min_gap=opts.get("min_gap"),
                normalize=opts.get("normalize", True), lufs=opts.get("lufs"),
                script=script_file.read_text("utf-8") if script_file.exists() else None,
                quality="final" if export else "preview", preset=preset, profile=profile,
            )
            fsutil.replace(out, final_out, tries=60, delay=0.25)
            rendered = convert.load(d)  # the pipeline built (or kept) it just now
            self._finish_export(pid, export, export_aspect, preset, encoder, rendered.duration / rendered.fps if rendered else 0.0, started)
            if not export and rendered is not None:
                store.update(pid, preview_rev=rendered.rev)
        except Exception as e:  # report to the user, keep the worker alive for the next job
            log.exception("project %s failed", pid)
            for part in (d / "preview.part.mp4", d / "output.part.mp4"):
                part.unlink(missing_ok=True)
            msg = redact(str(e) if isinstance(e, RenderUnsupported) else f"{type(e).__name__}: {e}", self.settings)[:500]
            if (export or isinstance(e, RenderUnsupported)) and (d / "preview.mp4").is_file():  # must not break the project
                store.update(pid, status="done", stage="done", progress=1.0, message="", video_ready=True, export_ready=False,
                             error=msg if isinstance(e, RenderUnsupported) else f"The export failed: {msg}")
            else:
                store.update(pid, status="failed", error=msg)
