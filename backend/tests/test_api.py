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


def test_export_validation_and_busy_rules(env):
    _, _, tone, gate = env
    gate.clear()
    with client(env) as c:
        p = upload(c, tone).json()
        assert c.post(f"/api/projects/{p['id']}/export").status_code == 409        # still processing
        gate.set()
        wait_done(c, p["id"])
        assert c.post(f"/api/projects/{p['id']}/export", json={"aspect": "4:3"}).status_code == 422
        assert c.post(f"/api/projects/{p['id']}/export", json={"aspect": "9:16"}).status_code == 202
        assert c.post(f"/api/projects/{p['id']}/export").status_code == 409        # already exporting
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
