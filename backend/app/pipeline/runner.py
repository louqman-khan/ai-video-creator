"""Orchestrates: ingest -> transcribe -> plan -> fetch -> captions -> assemble.
Every stage writes a JSON/file into the run dir and is skipped on re-run unless `force`."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.media import ffmpeg
from app.media.cache import MediaCache
from app.models import Scene, ScenePick, Transcript
import hashlib

from app.pipeline import assemble
from app.pipeline.align import align_script
from app.pipeline.silence import cut_audio, plan_cuts, remap_transcript
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.fetch import fetch_media
from app.text.urdu import normalize_transcript
from app.providers.audio_cleaner import AudioCleaner
from app.providers.media_ranker import MediaRanker
from app.providers.media_search import CompositeSearch
from app.providers.scene_planner import ScenePlanner
from app.providers.transcriber import Transcriber

log = logging.getLogger("avc.pipeline")
M = TypeVar("M", bound=BaseModel)

from app.timeline import convert
from app.timeline.render import render_timeline
from app.pipeline.sizes import ASPECTS, PREVIEW_SIZES, base_video_name, render_size  # noqa: F401  (re-exported)


@dataclass
class Providers:
    transcriber: Transcriber
    planner: ScenePlanner
    search: CompositeSearch
    ranker: MediaRanker
    cleaner: AudioCleaner


def _save(path: Path, items) -> None:
    data = [i.model_dump() for i in items] if isinstance(items, list) else items.model_dump()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def credits_text(picks: list[ScenePick]) -> str:
    seen, lines = set(), []
    for p in picks:
        a = p.asset
        if not a or a.id in seen:
            continue
        seen.add(a.id)
        lines.append(f"- {a.attribution or a.title or a.id} | License: {a.license} {a.license_url}".rstrip())
    return "Media credits\n=============\n" + "\n".join(lines) + "\n"


class Pipeline:
    def __init__(self, settings: Settings, providers: Providers, run_dir: Path) -> None:
        self.s, self.p, self.run_dir = settings, providers, run_dir
        # progress(stage, fraction 0..1, message): the web API shows this; the CLI ignores it
        self.progress: Callable[[str, float, str], None] = lambda stage, fraction, message: None
        run_dir.mkdir(parents=True, exist_ok=True)

    def transcribe(self, audio: Path, language: str | None, force: bool = False) -> Transcript:
        ffmpeg.require_ffmpeg()
        wav = self.run_dir / "audio.wav"
        if force or not wav.exists():
            log.info("ingest: converting audio to 16 kHz mono")
            ffmpeg.run(["-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", str(wav)])  # ASR hears the original
        path = self.run_dir / "transcript.json"
        if path.exists() and not force:
            return Transcript.model_validate_json(path.read_text("utf-8"))
        log.info("transcribing (%s model)...", self.s.whisper_model)
        t = self.p.transcriber.transcribe(wav, language)
        t.duration = ffmpeg.probe_duration(audio)
        if t.language == "ur":
            _save(self.run_dir / "transcript.raw.json", t)  # keep what the model really said
            t = normalize_transcript(t)
        _save(path, t)
        return t

    # What each option invalidates. Silence removal moves the timeline, so scenes and media picks
    # must be redone (an LLM call + downloads). Cleaner and loudness only change the audio files.
    _TIMELINE = ("silence", "script")
    _TIMELINE_FILES = ("scenes.json", "assets.json", "transcript.cut.json", "audio_cut.flac", "transcript.aligned.json",
                       "captions.json", "transcript.final.json")  # edited captions are tied to the old timeline
    _AUDIO_FILES = {"cleaner": ("audio_clean.flac", "audio_cut.flac", "audio_norm.flac"),
                    "lufs": ("audio_norm.flac",),
                    "silence": ("audio_cut.flac", "audio_norm.flac"),
                    "script": ("audio_norm.flac",)}

    def _sync_options(self, options: dict) -> None:
        """Forget derived results when the options that shape them changed since the last run."""
        path = self.run_dir / "run_config.json"
        old = json.loads(path.read_text("utf-8")) if path.exists() else None
        if old is not None:
            changed = [k for k in options if options[k] != old.get(k)]
            if changed:
                log.info("options changed since the last run (%s): rebuilding what depends on them", ", ".join(changed))
            for k in changed:
                files = list(self._AUDIO_FILES.get(k, ()))
                if k in self._TIMELINE:
                    files += self._TIMELINE_FILES
                for name in files:
                    (self.run_dir / name).unlink(missing_ok=True)
        path.write_text(json.dumps(options), "utf-8")

    def _clean(self, audio: Path, force: bool) -> Path:
        clean_path = self.run_dir / "audio_clean.flac"
        if force or not clean_path.exists():
            clean_path.unlink(missing_ok=True)
            return self.p.cleaner.clean(audio, clean_path)  # may return `audio` itself (noop/failure)
        return clean_path

    def align(self, script: str, transcript: Transcript) -> Transcript:
        """Replace the recognised text with the script's own words, keeping the audio's timing."""
        aligned, stats = align_script(script, transcript)
        log.info("script aligned: %d/%d words matched the audio exactly (%.0f%%)",
                 stats.exact, stats.script_words, 100 * stats.match_ratio)
        if stats.match_ratio < 0.5:
            log.warning("less than half of the script words were heard in the audio: "
                        "is this the right script for this recording?")
        _save(self.run_dir / "transcript.aligned.json", aligned)
        return aligned

    def _cached(self, name: str, model: type[M], force: bool) -> list[M] | None:
        path = self.run_dir / name
        if path.exists() and not force:
            return [model.model_validate(d) for d in json.loads(path.read_text("utf-8"))]
        return None

    def run(
        self,
        audio: Path,
        out: Path,
        language: str | None = None,
        aspect: str = "16:9",
        captions: bool = True,
        force: bool = False,
        style: CaptionStyle | None = None,
        remove_silence: bool = False,
        min_gap: float | None = None,
        normalize: bool = True,
        lufs: float | None = None,
        script: str | None = None,
        quality: str = "final",
        preset: str | None = None,
        profile=None,
    ) -> Path:
        preview = quality == "preview"
        w, h = render_size(aspect, quality, preset)
        min_gap = min_gap or self.s.silence_min_gap_s
        keep_gap = self.s.silence_keep_gap_s
        lufs = lufs if lufs is not None else self.s.target_lufs
        self.progress("transcribe", 0.05, "Listening to the audio")
        transcript = self.transcribe(audio, language, force)
        log.info("transcript: %s, %d words", transcript.language, len(transcript.words))
        self.progress("transcribe", 0.30, f"Recognised {len(transcript.words)} words")
        if script:
            transcript = self.align(script, transcript)

        # options that change the audio/timeline: results derived from them must not be reused
        self._sync_options({"cleaner": self.s.audio_cleaner, "silence": [min_gap, keep_gap] if remove_silence else None,
                            "lufs": lufs if normalize else None,
                            "script": hashlib.sha1(script.encode()).hexdigest()[:12] if script else None})

        final_audio = self._clean(audio, force)
        if remove_silence:
            cuts = plan_cuts(transcript.words, transcript.duration, min_gap, keep_gap)
            if cuts:
                removed = sum(b - a for a, b in cuts)
                log.info("removing %.1f s of silence in %d gaps", removed, len(cuts))
                cut_path = self.run_dir / "audio_cut.flac"
                if force or not cut_path.exists():
                    cut_audio(final_audio, cut_path, cuts, transcript.duration)
                final_audio = cut_path
                transcript = remap_transcript(transcript, cuts)
                _save(self.run_dir / "transcript.cut.json", transcript)
            else:
                log.info("no pauses of %.1f s or longer: nothing to remove", min_gap)

        scenes = self._cached("scenes.json", Scene, force)
        if scenes is None:
            log.info("planning scenes...")
            self.progress("plan", 0.35, "Planning scenes")
            scenes = self.p.planner.plan(transcript)
            _save(self.run_dir / "scenes.json", scenes)
        log.info("%d scenes", len(scenes))
        self.progress("plan", 0.45, f"{len(scenes)} scenes planned")

        picks = self._cached("assets.json", ScenePick, force)
        if picks is None:
            log.info("fetching media...")
            cache = MediaCache(Path(self.s.work_dir) / "cache" / "media", public_only=self.s.mode == "hosted")
            orientation = "portrait" if h > w else "landscape"
            picks = fetch_media(
                scenes, self.p.search, self.p.ranker, cache, orientation,
                on_scene=lambda i, n: self.progress("fetch", 0.45 + 0.30 * i / n, f"Finding visuals {i + 1}/{n}"),
            )
            _save(self.run_dir / "assets.json", picks)
        (self.run_dir / "CREDITS.txt").write_text(credits_text(picks), "utf-8")

        _save(self.run_dir / "transcript.final.json", transcript)  # exactly what the captions are built from
        log.info("rendering...")
        self.progress("render", 0.78, "Rendering the preview" if preview else "Rendering the full-quality video")
        facts = SimpleNamespace(audio_file=str(audio), aspect=aspect,
                                options={"style": style.model_dump(exclude_none=True) if style else None})
        timeline = convert.ensure_timeline(self.run_dir, facts, self.s)  # one renderer for CLI, web and editor
        render_timeline(timeline, self.run_dir, self.s, quality=quality, aspect=aspect, out=out, captions=captions,
                        normalize=normalize, lufs=lufs, progress=self.progress, preset=preset, profile=profile)
        self.progress("done", 1.0, "Finished")
        return out
