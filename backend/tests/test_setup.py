import os
import time

from fastapi.testclient import TestClient

from app import config
from app.api import setup as setup_mod
from app.api.main import create_app
from app.config import Settings
from app.media import models

H = {"X-Requested-With": "avc"}


def make(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    s = Settings(_env_file=None, projects_dir=str(tmp_path / "p"), work_dir=str(tmp_path / "w"), models_dir=str(tmp_path / "m"),
                 clip_dir=str(tmp_path / "m" / "clip"), frontend_dist=str(tmp_path / "none"), **kw)
    return s, TestClient(create_app(s, lambda *_: None), headers=H)


def test_keys_are_saved_to_the_data_dir_and_never_echoed(tmp_path, monkeypatch):
    s, c = make(tmp_path, monkeypatch)
    assert c.get("/api/setup").json()["keys"] == {"gemini_api_key": False, "pixabay_api_key": False}
    r = c.put("/api/setup/keys", json={"gemini_api_key": "AIzaSECRETSECRET123", "pixabay_api_key": "12345678-abcdef"})
    assert r.status_code == 200 and "SECRET" not in r.text
    assert r.json()["keys"] == {"gemini_api_key": True, "pixabay_api_key": True}
    assert s.gemini_api_key == "AIzaSECRETSECRET123"  # live, no restart needed
    f = tmp_path / "data" / ".env"
    assert "GEMINI_API_KEY=AIzaSECRETSECRET123" in f.read_text()
    if os.name != "nt":                                              # Windows has no owner-only file mode
        assert oct(f.stat().st_mode & 0o777) == "0o600"
    c.put("/api/setup/keys", json={"gemini_api_key": "AIzaOTHEROTHER456"})
    text = f.read_text()
    assert text.count("GEMINI_API_KEY") == 1 and "PIXABAY_API_KEY=12345678-abcdef" in text


def test_a_key_with_newlines_or_spaces_is_refused(tmp_path, monkeypatch):
    s, c = make(tmp_path, monkeypatch)
    r = c.put("/api/setup/keys", json={"gemini_api_key": "abc12345\nPIXABAY_API_KEY=evil"})
    assert r.status_code == 422
    assert not (tmp_path / "data" / ".env").exists()


def test_model_download_runs_in_background(tmp_path, monkeypatch):
    s, c = make(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(models, "fetch_rnnoise", lambda s, say: calls.append("rnnoise"))
    monkeypatch.setattr(models, "fetch_face", lambda s, say: calls.append("face"))
    monkeypatch.setattr(models, "fetch_clip", lambda s, say: calls.append("clip"))
    monkeypatch.setattr(models, "fetch_whisper", lambda m, say: calls.append("whisper:" + m))
    monkeypatch.setattr(models, "whisper_ready", lambda m: False)
    assert c.post("/api/setup/models", json={"whisper": "base"}).status_code == 202
    for _ in range(100):
        d = c.get("/api/setup").json()["download"]
        if not d["running"]:
            break
        time.sleep(0.05)
    assert d["error"] is None and calls == ["rnnoise", "face", "clip", "whisper:base"]
    assert s.whisper_model == "base" and "WHISPER_MODEL=base" in (tmp_path / "data" / ".env").read_text()


def test_download_failure_is_one_readable_sentence(tmp_path, monkeypatch):
    s, c = make(tmp_path, monkeypatch)

    def boom(s, say):
        raise models.ModelError("Download failed: HTTP 503")

    monkeypatch.setattr(models, "fetch_rnnoise", boom)
    c.post("/api/setup/models", json={})
    for _ in range(100):
        d = c.get("/api/setup").json()["download"]
        if not d["running"]:
            break
        time.sleep(0.05)
    assert d["error"] == "Download failed: HTTP 503"
    assert c.post("/api/setup/models", json={"whisper": "huge"}).status_code == 422


def test_hosted_mode_has_no_setup_routes(tmp_path, monkeypatch):
    s, c = make(tmp_path, monkeypatch, mode="hosted", database_url=f"sqlite:///{tmp_path}/a.db")
    assert c.get("/api/setup").status_code in (401, 404)
