import json
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
    ff("-f", "lavfi", "-i", "color=c=green:s=640x360", "-frames:v", "1", str(media / "green sky.jpg"))
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

    settings = Settings(_env_file=None, frontend_dist=str(tmp_path / "no-web-app"), projects_dir=str(tmp_path / "projects"), work_dir=str(tmp_path / "work"),
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


# ---------------------------------------------------------------- scenes / swap (task 3.4)

def finished_project(c, tone):
    p = upload(c, tone, clean="false", normalize="false").json()
    assert wait_done(c, p["id"])["status"] == "done"
    return p["id"]


def test_scene_list_hides_download_urls_and_serves_thumbnails(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        r = c.get(f"/api/projects/{pid}/scenes")
        assert r.status_code == 200
        scenes = r.json()
        assert scenes and all(s["text"] and s["end"] > s["start"] for s in scenes)
        first = scenes[0]
        assert first["asset"]["id"].startswith("local:") and first["asset"]["license"] and first["has_thumb"]
        assert "url" not in first["asset"] and "local_path" not in first["asset"]
        assert "file:" not in r.text and str(tone.parent) not in r.text  # no local paths either
        t = c.get(f"/api/projects/{pid}/scenes/{first['id']}/thumb")
        assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg" and t.content[:2] == b"\xff\xd8"
        assert c.get(f"/api/projects/{pid}/scenes/999/thumb").status_code == 404


def test_scenes_not_ready_yet_and_unknown_project(env):
    _, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.get(f"/api/projects/{p['id']}/scenes").status_code == 409
        gate.set()
        wait_done(c, p["id"])
        assert c.get(f"/api/projects/{'0' * 32}/scenes").status_code == 404


def test_swap_visual_end_to_end(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        before = c.get(f"/api/projects/{pid}").json()
        scene = c.get(f"/api/projects/{pid}/scenes").json()[0]
        cands = c.get(f"/api/projects/{pid}/scenes/{scene['id']}/candidates", params={"query": "sky"})
        assert cands.status_code == 200 and len(cands.json()) == 2
        assert all("url" not in a for a in cands.json())
        other = next(a for a in cands.json() if a["id"] != scene["asset"]["id"])

        r = c.post(f"/api/projects/{pid}/scenes/{scene['id']}/swap", json={"asset_id": other["id"]})
        assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["error"] is None and done["video_ready"]
        assert done["updated_at"] != before["updated_at"]
        after = c.get(f"/api/projects/{pid}/scenes").json()
        assert after[0]["asset"]["id"] == other["id"]
        assert [s["asset"]["id"] for s in after[1:]] == [s["asset"]["id"] for s in c.get(f"/api/projects/{pid}/scenes").json()[1:]]
        assert "License:" in (Path(settings.projects_dir) / pid / "CREDITS.txt").read_text()  # credits regenerated
        assert c.get(f"/api/projects/{pid}/video").status_code == 200  # still playable
        # the thumbnail now shows the new visual (a different file name, a fresh image)
        assert c.get(f"/api/projects/{pid}/scenes/{scene['id']}/thumb").status_code == 200


def test_swap_rejects_anything_the_server_did_not_offer(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        sid = c.get(f"/api/projects/{pid}/scenes").json()[0]["id"]
        swap = lambda body, s=sid: c.post(f"/api/projects/{pid}/scenes/{s}/swap", json=body)  # noqa: E731
        assert swap({"asset_id": "local:blue sky.jpg"}).status_code == 400   # real id, but never offered yet
        c.get(f"/api/projects/{pid}/scenes/{sid}/candidates", params={"query": "sky"})
        for evil in ("http://evil.example/x.mp4", "file:///etc/passwd", "../../etc/passwd", "local:nope.jpg"):
            assert swap({"asset_id": evil}).status_code == 400, evil
        assert swap({"url": "http://evil.example/x.mp4"}).status_code == 422  # a URL field is not even accepted
        assert swap({"asset_id": ""}).status_code == 422
        assert swap({"asset_id": "local:blue sky.jpg"}, 999).status_code == 404
        assert c.get(f"/api/projects/{pid}/scenes/{sid}/candidates", params={"query": "x" * 101}).status_code == 422
        assert c.get(f"/api/projects/{pid}/scenes/999/candidates").status_code == 404


def test_swap_not_allowed_while_processing(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        sid = c.get(f"/api/projects/{pid}/scenes").json()[0]["id"]
        cand = c.get(f"/api/projects/{pid}/scenes/{sid}/candidates", params={"query": "sky"}).json()[0]
        assert c.post(f"/api/projects/{pid}/scenes/{sid}/swap", json={"asset_id": cand["id"]}).status_code == 202
        assert c.post(f"/api/projects/{pid}/scenes/{sid}/swap", json={"asset_id": cand["id"]}).status_code == 409
        wait_done(c, pid)


def test_failed_swap_keeps_the_existing_video(env, tmp_path):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        sid = c.get(f"/api/projects/{pid}/scenes").json()[0]["id"]
        current = c.get(f"/api/projects/{pid}/scenes").json()[0]["asset"]["id"]
        cands = c.get(f"/api/projects/{pid}/scenes/{sid}/candidates", params={"query": "sky"}).json()
        other = next(a for a in cands if a["id"] != current)
        (tmp_path / "media" / (other["title"] + ".jpg")).unlink()  # the source vanishes before the download
        c.post(f"/api/projects/{pid}/scenes/{sid}/swap", json={"asset_id": other["id"]})
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["video_ready"] and "Could not apply the change" in done["error"]
        assert c.get(f"/api/projects/{pid}/video").status_code == 200
        assert c.get(f"/api/projects/{pid}/scenes").json()[0]["asset"]["id"] == current  # unchanged


# ---------------------------------------------------------------- captions (task 3.5)

def ass_of(settings, pid):
    return (Path(settings.projects_dir) / pid / "captions_preview.ass").read_text("utf-8")  # edits re-render the preview


def test_read_edit_and_reset_caption_text(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        cap = c.get(f"/api/projects/{pid}/captions").json()
        assert cap["edited"] is False and cap["language"] == "en" and cap["style"] == {}
        assert [x["id"] for x in cap["cues"]] == list(range(len(cap["cues"]))) and cap["cues"]
        original = cap["cues"][0]["text"]

        edits = [{"id": x["id"], "text": x["text"]} for x in cap["cues"]]
        edits[0]["text"] = "  Corrected\x00 text \n here  "  # control characters and spacing are cleaned
        r = c.put(f"/api/projects/{pid}/captions", json={"cues": edits})
        assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
        assert wait_done(c, pid)["status"] == "done"
        after = c.get(f"/api/projects/{pid}/captions").json()
        assert after["edited"] is True and after["cues"][0]["text"] == "Corrected text here"
        assert [x["start"] for x in after["cues"]] == [x["start"] for x in cap["cues"]]  # timing untouched
        assert "Corrected text here" in ass_of(settings, pid)  # and it reached the render

        assert c.delete(f"/api/projects/{pid}/captions").status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        back = c.get(f"/api/projects/{pid}/captions").json()
        assert back["edited"] is False and back["cues"][0]["text"] == original
        assert c.delete(f"/api/projects/{pid}/captions").status_code == 400  # nothing left to reset


def test_style_change_is_stored_and_rendered(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        r = c.put(f"/api/projects/{pid}/captions", json={"style": {"color": "#FFFF00", "position": "top"}})
        assert r.status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        cap = c.get(f"/api/projects/{pid}/captions").json()
        assert cap["style"]["color"] == "#FFFF00" and cap["edited"] is False
        style_line = next(l for l in ass_of(settings, pid).splitlines() if l.startswith("Style:"))
        assert "&H0000FFFF" in style_line and ",8," in style_line  # yellow, top alignment
        # sending the same style again is a no-op, not another render
        assert c.put(f"/api/projects/{pid}/captions", json={"style": {"color": "#FFFF00", "position": "top"}}).status_code == 400


def test_caption_update_validation_and_injection(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        cap = c.get(f"/api/projects/{pid}/captions").json()
        n = len(cap["cues"])
        put = lambda body: c.put(f"/api/projects/{pid}/captions", json=body)  # noqa: E731
        assert put({}).status_code == 400
        assert put({"cues": [{"id": x["id"], "text": x["text"]} for x in cap["cues"]]}).status_code == 400  # no change
        assert put({"cues": [{"id": 0, "text": "x"}]}).status_code == 409 if n > 1 else True               # stale list
        assert put({"cues": [{"id": i + 1, "text": "x"} for i in range(n)]}).status_code == 409              # wrong ids
        assert put({"cues": [{"id": 0, "text": "x" * 301}]}).status_code == 422
        assert put({"style": {"color": "yellow"}}).status_code == 422
        assert put({"style": {"font": "Arial,0,0\nStyle: Evil"}}).status_code == 422                          # ASS injection
        assert put({"style": {"colour": "#fff"}}).status_code == 422                                          # unknown key
        # ASS override tags in the text are neutralised
        edits = [{"id": x["id"], "text": x["text"]} for x in cap["cues"]]
        edits[0]["text"] = r"{\fs300\pos(0,0)}Big \Nbreak"
        assert put({"cues": edits}).status_code == 202
        wait_done(c, pid)
        ass = ass_of(settings, pid)
        assert "{\\fs300" not in ass and "\\N" not in ass.split("[Events]")[1]


def test_caption_endpoints_blocked_while_processing_or_unknown(env):
    _, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.get(f"/api/projects/{p['id']}/captions").status_code == 409
        assert c.put(f"/api/projects/{p['id']}/captions", json={"style": {"bold": True}}).status_code == 409
        assert c.delete(f"/api/projects/{p['id']}/captions").status_code == 409
        assert c.post(f"/api/projects/{p['id']}/captions/preview", json={}).status_code == 409
        gate.set()
        wait_done(c, p["id"])
        assert c.get(f"/api/projects/{'0' * 32}/captions").status_code == 404


def test_preview_renders_a_real_frame_with_the_requested_style(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        url = f"/api/projects/{pid}/captions/preview"
        plain = c.post(url, json={"text": "Preview text"})
        yellow = c.post(url, json={"text": "Preview text", "style": {"color": "#FFFF00", "size_pct": 12}})
        assert plain.status_code == 200 and plain.headers["content-type"] == "image/jpeg"
        assert plain.content[:2] == b"\xff\xd8" and yellow.content[:2] == b"\xff\xd8"
        assert plain.content != yellow.content                      # the style really changed the picture
        assert plain.headers["cache-control"] == "no-store"
        assert c.post(url, json={"text": "   "}).status_code == 422
        assert c.post(url, json={"cue_id": 999}).status_code == 404
        assert c.post(url, json={"text": "x" * 301}).status_code == 422
        assert c.post(url, json={"style": {"font": "a,b"}}).status_code == 422
        # nothing was left behind in the project folder
        assert list((Path(env[0].projects_dir) / pid / "preview").glob("*")) == []


# ---------------------------------------------------------------- preview + export (task 3.6)

def dims(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def test_new_projects_get_a_fast_preview_and_no_export_yet(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        info = c.get(f"/api/projects/{pid}").json()
        assert info["video_ready"] is True and info["export_ready"] is False and info["export_aspect"] is None
        assert dims(d / "preview.mp4") == (960, 540) and not (d / "output.mp4").exists()
        v = c.get(f"/api/projects/{pid}/video")
        assert v.status_code == 200 and b"ftyp" in v.content[:32]
        assert c.get(f"/api/projects/{pid}/export").status_code == 409  # nothing exported yet


def test_export_renders_full_quality_in_both_aspects(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        r = c.post(f"/api/projects/{pid}/export")  # no body: the project's own format
        assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["export_ready"] is True and done["export_aspect"] == "16:9" and done["error"] is None
        got = c.get(f"/api/projects/{pid}/export")
        assert got.status_code == 200 and got.headers["content-type"] == "video/mp4" and b"ftyp" in got.content[:32]
        assert "attachment" in got.headers["content-disposition"] and "16x9" in got.headers["content-disposition"]
        assert dims(d / "output.mp4") == (1920, 1080)
        assert dims(d / "preview.mp4") == (960, 540)  # the preview is untouched by an export

        c.post(f"/api/projects/{pid}/export", json={"aspect": "9:16"})
        done = wait_done(c, pid)
        assert done["export_ready"] is True and done["export_aspect"] == "9:16"
        assert dims(d / "output.mp4") == (1080, 1920)
        assert dims(d / "preview.mp4") == (960, 540)


def test_edits_make_the_export_stale_and_rerender_only_the_preview(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        c.post(f"/api/projects/{pid}/export")
        assert wait_done(c, pid)["export_ready"] is True
        assert (d / "output.mp4").exists()
        c.put(f"/api/projects/{pid}/captions", json={"style": {"bold": True}})
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["export_ready"] is False and done["export_aspect"] is None
        assert not (d / "output.mp4").exists()                       # a stale export is never offered
        assert c.get(f"/api/projects/{pid}/export").status_code == 409
        assert dims(d / "preview.mp4") == (960, 540)
        # exporting again picks the edit up
        c.post(f"/api/projects/{pid}/export")
        assert wait_done(c, pid)["export_ready"] is True
        style_line = next(l for l in (d / "captions.ass").read_text().splitlines() if l.startswith("Style:"))
        assert ",-1,0,0,0," in style_line  # bold made it into the full-quality file


def test_export_validation_and_busy_rules(env, monkeypatch):
    import threading

    from app.pipeline import assemble

    _, _, tone, gate = env
    hold = threading.Event()                      # keeps the export "running" until the test has checked the busy rule (no race with a fast machine)
    real = assemble.concat_and_finish

    def slow(*args, **kwargs):
        hold.wait(30)
        return real(*args, **kwargs)

    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.post(f"/api/projects/{p['id']}/export").status_code == 409        # still processing
        gate.set()
        wait_done(c, p["id"])
        assert c.post(f"/api/projects/{p['id']}/export", json={"aspect": "4:3"}).status_code == 422
        monkeypatch.setattr(assemble, "concat_and_finish", slow)
        assert c.post(f"/api/projects/{p['id']}/export", json={"aspect": "9:16"}).status_code == 202
        assert c.post(f"/api/projects/{p['id']}/export").status_code == 409        # already exporting
        hold.set()
        wait_done(c, p["id"])
        assert c.post(f"/api/projects/{'0' * 32}/export").status_code == 404
        assert c.get(f"/api/projects/{'0' * 32}/export").status_code == 404


def test_failed_export_keeps_the_project_usable(env, monkeypatch):
    from app.pipeline import assemble

    _, _, tone, _ = env
    real = assemble.concat_and_finish

    def flaky(*args, **kwargs):  # only the full-quality encode breaks
        profile = args[7] if len(args) > 7 else kwargs.get("profile")
        if profile is not None and profile.name == "final":
            raise assemble.ffmpeg.FfmpegError("disk full")
        return real(*args, **kwargs)

    with client(env) as c:
        pid = finished_project(c, tone)
        monkeypatch.setattr(assemble, "concat_and_finish", flaky)
        c.post(f"/api/projects/{pid}/export")
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["video_ready"] is True and done["export_ready"] is False
        assert "The export failed" in done["error"] and "disk full" in done["error"]
        assert c.get(f"/api/projects/{pid}/video").status_code == 200   # the preview still plays
        assert c.get(f"/api/projects/{pid}/captions").status_code == 200  # and the editor still works


def test_videos_are_never_served_from_a_stale_browser_cache(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        assert c.get(f"/api/projects/{pid}/video").headers["cache-control"] == "no-cache"
        c.post(f"/api/projects/{pid}/export")
        wait_done(c, pid)
        assert c.get(f"/api/projects/{pid}/export").headers["cache-control"] == "no-cache"


# ---------------------------------------------------------------- credits (task 3.7)

def test_attributions_are_deduplicated_with_their_scenes_and_hide_urls(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        scenes = c.get(f"/api/projects/{pid}/scenes").json()
        r = c.get(f"/api/projects/{pid}/attributions")
        assert r.status_code == 200
        items = r.json()
        ids = [i["asset"]["id"] for i in items]
        assert len(ids) == len(set(ids))                                    # each visual listed once
        used = {s["asset"]["id"] for s in scenes if s["asset"]}
        assert set(ids) == used
        # every scene that uses a visual is listed against it
        for i in items:
            assert i["scenes"] == [s["id"] for s in scenes if s["asset"] and s["asset"]["id"] == i["asset"]["id"]]
            assert i["asset"]["license"] and "url" not in i["asset"] and "local_path" not in i["asset"]
        assert c.get(f"/api/projects/{'0' * 32}/attributions").status_code == 404
        assert c.get(f"/api/projects/{pid}/attributions").json() == items   # stable


def test_attributions_not_ready_while_processing(env):
    _, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.get(f"/api/projects/{p['id']}/attributions").status_code == 409
        gate.set()
        wait_done(c, p["id"])


# ---------------------------------------------------------------- timeline document (task 4.1)

def put_tl(c, pid, tl, **over):
    body = {"base_rev": tl["rev"], "tracks": tl["tracks"], "clips": tl["clips"], "caption_style": tl["caption_style"], **over}
    return c.put(f"/api/projects/{pid}/timeline", json=body)


def test_timeline_is_built_from_the_project_and_hides_server_paths(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        r = c.get(f"/api/projects/{pid}/timeline")
        assert r.status_code == 200
        tl = r.json()
        assert tl["rev"] == 1 and tl["fps"] == 30 and tl["aspect"] == "16:9"
        assert [t["id"] for t in tl["tracks"]] == ["V1", "A1", "C1"]
        scenes = c.get(f"/api/projects/{pid}/scenes").json()
        v1 = [x for x in tl["clips"] if x["track"] == "V1"]
        assert len(v1) == len([s for s in scenes if s["asset"]])
        assert any(x["track"] == "A1" for x in tl["clips"]) and any(x["track"] == "C1" for x in tl["clips"])
        nar = next(x for x in tl["clips"] if x["track"] == "A1")
        assert tl["duration"] >= nar["duration"] and all(isinstance(x["start"], int) and isinstance(x["duration"], int) for x in tl["clips"])
        assert all(a["license"] for a in tl["assets"].values())
        assert "path" not in r.text and "file:" not in r.text and str(settings.projects_dir) not in r.text and str(settings.work_dir) not in r.text
        assert all("url" not in a and "path" not in a for a in tl["assets"].values())
        assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == 1       # reading never bumps the revision
        assert (Path(settings.projects_dir) / pid / "timeline.json").is_file()


def test_timeline_unavailable_while_processing_or_unknown(env):
    _, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.get(f"/api/projects/{p['id']}/timeline").status_code == 409
        gate.set()
        wait_done(c, p["id"])
        assert c.get(f"/api/projects/{'0' * 32}/timeline").status_code == 404
        assert c.put(f"/api/projects/{'0' * 32}/timeline", json={"base_rev": 1, "tracks": [], "clips": []}).status_code == 404


def test_timeline_edit_roundtrip_and_revisions(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        nar = next(x for x in tl["clips"] if x["track"] == "A1")
        nar["volume"] = 0.5
        r = put_tl(c, pid, tl)
        assert r.status_code == 200 and r.json()["rev"] == 2
        again = c.get(f"/api/projects/{pid}/timeline").json()
        assert again["rev"] == 2 and next(x for x in again["clips"] if x["track"] == "A1")["volume"] == 0.5
        # a second tab that still has revision 1 must not overwrite
        stale = put_tl(c, pid, tl)
        assert stale.status_code == 409 and stale.headers["x-current-rev"] == "2" and "revision 2" in stale.json()["detail"]
        assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == 2
        # the file on disk is the saved document, not a half-written one
        saved = json.loads((Path(settings.projects_dir) / pid / "timeline.json").read_text())
        assert saved["rev"] == 2 and saved["schema_version"] == 1


def test_timeline_put_without_opening_it_first_is_refused(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        assert c.delete(f"/api/projects/{pid}/timeline").status_code == 204      # e.g. an older project, or after a reset
        r = c.put(f"/api/projects/{pid}/timeline", json={"base_rev": 1, "tracks": [], "clips": []})
        assert r.status_code == 409 and "Open the timeline first" in r.json()["detail"]


def test_timeline_put_rejects_invalid_documents(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        v1 = [x for x in tl["clips"] if x["track"] == "V1"]

        def mutate(fn, expect=422, contains=""):
            doc = json.loads(json.dumps(tl))
            body = fn(doc) or doc
            r = put_tl(c, pid, doc) if body is doc else c.put(f"/api/projects/{pid}/timeline", json=body)
            assert r.status_code == expect, (r.status_code, r.text[:200])
            assert contains in r.text, r.text[:300]
            assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == 1  # nothing was saved

        def overlap(d):
            clips = [x for x in d["clips"] if x["track"] == "V1"]
            clips[1]["start"] = clips[0]["start"] + 1
        if len(v1) > 1:
            mutate(overlap, contains="overlap")
        mutate(lambda d: d["clips"][0].update(asset="does-not-exist"), contains="unknown asset")
        mutate(lambda d: d["clips"][0].update(track="NOPE"), contains="unknown track")
        mutate(lambda d: d["clips"][0].update(start=-1))
        mutate(lambda d: d["clips"][0].update(duration=0))
        mutate(lambda d: d["clips"][0].update(duration=10 ** 9))
        mutate(lambda d: d["clips"][0].update(volume=99))
        mutate(lambda d: d["clips"][0].update(id="has space"))
        mutate(lambda d: d["clips"][0].update(url="http://evil.example/x.mp4"))          # unknown field
        mutate(lambda d: d["clips"][0].update(path="/etc/passwd"))                        # unknown field
        mutate(lambda d: d["clips"][0].update(text="x" * 301))
        mutate(lambda d: d["clips"].extend({**d["clips"][-1], "id": f"extra{i}", "start": 10 ** 6 + i * 10} for i in range(2001)))
        mutate(lambda d: d["clips"].append(dict(d["clips"][0])), contains="duplicate")
        mutate(lambda d: d.update(caption_style={"color": "yellow"}))
        mutate(lambda d: d.update(caption_style={"font": "a,b"}))
        # the browser cannot add or change assets, rev, or any other top-level field
        for extra in ({"assets": {"x": {"id": "x", "kind": "video", "path": "/etc/passwd", "license": "L"}}}, {"rev": 99}, {"fps": 1}):
            r = c.put(f"/api/projects/{pid}/timeline", json={"base_rev": 1, "tracks": tl["tracks"], "clips": tl["clips"], **extra})
            assert r.status_code == 422, extra
        assert c.put(f"/api/projects/{pid}/timeline", json={"tracks": [], "clips": []}).status_code == 422   # base_rev missing
        assert c.put(f"/api/projects/{pid}/timeline", json={"base_rev": 0, "tracks": [], "clips": []}).status_code == 422
        assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == 1


def test_timeline_reset_needs_confirmation_when_edited(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        f = Path(settings.projects_dir) / pid / "timeline.json"
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert c.delete(f"/api/projects/{pid}/timeline").status_code == 204 and not f.exists()   # unedited: free to drop
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert f.exists() and tl["rev"] == 1                                                       # rebuilt on demand
        tl["clips"][0]["volume"] = 0.5
        assert put_tl(c, pid, tl).status_code == 200
        refused = c.delete(f"/api/projects/{pid}/timeline")
        assert refused.status_code == 409 and "discard" in refused.json()["detail"] and f.exists()
        assert c.delete(f"/api/projects/{pid}/timeline", params={"discard_edits": "true"}).status_code == 204
        assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == 1


def frame_rgb(path, t):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return tuple(out[:3])


def test_an_unedited_timeline_follows_step3_changes(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        f = Path(settings.projects_dir) / pid / "timeline.json"
        c.get(f"/api/projects/{pid}/timeline")
        assert f.exists()
        # a Step 3 edit re-renders from the project's files: the render rebuilds the (never-edited) timeline, so it is current afterwards
        assert c.put(f"/api/projects/{pid}/captions", json={"style": {"bold": True}}).status_code == 202
        wait_done(c, pid)
        assert f.exists()
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert tl["caption_style"]["bold"] is True and tl["rev"] == 1
        # and it stays usable: it can be edited right after a render
        tl["clips"][0]["volume"] = 0.9
        assert put_tl(c, pid, tl).status_code == 200


def test_step3_screens_act_on_an_edited_timeline(env):
    """After the timeline has been edited it is the only truth: swap, captions and export all work ON it."""
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        tl["clips"][0]["volume"] = 0.5                                          # any edit makes the timeline "edited"
        assert put_tl(c, pid, tl).status_code == 200

        # --- swap a visual: the picture changes, and it changes inside the timeline
        scene = c.get(f"/api/projects/{pid}/scenes").json()[0]
        before = frame_rgb(d / "preview.mp4", 0.3)
        cands = c.get(f"/api/projects/{pid}/scenes/{scene['id']}/candidates", params={"query": "sky"}).json()
        other = next(a for a in cands if a["id"] != scene["asset"]["id"])
        assert c.post(f"/api/projects/{pid}/scenes/{scene['id']}/swap", json={"asset_id": other["id"]}).status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        after_tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert after_tl["rev"] == 3 and other["id"] in after_tl["assets"]
        assert next(x for x in after_tl["clips"] if x["id"] == f"scene-{scene['id']}")["asset"] == other["id"]
        assert c.get(f"/api/projects/{pid}/scenes").json()[0]["asset"]["id"] == other["id"]      # the scene list is a view over it
        assert frame_rgb(d / "preview.mp4", 0.3) != before                                         # blue <-> green: really re-rendered

        # --- edit a caption: it lands on the caption clip, and the reset is refused (the timeline is the truth)
        cap = c.get(f"/api/projects/{pid}/captions").json()
        assert cap["edited"] is True
        edits = [{"id": x["id"], "text": x["text"]} for x in cap["cues"]]
        edits[0]["text"] = "Edited in the timeline"
        assert c.put(f"/api/projects/{pid}/captions", json={"cues": edits, "style": {"color": "#FFFF00"}}).status_code == 202
        wait_done(c, pid)
        tl2 = c.get(f"/api/projects/{pid}/timeline").json()
        assert tl2["rev"] == 4 and tl2["caption_style"]["color"] == "#FFFF00"
        assert any(x["text"] == "Edited in the timeline" for x in tl2["clips"] if x["track"] == "C1")
        assert "Edited in the timeline" in (d / "captions_preview.ass").read_text()
        assert c.get(f"/api/projects/{pid}/captions").json()["cues"][0]["text"] == "Edited in the timeline"
        assert c.delete(f"/api/projects/{pid}/captions").status_code == 409
        assert c.put(f"/api/projects/{pid}/captions", json={"cues": edits}).status_code == 400         # nothing changed

        # --- export renders the edited timeline: hide the picture track and the export is black
        tl2["tracks"] = [{**t, "muted": True} if t["id"] == "V1" else t for t in tl2["tracks"]]
        assert put_tl(c, pid, tl2).status_code == 200
        assert c.post(f"/api/projects/{pid}/export").status_code == 202
        done = wait_done(c, pid)
        assert done["export_ready"] is True and done["error"] is None
        assert sum(frame_rgb(d / "output.mp4", 0.3)) < 60 and (d / "output.mp4").stat().st_size > 0
        assert (d / "CREDITS.txt").is_file()
        assert c.get(f"/api/projects/{pid}/video").status_code == 200


def test_features_the_renderer_cannot_do_yet_are_reported_and_keep_the_last_preview(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        good = (d / "preview.mp4").read_bytes()
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        v1 = next(x for x in tl["clips"] if x["track"] == "V1")
        nar = next(x for x in tl["clips"] if x["kind"] == "audio")
        nar["effects"] = [{"type": "blur", "value": 10}]
        assert put_tl(c, pid, tl).status_code == 200                                # the document may hold it ...
        assert c.put(f"/api/projects/{pid}/captions", json={"style": {"bold": True}}).status_code == 202
        done = wait_done(c, pid)                                                    # ... but the renderer says so, in plain words
        assert done["status"] == "done" and done["video_ready"] is True
        assert "Not supported yet" in done["error"] and "audio" in done["error"]
        assert (d / "preview.mp4").read_bytes() == good                             # the last good preview is untouched
        assert c.get(f"/api/projects/{pid}/video").status_code == 200
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        next(x for x in tl["clips"] if x["kind"] == "audio")["effects"] = []
        assert put_tl(c, pid, tl).status_code == 200
        assert c.put(f"/api/projects/{pid}/captions", json={"style": {"bold": False}}).status_code == 202
        assert wait_done(c, pid)["error"] is None



# ---------------------------------------------------------------- editor media pipeline (task 4.2)

def wait_media(c, pid, ids=None, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        items = c.get(f"/api/projects/{pid}/media").json()
        pick = [m for m in items if ids is None or m["asset_id"] in ids]
        if pick and all(m["status"] in ("ready", "failed") for m in pick):
            return {m["asset_id"]: m for m in pick}
        time.sleep(0.3)
    raise AssertionError("media was not prepared in time")


def make_clip(path, seconds=2, audio=True):
    args = ["-f", "lavfi", "-i", f"testsrc=s=320x180:r=30:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    ff(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac", "-shortest"] if audio else []), str(path))


def post_media(c, pid, path, **data):
    data.setdefault("rights_confirmed", "true")
    with open(path, "rb") as f:
        return c.post(f"/api/projects/{pid}/media", files={"file": (path.name, f, "application/octet-stream")}, data=data)


def test_stock_and_narration_are_prepared_when_the_timeline_is_first_built(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        assert c.get(f"/api/projects/{pid}/timeline").status_code == 200          # first build triggers preparation
        media = wait_media(c, pid)
        assert "narration" in media and all(m["status"] == "ready" for m in media.values()), media
        nar = media["narration"]
        assert set(nar["derived"]) == {"audio", "peaks"} and nar["uploaded"] is False and nar["has_audio"]
        img = next(m for m in media.values() if m["kind"] == "image")
        assert img["derived"] == ["proxy"] and img["width"] == 640 and img["bytes"] > 0
        r = c.get(f"/api/projects/{pid}/media/proxy", params={"asset": img["asset_id"]})   # ids with spaces/colons work
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
        assert c.get(f"/api/projects/{pid}/media/audio", params={"asset": "narration"}).headers["content-type"] == "audio/mp4"
        peaks = c.get(f"/api/projects/{pid}/media/peaks", params={"asset": "narration"}).json()
        assert set(peaks["rates"]) == {"100", "10"} and len(peaks["rates"]["100"]) > 100
        assert c.get(f"/api/projects/{pid}/media/film", params={"asset": img["asset_id"]}).status_code == 404   # images have none
        # unknown ids and path-like ids never reach the file system
        for bad in ("nope", "../../etc/passwd", "/etc/passwd", "upload:../x"):
            assert c.get(f"/api/projects/{pid}/media/proxy", params={"asset": bad}).status_code == 404, bad
        assert c.get(f"/api/projects/{pid}/media/proxy").status_code == 422        # asset is required
        assert c.get(f"/api/projects/{'0' * 32}/media").status_code == 404


def test_upload_media_full_lifecycle(env, tmp_path):
    settings, _, tone, _ = env
    clip = tmp_path / "my holiday.mp4"
    make_clip(clip, 2)
    with client(env) as c:
        pid = finished_project(c, tone)
        rev = c.get(f"/api/projects/{pid}/timeline").json()["rev"]
        r = post_media(c, pid, clip, title="  Beach  ")
        assert r.status_code == 201
        m = r.json()
        assert m["uploaded"] is True and m["kind"] == "video" and m["title"] == "Beach" and m["asset_id"].startswith("upload:")
        assert m["status"] in ("pending", "processing", "ready") and abs(m["duration"] - 2) < 0.3
        # it is on the timeline now, appended without changing the revision, and without exposing paths
        tl = c.get(f"/api/projects/{pid}/timeline")
        assert tl.json()["rev"] == rev and m["asset_id"] in tl.json()["assets"]
        a = tl.json()["assets"][m["asset_id"]]
        assert a["license"] == "User-provided" and a["duration"] == 60 and a["kind"] == "video"
        assert "uploads" not in tl.text and "my holiday" not in tl.text and ".mp4" not in tl.text
        # stored under a server-chosen name, never the user's
        files = list((Path(settings.projects_dir) / pid / "uploads").iterdir())
        assert len(files) == 1 and files[0].name.endswith(".mp4") and "holiday" not in files[0].name

        ready = wait_media(c, pid, {m["asset_id"]})[m["asset_id"]]
        assert ready["status"] == "ready" and set(ready["derived"]) == {"proxy", "film", "audio", "peaks"}
        proxy = c.get(f"/api/projects/{pid}/media/proxy", params={"asset": m["asset_id"]})
        assert proxy.status_code == 200 and proxy.headers["content-type"] == "video/mp4" and b"ftyp" in proxy.content[:32]
        film = c.get(f"/api/projects/{pid}/media/film.json", params={"asset": m["asset_id"]}).json()
        assert film["thumb_width"] == 160 and film["count"] >= 4
        assert c.get(f"/api/projects/{pid}/media/film", params={"asset": m["asset_id"]}).headers["content-type"] == "image/jpeg"
        usage = c.get(f"/api/projects/{pid}/disk").json()
        assert usage["uploads_bytes"] > 0 and usage["derived_bytes"] > 0 and usage["total_bytes"] >= usage["project_bytes"] + usage["derived_bytes"] - 1

        # a clip using it blocks deletion; removing the clip frees it
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        tl["clips"].append({"id": "mine", "track": "V1", "kind": "video", "asset": m["asset_id"], "start": tl["duration"] + 30, "duration": 30})
        assert put_tl(c, pid, tl).status_code == 200
        assert c.delete(f"/api/projects/{pid}/media", params={"asset": m["asset_id"]}).status_code == 409
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        tl["clips"] = [x for x in tl["clips"] if x["id"] != "mine"]
        assert put_tl(c, pid, tl).status_code == 200
        assert c.delete(f"/api/projects/{pid}/media", params={"asset": m["asset_id"]}).status_code == 204
        assert m["asset_id"] not in c.get(f"/api/projects/{pid}/timeline").json()["assets"]
        assert list((Path(settings.projects_dir) / pid / "uploads").iterdir()) == []
        assert c.delete(f"/api/projects/{pid}/media", params={"asset": m["asset_id"]}).status_code == 404


def test_upload_rejections_leave_nothing_behind(env, tmp_path):
    settings, _, tone, _ = env
    good = tmp_path / "ok.mp4"
    make_clip(good, 2)
    playlist = tmp_path / "evil.mp4"
    playlist.write_text("#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/seg.ts\n")
    truncated = tmp_path / "cut.mp4"
    truncated.write_bytes(good.read_bytes()[:64])
    notmedia = tmp_path / "doc.pdf"
    notmedia.write_bytes(b"%PDF-1.4\n")
    with client(env) as c:
        pid = finished_project(c, tone)
        uploads = Path(settings.projects_dir) / pid / "uploads"
        assert post_media(c, pid, good, rights_confirmed="false").status_code == 400
        assert "right to use" in post_media(c, pid, good, rights_confirmed="false").json()["detail"]
        r = c.post(f"/api/projects/{pid}/media", files={"file": ("a.mp4", good.read_bytes())})            # field missing
        assert r.status_code == 400
        for bad in (playlist, truncated, notmedia):
            r = post_media(c, pid, bad)
            assert r.status_code == 400, (bad.name, r.status_code, r.text[:120])
        assert list(uploads.iterdir()) == []                                   # no .part files, no orphans
        assert c.post(f"/api/projects/{'0' * 32}/media", files={"file": ("a.mp4", b"x")}, data={"rights_confirmed": "true"}).status_code == 404
        assert c.get(f"/api/projects/{pid}/media").status_code == 200
    with client(env, max_media_minutes=0.01) as c:                             # 0.6 s limit; the clip is 2 s
        r = post_media(c, pid, good)
        assert r.status_code == 400 and "longer than" in r.json()["detail"]
    with client(env, max_media_upload_mb=0) as c:
        assert post_media(c, pid, good).status_code == 413
    with client(env, max_uploads_per_project=1) as c:
        assert post_media(c, pid, good).status_code == 201
        assert post_media(c, pid, good).status_code == 409
        wait_media(c, pid)
    assert [p for p in uploads.iterdir() if p.suffix == ".part"] == []


def test_only_uploaded_files_can_be_deleted(env):
    _, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        assert c.delete(f"/api/projects/{pid}/media", params={"asset": "narration"}).status_code == 400
        assert c.delete(f"/api/projects/{pid}/media", params={"asset": "nope"}).status_code == 404
        wait_media(c, pid)


def test_failed_preparation_is_reported_and_can_be_retried(env, tmp_path, monkeypatch):
    from app.api import media as media_mod

    real = media_mod.derive.derive_all
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full at /secret/path")
        return real(*args, **kwargs)

    clip = tmp_path / "v.mp4"
    make_clip(clip, 2, audio=False)
    with client(env) as c:
        pid = finished_project(c, tone := env[2])
        wait_media(c, pid)                                                     # let the stock/narration finish first
        monkeypatch.setattr(media_mod.derive, "derive_all", flaky)
        m = post_media(c, pid, clip).json()
        failed = wait_media(c, pid, {m["asset_id"]})[m["asset_id"]]
        assert failed["status"] == "failed" and failed["error"] == "this file could not be processed"
        assert "secret" not in json.dumps(failed)                              # internal error text never reaches the browser
        assert c.get(f"/api/projects/{pid}/media/proxy", params={"asset": m["asset_id"]}).status_code == 404
        assert c.post(f"/api/projects/{pid}/media/prepare").status_code == 202  # retry
        ok = wait_media(c, pid, {m["asset_id"]})[m["asset_id"]]
        assert ok["status"] == "ready" and ok["derived"] == ["proxy", "film"]   # silent video: no audio files
        assert c.get(f"/api/projects/{pid}/media/audio", params={"asset": m["asset_id"]}).status_code == 404


def test_worker_is_idempotent_and_remembers_state_across_restarts(tmp_path, monkeypatch):
    from app.api import media as media_mod
    from app.config import Settings

    settings = Settings(_env_file=None, work_dir=str(tmp_path / "work"))
    src = tmp_path / "pic.png"
    ff("-f", "lavfi", "-i", "testsrc=s=64x64", "-frames:v", "1", str(src))
    counter = {"n": 0}
    real = media_mod.derive.derive_all
    monkeypatch.setattr(media_mod.derive, "derive_all", lambda *a, **k: (counter.__setitem__("n", counter["n"] + 1), real(*a, **k))[1])
    w = media_mod.MediaWorker(settings)
    assert w.status(src)[0] == "pending"
    w.ensure(src); w.ensure(src); w.ensure(src)
    for _ in range(100):
        if w.status(src)[0] == "ready":
            break
        time.sleep(0.1)
    assert w.status(src)[0] == "ready" and counter["n"] == 1                   # three requests, one job
    w.ensure(src)
    time.sleep(0.3)
    assert counter["n"] == 1                                                   # ready: nothing to do
    w.shutdown()
    again = media_mod.MediaWorker(settings)                                    # "server restart"
    assert again.status(src)[0] == "ready"
    src.write_bytes(src.read_bytes() + b"\x00")                                # the file changed: derived files are stale
    assert again.status(src)[0] == "pending"
    again.shutdown()


def test_render_the_saved_timeline_on_request(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        assert c.delete(f"/api/projects/{pid}/timeline").status_code == 204
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 409          # open the timeline first
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert sum(frame_rgb(d / "preview.mp4", 0.3)) > 60                                 # a picture today
        tl["tracks"] = [{**t, "muted": True} if t["id"] == "V1" else t for t in tl["tracks"]]
        assert put_tl(c, pid, tl).status_code == 200
        assert sum(frame_rgb(d / "preview.mp4", 0.3)) > 60                                 # saving alone renders nothing
        r = c.post(f"/api/projects/{pid}/timeline/render")
        assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202           # already rendering: merged into the next run
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["error"] is None
        assert sum(frame_rgb(d / "preview.mp4", 0.3)) < 60                                 # the saved edit is now in the preview
        assert c.post(f"/api/projects/{'0' * 32}/timeline/render").status_code == 404


def test_editing_continues_while_a_render_runs_and_renders_are_merged(env, monkeypatch):
    import threading as th

    from app.api import jobs as jobs_mod

    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert tl["rev"] == 1
        # an unedited timeline is rebuilt by the render itself: nothing may touch it while one runs
        tl["clips"][0]["volume"] = 0.9
        assert put_tl(c, pid, tl).status_code == 200                                     # now it is edited
        real = jobs_mod.render_timeline
        started, release, runs = th.Event(), th.Event(), []

        def slow(*a, **k):
            runs.append(a[0].rev)
            started.set()
            release.wait(30)
            return real(*a, **k)

        monkeypatch.setattr(jobs_mod, "render_timeline", slow)
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202
        assert started.wait(20)
        info = c.get(f"/api/projects/{pid}").json()
        assert info["status"] == "running" and info["preview_rev"] == 2 - 1                # still the earlier preview (rev 1)
        # the user keeps editing and saving while the preview renders ...
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert tl["rev"] == 2
        tl["clips"][0]["volume"] = 0.8
        assert put_tl(c, pid, tl).status_code == 200
        tl["rev"] = 3
        tl["clips"][0]["volume"] = 0.7
        assert put_tl(c, pid, tl).status_code == 200
        # ... and asks for a new preview several times: those requests are merged into ONE waiting render
        for _ in range(4):
            assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202
        release.set()
        for _ in range(200):
            p = c.get(f"/api/projects/{pid}").json()
            if p["status"] == "done" and p["preview_rev"] == 4 and len(runs) == 2:
                break
            time.sleep(0.2)
        assert runs == [2, 4]                                                              # the first saw rev 2, the merged one rev 4
        assert p["preview_rev"] == 4 and p["status"] == "done" and p["error"] is None


def test_a_never_edited_timeline_is_not_touchable_during_a_render(env, monkeypatch):
    import threading as th

    from app.api import jobs as jobs_mod

    settings, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.get(f"/api/projects/{p['id']}/timeline").status_code == 409              # creating: not ready at all
        gate.set()
        wait_done(c, p["id"])
        info = c.get(f"/api/projects/{p['id']}").json()
        assert info["preview_rev"] == 1                                                    # the first render recorded its revision
        real = jobs_mod.render_timeline
        started, release = th.Event(), th.Event()
        # an unedited project re-renders through the pipeline: block that path instead
        from app.pipeline import runner as runner_mod
        real_pipe = runner_mod.render_timeline

        def slow(*a, **k):
            started.set()
            release.wait(30)
            return real_pipe(*a, **k)

        monkeypatch.setattr(runner_mod, "render_timeline", slow)
        assert c.put(f"/api/projects/{p['id']}/captions", json={"style": {"bold": True}}).status_code == 202
        assert started.wait(20)
        assert c.get(f"/api/projects/{p['id']}/timeline").status_code == 409              # being rebuilt by the render: hands off
        assert c.post(f"/api/projects/{p['id']}/timeline/render").status_code == 409
        release.set()
        wait_done(c, p["id"])


def test_stock_music_is_searched_added_credited_and_never_trusted_from_the_browser(env, monkeypatch):
    from urllib.parse import quote

    from app.models import MediaAsset
    from app.providers.media_search.openverse import OpenverseSearch

    settings, _, tone, _ = env
    song = MediaAsset(id="openverse:song-1", source="openverse", kind="audio", url=tone.resolve().as_uri(), duration=2.0, title="Calm song",
                      license="CC BY 4.0", license_url="https://cc/by", author="Zed", attribution='"Calm song" by Zed is licensed under CC BY 4.0',
                      attribution_required=True)
    monkeypatch.setattr(OpenverseSearch, "search_audio", lambda self, q, category="music", limit=12: [song])
    with client(env) as c:
        pid = finished_project(c, tone)
        r = c.get(f"/api/projects/{pid}/bin/search", params={"q": "calm", "kind": "music"})
        assert r.status_code == 200 and r.json()[0]["id"] == "openverse:song-1"
        assert "url" not in r.json()[0] and tone.name not in r.text                         # no download address for the browser
        assert c.post(f"/api/projects/{pid}/bin/add", json={"asset_id": "openverse:never-offered"}).status_code == 400
        assert c.post(f"/api/projects/{pid}/bin/add", json={"asset_id": "file:///etc/passwd"}).status_code == 400
        a = c.post(f"/api/projects/{pid}/bin/add", json={"asset_id": "openverse:song-1"})
        assert a.status_code == 201 and a.json()["kind"] == "audio" and a.json()["duration"] > 0
        assert "path" not in a.json() and "url" not in a.json()
        assert c.post(f"/api/projects/{pid}/bin/add", json={"asset_id": "openverse:song-1"}).json() == a.json()   # adding twice is harmless
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert tl["rev"] == 1 and "openverse:song-1" in tl["assets"]                        # append-only: nobody's edit conflicts
        # use it on a new audio track, then it is credited
        tl["tracks"].append({"id": "A2", "kind": "audio", "name": "Music", "muted": False, "locked": False, "duck": True})
        tl["clips"].append({**tl["clips"][0], "id": "music", "track": "A2", "kind": "audio", "asset": "openverse:song-1", "start": 0, "duration": 30,
                            "in_point": 0, "loop": False, "volume": 0.3, "fade_in": 0, "fade_out": 0, "text": None, "words": [], "meta": {}, "effects": []})
        assert put_tl(c, pid, tl).status_code == 200, put_tl(c, pid, tl).text
        att = c.get(f"/api/projects/{pid}/attributions").json()
        assert [x["asset"]["id"] for x in att if x["asset"]["kind"] == "audio"] == ["openverse:song-1"]
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        text = c.get(f"/api/projects/{pid}/credits").text
        assert "Calm song" in text and "CC BY 4.0" in text


def test_openverse_audio_parsing_keeps_only_web_links_and_accepts_streams_without_extension():
    import httpx
    import respx

    from app.providers.media_search.openverse import OpenverseSearch

    with respx.mock:
        respx.get("https://api.openverse.org/v1/audio/").mock(return_value=httpx.Response(200, json={"results": [
            {"id": "a", "url": "https://x/a.mp3", "duration": 125000, "license": "by", "license_version": "4.0", "creator": "Zed", "title": "A"},
            {"id": "b", "url": "ftp://x/b", "license": "cc0", "license_version": "1.0"},
            {"id": "c", "url": "https://x/c?trackid=3&format=mp32", "license": "cc0", "license_version": "1.0", "duration": None}]}))
        res = OpenverseSearch().search_audio("rain", "music")
    assert [r.id for r in res] == ["openverse:a", "openverse:c"]
    assert res[0].duration == 125.0 and res[0].kind == "audio" and res[0].attribution_required and not res[1].attribution_required


def test_changing_the_frame_shape_re_renders_the_preview_at_that_shape(env):
    import subprocess

    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        assert put_tl(c, pid, tl, aspect="3:2").status_code == 422                          # only the four known shapes
        r = put_tl(c, pid, tl, aspect="1:1")
        assert r.status_code == 200 and r.json()["aspect"] == "1:1"
        assert c.get(f"/api/projects/{pid}").json()["aspect"] == "1:1"                     # the project follows its timeline
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(d / "preview.mp4")],
                              capture_output=True, text=True).stdout.strip()
        assert size == "540,540"


def test_export_presets_sizes_encoders_and_estimates(env, monkeypatch):
    import subprocess

    from app.media import ffmpeg as ff
    from app.pipeline import export_speed
    from app.pipeline.sizes import render_size

    assert [render_size("16:9", "final", p) for p in ("720p", "1080p", "4k")] == [(1280, 720), (1920, 1080), (3840, 2160)]
    assert render_size("9:16", "final", "720p") == (720, 1280) and render_size("4:5", "final", "4k") == (2160, 2700) and render_size("1:1", "final", "720p") == (720, 720)
    settings, _, tone, _ = env
    with client(env) as c:
        assert "hardware_encoder" in c.get("/api/health").json()
        pid = finished_project(c, tone)
        d = Path(settings.projects_dir) / pid
        e = c.get(f"/api/projects/{pid}/export/estimate", params={"preset": "4k", "encoder": "software"}).json()
        e720 = c.get(f"/api/projects/{pid}/export/estimate", params={"preset": "720p", "encoder": "software"}).json()
        eh = c.get(f"/api/projects/{pid}/export/estimate", params={"preset": "4k", "encoder": "hardware"}).json()
        assert (e["width"], e["height"]) == (3840, 2160) and e["seconds"] >= e720["seconds"] >= 1 and eh["seconds"] <= e["seconds"] and not e["learned"]
        assert c.get(f"/api/projects/{pid}/export/estimate", params={"preset": "8k"}).status_code == 422
        assert c.post(f"/api/projects/{pid}/export", json={"preset": "8k"}).status_code == 422
        monkeypatch.setattr(ff, "hardware_encoder", lambda: None)                         # no hardware encoder here
        assert c.post(f"/api/projects/{pid}/export", json={"encoder": "hardware"}).status_code == 422
        monkeypatch.undo()
        r = c.post(f"/api/projects/{pid}/export", json={"preset": "720p"})
        assert r.status_code == 202
        done = wait_done(c, pid)
        assert done["export_ready"] and done["export_preset"] == "720p" and done["export_encoder"] == "software"
        size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(d / "output.mp4")],
                              capture_output=True, text=True).stdout.strip()
        assert size == "1280,720"
        assert c.get(f"/api/projects/{pid}/export").status_code == 200                  # download works
        # an edit makes the export stale and clears what it was made with
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        tl["clips"][0]["volume"] = 0.9
        assert put_tl(c, pid, tl).status_code == 200
        assert c.post(f"/api/projects/{pid}/timeline/render").status_code == 202
        after = wait_done(c, pid)
        assert not after["export_ready"] and after["export_preset"] is None
    # estimates learn: the recorded speed replaces the default (clips shorter than 3 s say nothing)
    export_speed.record(settings.work_dir, "software", "1080p", "16:9", 10.0, 24.0)
    assert export_speed.estimate(settings.work_dir, "software", "1080p", "16:9", 10.0)["learned"] is True
    export_speed.record(settings.work_dir, "hardware", "1080p", "16:9", 1.0, 5.0)
    assert export_speed.estimate(settings.work_dir, "hardware", "1080p", "16:9", 10.0)["learned"] is False


def test_storage_report_and_clean_up_over_the_api(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        r = c.get("/api/storage").json()
        assert {i["key"] for i in r["items"]} == {"projects", "segments", "stock", "proxies", "search"} and r["total"] > 0
        out = c.post("/api/storage/clean", params={"days": 7}).json()
        assert out["freed"] >= 0 and out["dry_run"] is False
        assert c.get(f"/api/projects/{pid}").json()["video_ready"] is True                          # the project is untouched


def test_a_typed_script_is_spoken_and_becomes_a_normal_project(env, monkeypatch):
    import shutil

    from app.providers import tts as tts_mod
    from app.providers.tts import TTSUnavailable

    settings, _, tone, _ = env

    class FakeVoice:
        def languages(self):
            return ["en"]

        def synthesize(self, text, language, out, voice=None):
            if language != "en":
                raise TTSUnavailable("No voice for Urdu is installed.")
            assert "hello" in text.lower()
            shutil.copyfile(tone, out)
            return out

    monkeypatch.setattr(tts_mod, "create_tts", lambda s: FakeVoice())
    with client(env) as c:
        assert c.get("/api/health").json()["speech"] == ["en"]
        assert c.post("/api/projects", data={"language": "en"}).status_code == 422                     # neither audio nor script
        assert c.post("/api/projects", data={"script": "Hello there.", "language": ""}).status_code == 422   # a voice needs a language
        no_voice = c.post("/api/projects", data={"script": "سلام", "language": "ur"})
        assert no_voice.status_code == 422 and "Urdu" in no_voice.json()["detail"]
        r = c.post("/api/projects", data={"script": "Hello there. This is the narration.", "language": "en"})
        assert r.status_code == 202, r.text
        info = r.json()
        assert info["original_filename"] == "" and info["name"].startswith("Hello there")
        done = wait_done(c, info["id"])
        assert done["status"] == "done" and done["video_ready"] and done["error"] is None
        d = Path(settings.projects_dir) / info["id"]
        assert (d / "narration.wav").is_file() and (d / "script.txt").read_text("utf-8").startswith("Hello there")
        assert c.get(f"/api/projects/{info['id']}/timeline").status_code == 200                      # editable like any other project
        # a voice that breaks while speaking: the project fails with the reason, it does not hang or look finished
        class Broken(FakeVoice):
            def synthesize(self, *a, **k):
                raise TTSUnavailable("The voice file is damaged.")
        monkeypatch.setattr(tts_mod, "create_tts", lambda s: Broken())
        with client(env) as c2:
            r2 = c2.post("/api/projects", data={"script": "Hello again.", "language": "en"})
            assert r2.status_code == 202
            failed = wait_done(c2, r2.json()["id"])
            assert failed["status"] == "failed" and "damaged" in failed["error"]


def test_an_avatar_speaks_the_narration_and_lands_on_the_timeline_keyed_in_a_corner(env):
    import subprocess

    from app.pipeline.sizes import ASPECTS

    settings, _, tone, _ = env
    with client(env) as c:
        listed = c.get("/api/avatars").json()
        assert {a["id"] for a in listed} >= {"sara", "ali"}
        t = c.get("/api/avatars/sara/thumb")
        assert t.status_code == 200 and t.headers["content-type"] == "image/png" and t.content[:4] == b"\x89PNG"
        assert c.get("/api/avatars/nobody/thumb").status_code == 404
        pid = finished_project(c, tone)
        assert c.post(f"/api/projects/{pid}/avatar", json={"avatar": "nobody"}).status_code == 422
        assert c.post(f"/api/projects/{pid}/avatar", json={"avatar": "sara", "size": 5}).status_code == 422
        r = c.post(f"/api/projects/{pid}/avatar", json={"avatar": "sara", "corner": "bottom-left", "size": 0.35})
        assert r.status_code == 202
        done = wait_done(c, pid)
        assert done["status"] == "done" and done["error"] is None and done["video_ready"]
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        clip = next(x for x in tl["clips"] if x["id"] == "avatar-1")
        narration = next(x for x in tl["clips"] if x["kind"] == "audio")
        track = next(x for x in tl["tracks"] if x["id"] == clip["track"])
        assert track["name"] == "Avatar" and clip["key"]["color"] == "#00ff00" and clip["fit"] == "fit"
        assert clip["start"] == narration["start"] and abs(clip["duration"] - narration["duration"]) <= 2        # as long as the narration
        assert clip["transform"]["x"] < 0 and clip["transform"]["y"] > 0 and clip["transform"]["scale"] == 0.35  # bottom-left
        assert tl["assets"][clip["asset"]]["source"] == "avatar" and "path" not in tl["assets"][clip["asset"]]
        assert "avatar" not in c.get(f"/api/projects/{pid}/credits").text.lower()                                # generated: nothing to credit
        # the preview shows the avatar in the corner and the video underneath everywhere else (the green is keyed out)
        d = Path(settings.projects_dir) / pid
        def rgb(x, y):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(d / "preview.mp4"), "-frames:v", "1", "-vf", f"crop=6:6:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, check=True).stdout
            return tuple(sum(raw[i::3]) // (len(raw) // 3) for i in range(3))
        w, h = (960, 540) if tl["aspect"] == "16:9" else (540, 960)
        far = rgb(w - 40, 40)                                                                                    # top-right: no avatar
        near = rgb(int(w * 0.03) + 8, int(h * 0.97) - 8)                                                         # the avatar's own square corner: transparent, so the video shows
        assert not (near[1] > 200 and near[0] < 60 and near[2] < 60)                                              # not the key green
        assert not (far[1] > 200 and far[0] < 60 and far[2] < 60)
        # a second avatar goes on its own track
        assert c.post(f"/api/projects/{pid}/avatar", json={"avatar": "ali"}).status_code == 202
        assert wait_done(c, pid)["status"] == "done"
        tl2 = c.get(f"/api/projects/{pid}/timeline").json()
        assert [x["id"] for x in tl2["clips"] if x["id"].startswith("avatar-")] == ["avatar-1", "avatar-2"]
        assert len({x["track"] for x in tl2["clips"] if x["id"].startswith("avatar-")}) == 2


def test_a_focus_suggestion_is_offered_for_pictures_and_changes_nothing(env):
    settings, _, tone, _ = env
    with client(env) as c:
        pid = finished_project(c, tone)
        tl = c.get(f"/api/projects/{pid}/timeline").json()
        pic = next(a for a in tl["assets"].values() if a["kind"] in ("image", "video"))
        r = c.get(f"/api/projects/{pid}/media/focus", params={"asset": pic["id"]})
        assert r.status_code == 200 and 0 <= r.json()["x"] <= 1 and 0 <= r.json()["y"] <= 1
        assert c.get(f"/api/projects/{pid}/media/focus", params={"asset": "narration"}).status_code == 400
        assert c.get(f"/api/projects/{pid}/media/focus", params={"asset": "nope"}).status_code == 404
        assert c.get(f"/api/projects/{pid}/timeline").json()["rev"] == tl["rev"]                         # it only suggests
        # a clip's focus survives a save and shows in the next read
        clip = next(x for x in tl["clips"] if x["asset"] == pic["id"])
        clip["focus"] = [0.2, 0.6]
        assert put_tl(c, pid, tl).status_code == 200
        assert next(x for x in c.get(f"/api/projects/{pid}/timeline").json()["clips"] if x["id"] == clip["id"])["focus"] == [0.2, 0.6]
        clip["focus"] = [2, 0.5]
        assert put_tl(c, pid, tl | {"rev": c.get(f"/api/projects/{pid}/timeline").json()["rev"]}).status_code == 422


def test_the_built_web_app_is_served_by_the_same_process_without_leaking_files(env, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP</html>")
    (dist / "assets" / "app-abc.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    with client(env, frontend_dist=str(dist)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "APP" in r.text and r.headers["cache-control"] == "no-cache"
        assert "APP" in c.get("/projects/0123456789abcdef0123456789abcdef").text                      # deep links open the app
        js = c.get("/assets/app-abc.js")
        assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
        assert "secret" not in c.get("/../secret.txt").text and "secret" not in c.get("/%2e%2e/secret.txt").text and "secret" not in c.get("/assets/../../secret.txt").text
        assert c.get("/api/health").json()["ok"] is True                                              # the API is untouched
        assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").headers["content-type"].startswith("application/json")
    with client(env, frontend_dist=str(tmp_path / "missing")) as c:
        assert c.get("/").status_code == 404                                                          # no built app: just the API, as before
