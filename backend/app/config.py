from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    # --- optional PAID providers (docs/paid-providers.md): off unless TTS=elevenlabs / AVATAR_RENDERER=heygen is chosen AND the key is set
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"  # for Urdu choose a model that supports it (see the ElevenLabs docs)
    elevenlabs_voice_en: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_voice_ur: str = ""
    heygen_api_key: str = ""
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
    avatar_renderer: str = "simple"  # simple (cartoon, CPU) | remote (GPU service, AVATAR_URL) | none
    avatar_url: str = ""
    avatar_token: str = ""

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

    # --- hosting (docs/hosting.md). MODE=local: one person, no login (desktop app, avc app). MODE=hosted: accounts, per-user limits, security headers.
    mode: Literal["local", "hosted"] = "local"
    database_url: str = ""  # empty: sqlite:///<work_dir>/app.db (single VM); a PostgreSQL URL works too
    public_url: str = "http://127.0.0.1:8742"  # how users reach the site: used in e-mail links; https:// turns on Secure cookies
    signups: Literal["open", "invite", "closed"] = "open"
    invite_codes: str = ""  # comma-separated codes accepted when SIGNUPS=invite
    admin_emails: str = ""  # comma-separated: these accounts may use the storage clean-up
    session_days: int = 14
    require_email_verification: bool = True
    smtp_host: str = ""  # empty: e-mails are written to <work_dir>/outbox/ and the log (development)
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "AI Video Creator <no-reply@localhost>"
    allow_noncommercial_voices: bool | None = None  # None: yes in local mode, NO in hosted mode (the Urdu voice is CC-BY-NC and the English voice's licence is unclear)
    job_workers: int = 1  # renders that may run at once (each uses all CPU cores; raise on a bigger machine)
    # per-user limits in hosted mode
    max_projects_per_user: int = 20
    max_storage_mb_per_user: int = 5000
    max_active_jobs_per_user: int = 1
    max_exports_per_day: int = 10
    trusted_proxy: bool = False  # behind a reverse proxy that sets X-Forwarded-For (Caddy, nginx): use it for rate limits

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
    frontend_dist: str = str(ROOT / "frontend" / "dist")  # the built web app; when it exists the server shows it at / (one process = the whole app)
    clip_dir: str = str(ROOT / "assets" / "models" / "clip")
    tts_dir: str = str(ROOT / "assets" / "models" / "tts")
    rnnoise_model: str = "cb.rnnn"  # file name inside models_dir

    @property
    def source_names(self) -> list[str]:
        return [s.strip().lower() for s in self.media_sources.split(",") if s.strip()]


def get_settings() -> Settings:
    return Settings()
