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
    gemini_model: str = "gemini-3.5-flash"
    scene_planner: str = "gemini"

    # providers
    transcriber: str = "faster_whisper"
    whisper_model: str = "small"
    media_ranker: str = "heuristic"
    audio_cleaner: str = "noop"
    tts: str = "none"
    avatar_renderer: str = "none"

    # scene chunking
    scene_min_s: float = 3.0
    scene_max_s: float = 8.0

    # output
    fps: int = 30
    fonts_dir: str = str(ROOT / "assets" / "fonts")
    work_dir: str = str(ROOT / "work")

    @property
    def source_names(self) -> list[str]:
        return [s.strip().lower() for s in self.media_sources.split(",") if s.strip()]


def get_settings() -> Settings:
    return Settings()
