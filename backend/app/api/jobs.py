"""Background processing: one worker thread (the pipeline is CPU-heavy on a laptop)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.api.store import ProjectStore
from app.config import Settings
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.runner import Pipeline, Providers

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

    def submit(self, project_id: str) -> None:
        self._pool.submit(self._run, project_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, pid: str) -> None:
        store = self.store
        try:
            info = store.update(pid, status="running", stage="start", progress=0.0, message="Starting", error=None)
            opts = info.options
            d = store.path(pid)
            settings = self.settings.model_copy(update={"audio_cleaner": "ffmpeg" if opts.get("clean", True) else "noop"})
            pipe = Pipeline(settings, self.factory(settings, opts), d)
            pipe.progress = lambda stage, frac, msg: store.update(pid, stage=stage, progress=round(frac, 3), message=msg)
            script_file = d / "script.txt"
            style = CaptionStyle.model_validate(opts["style"]) if opts.get("style") else None
            pipe.run(
                d / info.audio_file, d / "output.mp4", opts.get("language") or None, info.aspect,
                captions=opts.get("captions", True), style=style,
                remove_silence=opts.get("remove_silence", False), min_gap=opts.get("min_gap"),
                normalize=opts.get("normalize", True), lufs=opts.get("lufs"),
                script=script_file.read_text("utf-8") if script_file.exists() else None,
            )
            store.update(pid, status="done", stage="done", progress=1.0, message="Finished", video_ready=True)
        except Exception as e:  # report to the user, keep the worker alive for the next job
            log.exception("project %s failed", pid)
            store.update(pid, status="failed", error=redact(f"{type(e).__name__}: {e}", self.settings)[:500])
