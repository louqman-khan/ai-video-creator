from pathlib import Path

from app.config import Settings
from app.providers.audio_cleaner import NoopCleaner, create_cleaner
from app.providers.audio_cleaner.ffmpeg_cleaner import FfmpegCleaner, build_filter


def test_filter_uses_rnnoise_when_model_exists_else_afftdn(tmp_path):
    model = tmp_path / "m.rnnn"
    assert "afftdn" in build_filter(model) and "arnndn" not in build_filter(model)  # file missing
    model.write_text("x")
    f = build_filter(model)
    assert f.startswith("highpass=f=80,arnndn=m='") and "afftdn" not in f
    assert FfmpegCleaner(model).method == "rnnoise" and FfmpegCleaner(None).method == "afftdn"


def test_cleaner_selected_by_config():
    assert isinstance(create_cleaner(Settings(_env_file=None)), FfmpegCleaner)
    assert isinstance(create_cleaner(Settings(_env_file=None, audio_cleaner="noop")), NoopCleaner)


def test_cleaning_failure_returns_original(tmp_path):
    src = tmp_path / "missing.wav"  # ffmpeg cannot read it
    assert FfmpegCleaner(None).clean(src, tmp_path / "out.flac") == src
