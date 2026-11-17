import json
import os
import time
from pathlib import Path

from app import maintenance
from app.config import Settings
from app.media.derive import asset_key


def make(tmp_path):
    s = Settings(_env_file=None, work_dir=str(tmp_path / "work"), projects_dir=str(tmp_path / "work" / "projects"))
    for d in ("cache/media", "cache/proxies", "cache/search", "projects"):
        (tmp_path / "work" / d).mkdir(parents=True, exist_ok=True)
    return s


def age(path: Path, days: float):
    t = time.time() - days * 86400
    for p in [path, *(path.rglob("*") if path.is_dir() else [])]:
        os.utime(p, (t, t))


def test_clean_removes_only_what_nothing_uses_and_what_is_old_enough(tmp_path):
    s = make(tmp_path)
    work = tmp_path / "work"
    # a project that uses one stock file and one upload (with their proxies), plus old render caches
    proj = work / "projects" / ("a" * 32)
    (proj / "uploads").mkdir(parents=True)
    used_stock = work / "cache" / "media" / "used.mp4"; used_stock.write_bytes(b"x" * 1000)
    old_stock = work / "cache" / "media" / "old.mp4"; old_stock.write_bytes(b"x" * 2000)
    new_stock = work / "cache" / "media" / "new.mp4"; new_stock.write_bytes(b"x" * 3000)
    upload = proj / "uploads" / "u.mp4"; upload.write_bytes(b"x" * 500)
    (proj / "timeline.json").write_text(json.dumps({"assets": {"s": {"path": str(used_stock)}, "u": {"path": str(upload)}}}))
    (proj / "tl_segments").mkdir(); (proj / "tl_segments" / "seg.mp4").write_bytes(b"x" * 4000)
    (proj / "exp.mp4").write_bytes(b"x" * 100)
    for f in (used_stock, old_stock):
        age(f, 30)
    age(proj / "tl_segments", 30)
    live_proxy = work / "cache" / "proxies" / asset_key(used_stock); live_proxy.mkdir(); (live_proxy / "p.mp4").write_bytes(b"x" * 700)
    orphan = work / "cache" / "proxies" / "deadbeefdeadbeef"; orphan.mkdir(); (orphan / "p.mp4").write_bytes(b"x" * 900); age(orphan, 2)
    fresh_orphan = work / "cache" / "proxies" / "0123456789abcdef"; fresh_orphan.mkdir(); (fresh_orphan / "p.mp4").write_bytes(b"x" * 50)   # just made: may be in use
    old_search = work / "cache" / "search" / "s.json"; old_search.write_text("[]"); age(old_search, 30)

    dry = maintenance.clean(s, days=7, segments=True, dry_run=True)
    assert dry["freed"] == 2000 + 4000 + 900 + 2 and old_stock.exists() and orphan.exists()          # a dry run removes nothing

    r = maintenance.clean(s, days=7, segments=False)                                                 # render caches only on request
    assert (proj / "tl_segments").exists()
    assert not old_stock.exists() and not orphan.exists() and not old_search.exists()
    assert used_stock.exists() and new_stock.exists() and live_proxy.exists() and fresh_orphan.exists() and upload.exists() and (proj / "exp.mp4").exists()
    assert r["freed"] == 2000 + 900 + 2

    r2 = maintenance.clean(s, days=7, segments=True)
    assert not (proj / "tl_segments").exists() and r2["freed"] == 4000
    assert upload.exists() and (proj / "timeline.json").exists()                                     # a project's own files are never touched


def test_survey_reports_every_category_and_leftover_partial_files(tmp_path):
    s = make(tmp_path)
    proj = tmp_path / "work" / "projects" / ("b" * 32)
    proj.mkdir(parents=True)
    part = proj / "seg.part.mp4"; part.write_bytes(b"x" * 10); age(part, 1)
    items = {i.key: i for i in maintenance.survey(s)}
    assert set(items) == {"projects", "segments", "stock", "proxies", "search"}
    assert items["segments"].reclaimable == 10                                                       # an abandoned half-written file
