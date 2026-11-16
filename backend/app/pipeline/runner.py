"""Orchestrates: ingest -> transcribe -> plan -> fetch -> captions -> assemble.
Every stage writes a JSON/file into the run dir and is skipped on re-run unless `force`."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.media import ffmpeg
from app.media.cache import MediaCache
from app.models import Scene, ScenePick, Transcript
from app.pipeline import assemble
from app.pipeline.silence import cut_audio, plan_cuts, remap_transcript
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.captions import build_ass
from app.pipeline.fetch import fetch_media
from app.text.urdu import normalize_transcript
from app.providers.audio_cleaner import AudioCleaner
from app.providers.media_ranker import MediaRanker
from app.providers.media_search import CompositeSearch
from app.providers.scene_planner import ScenePlanner
from app.providers.transcriber import Transcriber

log = logging.getLogger("avc.pipeline")
M = TypeVar("M", bound=BaseModel)

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}


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

    _DERIVED = ("scenes.json", "assets.json", "audio_clean.flac", "audio_cut.flac", "transcript.cut.json")

    def _sync_options(self, options: dict) -> None:
        """Forget derived results when the options that shape them changed since the last run."""
        path = self.run_dir / "run_config.json"
        old = json.loads(path.read_text("utf-8")) if path.exists() else None
        if old is not None and old != options:
            log.info("options changed since the last run: rebuilding scenes, media picks and audio")
            for name in self._DERIVED:
                (self.run_dir / name).unlink(missing_ok=True)
        path.write_text(json.dumps(options), "utf-8")

    def _clean(self, audio: Path, force: bool) -> Path:
        clean_path = self.run_dir / "audio_clean.flac"
        if force or not clean_path.exists():
            clean_path.unlink(missing_ok=True)
            return self.p.cleaner.clean(audio, clean_path)  # may return `audio` itself (noop/failure)
        return clean_path

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
    ) -> Path:
        w, h = ASPECTS[aspect]
        min_gap = min_gap or self.s.silence_min_gap_s
        keep_gap = self.s.silence_keep_gap_s
        transcript = self.transcribe(audio, language, force)
        log.info("transcript: %s, %d words", transcript.language, len(transcript.words))

        # options that change the audio/timeline: results derived from them must not be reused
        self._sync_options({"cleaner": self.s.audio_cleaner, "silence": [min_gap, keep_gap] if remove_silence else None})

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
            scenes = self.p.planner.plan(transcript)
            _save(self.run_dir / "scenes.json", scenes)
        log.info("%d scenes", len(scenes))

        picks = self._cached("assets.json", ScenePick, force)
        if picks is None:
            log.info("fetching media...")
            cache = MediaCache(Path(self.s.work_dir) / "cache" / "media")
            orientation = "portrait" if h > w else "landscape"
            picks = fetch_media(scenes, self.p.search, self.p.ranker, cache, orientation)
            _save(self.run_dir / "assets.json", picks)
        (self.run_dir / "CREDITS.txt").write_text(credits_text(picks), "utf-8")

        ass = None
        if captions:
            ass = self.run_dir / "captions.ass"
            ass.write_text(build_ass(transcript, w, h, style), "utf-8")

        log.info("rendering...")
        seg_dir = self.run_dir / "segments"
        shutil.rmtree(seg_dir, ignore_errors=True)
        segments = assemble.build_segments(scenes, picks, seg_dir, w, h, self.s.fps)
        out.parent.mkdir(parents=True, exist_ok=True)
        assemble.concat_and_finish(
            segments, final_audio, ass, out, self.run_dir, Path(self.s.fonts_dir), transcript.duration
        )
        return out
