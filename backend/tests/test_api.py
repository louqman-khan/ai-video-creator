import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import ProjectStore
from app.config import Settings
from app.models import Segment, Transcript, Word
from app.pipeline.runner import Providers
from app.pipeline.scenes import chunk_scenes
from app.providers.audio_cleaner import NoopCleaner
from app.providers.media_ranker.heuristic import HeuristicRanker
from app.providers.media_search import CompositeSearch
from app.providers.media_search.local_folder import LocalFolderSearch

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
SECRET = "SECRET-KEY-123456"


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture()
def env(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    ff("-f", "lavfi", "-i", "color=c=blue:s=640x360", "-frames:v", "1", str(media / "blue sky.jpg"))
    tone = tmp_path / "tone.wav"
    ff("-f", "lavfi", "-i", "sine=frequency=300:duration=4", str(tone))
    words = [Word(text=f"w{i}", start=0.2 + i * 0.4, end=0.2 + i * 0.4 + 0.35) for i in range(8)]
    transcript = Transcript(language="en", duration=4.0, segments=[Segment(text="x", start=0, end=4, words=words)])
    gate = threading.Event()
    gate.set()

    class FakeTranscriber:
        def transcribe(self, audio, language=None):
            gate.wait(10)
            return transcript

    class FakePlanner:
        def plan(self, t):
            sc = chunk_scenes(t, 1.0, 8.0)
            for s in sc:
                s.query_en = "blue sky"
            return sc

    def factory(settings, options):
        return Providers(FakeTranscriber(), FakePlanner(), CompositeSearch([LocalFolderSearch(media)]),
                         HeuristicRanker(), NoopCleaner())

    settings = Settings(_env_file=None, projects_dir=str(tmp_path / "projects"), work_dir=str(tmp_path / "work"),
                        pixabay_api_key=SECRET, fonts_dir=str(tmp_path / "nofonts"))
    return settings, factory, tone, gate


def client(env, **override):
    settings, factory, *_ = env
    return TestClient(create_app(settings.model_copy(update=override), factory))


def upload(c, path, **data):
    with open(path, "rb") as f:
        return c.post("/api/projects", files={"file": (path.name, f, "audio/wav")}, data=data)


def wait_done(c, pid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/api/projects/{pid}").json()
        if p["status"] in ("done", "failed"):
            return p
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_full_flow_upload_progress_video_credits_delete(env):
    _, _, tone, _ = env
    with client(env) as c:
        h = c.get("/api/health").json()
        assert h["ok"] is True and ".mp3" in h["limits"]["extensions"] and h["limits"]["max_upload_mb"] == 200
        r = upload(c, tone, aspect="16:9", clean="false")
        assert r.status_code == 202
        p = r.json()
        assert p["status"] in ("queued", "running") and p["name"] == "tone" and p["audio_file"] == "upload.wav"
        done = wait_done(c, p["id"])
        assert done["status"] == "done" and done["progress"] == 1.0 and done["video_ready"] and done["error"] is None
        v = c.get(f"/api/projects/{p['id']}/video")
        assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and b"ftyp" in v.content[:32]
        assert "License" in c.get(f"/api/projects/{p['id']}/credits").text or "User-provided" in c.get(f"/api/projects/{p['id']}/credits").text
        assert [x["id"] for x in c.get("/api/projects").json()] == [p["id"]]
        assert c.delete(f"/api/projects/{p['id']}").status_code == 204
        assert c.get(f"/api/projects/{p['id']}").status_code == 404


def test_rejects_bad_uploads_and_leaves_nothing_behind(env, tmp_path):
    _, _, tone, _ = env
    notaudio = tmp_path / "fake.mp3"
    notaudio.write_text("this is not audio")
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    with client(env) as c:
        assert upload(c, txt).status_code == 415
        assert upload(c, notaudio).status_code == 400
        assert upload(c, tone, aspect="4:3").status_code == 422
        assert upload(c, tone, language="fr").status_code == 422
        assert upload(c, tone, style='{"color": "yellow"}').status_code == 422
        assert upload(c, tone, style='{"colour": "#fff"}').status_code == 422  # unknown key
        assert c.get("/api/projects").json() == []  # nothing half-created
    with client(env, max_upload_mb=0) as c:
        assert upload(c, tone).status_code == 413
        assert c.get("/api/projects").json() == []
    with client(env, max_audio_minutes=0.01) as c:  # 0.6 s limit, the tone is 4 s
        assert upload(c, tone).status_code == 413
        assert c.get("/api/projects").json() == []


def test_ids_are_validated_no_path_traversal(env):
    with client(env) as c:
        for bad in ("..", "xyz", "0" * 31, "../../etc/passwd", "%2e%2e"):
            assert c.get(f"/api/projects/{bad}").status_code == 404
        assert c.get(f"/api/projects/{'0' * 32}").status_code == 404
        assert c.get(f"/api/projects/{'0' * 32}/video").status_code == 404


def test_failed_job_reports_error_with_secrets_redacted(env):
    settings, _, tone, _ = env

    def boom(s, o):
        raise RuntimeError(f"upstream said key={SECRET} is invalid")

    with TestClient(create_app(settings, boom)) as c:
        p = upload(c, tone).json()
        done = wait_done(c, p["id"])
        assert done["status"] == "failed" and "RuntimeError" in done["error"]
        assert SECRET not in done["error"] and "***" in done["error"]
        assert c.get(f"/api/projects/{p['id']}/video").status_code == 409
        assert c.delete(f"/api/projects/{p['id']}").status_code == 204  # failed ones can be removed


def test_cannot_delete_while_processing_and_progress_is_visible(env):
    _, _, tone, gate = env
    gate.clear()  # hold the job inside "transcribe"
    with client(env) as c:
        p = upload(c, tone).json()
        for _ in range(100):
            cur = c.get(f"/api/projects/{p['id']}").json()
            if cur["status"] == "running" and cur["stage"] == "transcribe":
                break
            time.sleep(0.1)
        assert cur["status"] == "running" and 0 < cur["progress"] < 0.5 and cur["message"]
        assert c.delete(f"/api/projects/{p['id']}").status_code == 409
        assert c.get(f"/api/projects/{p['id']}/video").status_code == 409
        gate.set()
        assert wait_done(c, p["id"])["status"] == "done"


def test_restart_marks_interrupted_projects_failed(env):
    settings, factory, *_ = env
    store = ProjectStore(Path(settings.projects_dir))
    stuck = store.create("stuck", status="running")
    with TestClient(create_app(settings, factory)) as c:  # startup runs the recovery
        p = c.get(f"/api/projects/{stuck.id}").json()
        assert p["status"] == "failed" and "restarted" in p["error"]
