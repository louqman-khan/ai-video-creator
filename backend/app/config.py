from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] is the repo root
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ROOT / "backend" / ".env"),
        extra="ignore",
    )

    # media sources
    pixabay_api_key: str = ""
    pexels_api_key: str = ""
    media_sources: str = "pixabay,pexels,openverse,wikimedia"
    local_media_dir: str = ""

    # LLM
    gemini_api_key: str = ""
    # comma-separated, tried in order (fast model first, others are fail-over)
    gemini_model: str = "gemini-flash-lite-latest,gemini-3-flash-preview,gemini-3.5-flash"
    scene_planner: str = "gemini"

    # providers
    transcriber: str = "faster_whisper"
    whisper_model: str = "small"
    media_ranker: str = "auto"  # auto | clip | heuristic: auto = CLIP when its model files are in clip_dir (docs/clip-ranker.md)
    audio_cleaner: str = "ffmpeg"  # ffmpeg | noop (--no-clean)
    tts: str = "auto"  # auto | mms | piper | none  (docs/tts.md)
    avatar_renderer: str = "none"

    # silence removal (avc make --remove-silence)
    silence_min_gap_s: float = 0.8   # pauses at least this long are shortened
    silence_keep_gap_s: float = 0.4  # ... to this length

    # loudness (EBU R128)
    target_lufs: float = -14.0

    # web API
    projects_dir: str = str(ROOT / "work" / "projects")
    max_upload_mb: int = 200
    max_audio_minutes: float = 30.0  # CPU-only start: keep jobs bounded
    cors_origins: str = "http://127.0.0.1:5742,http://localhost:5742"  # the Vite dev server

    # imported media (editor)
    max_media_upload_mb: int = 500
    max_media_minutes: float = 30.0
    max_image_megapixels: int = 64
    max_media_fps: int = 240
    max_uploads_per_project: int = 100
    proxy_dir: str = ""  # empty: <work_dir>/cache/proxies

    # scene chunking
    scene_min_s: float = 3.0
    scene_max_s: float = 8.0

    # captions: empty = Noto Nastaliq Urdu for Urdu, Arial otherwise
    caption_font: str = ""

    # output
    fps: int = 30
    fonts_dir: str = str(ROOT / "assets" / "fonts")
    work_dir: str = str(ROOT / "work")
    models_dir: str = str(ROOT / "assets" / "models")
    clip_dir: str = str(ROOT / "assets" / "models" / "clip")
    tts_dir: str = str(ROOT / "assets" / "models" / "tts")
    rnnoise_model: str = "cb.rnnn"  # file name inside models_dir

    @property
    def source_names(self) -> list[str]:
        return [s.strip().lower() for s in self.media_sources.split(",") if s.strip()]


def get_settings() -> Settings:
    return Settings()
