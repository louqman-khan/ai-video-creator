"""The hosted mode: accounts, sessions, ownership of every route, CSRF, limits, reset, deletion, export."""

import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.accounts import passwords
from app.api.main import create_app
from test_api import env, wait_done  # noqa: F401  (the `env` fixture: fake providers, a tone, a gate to hold a job)

H = {"X-Requested-With": "avc"}
GOOD = "correct horse battery"


def hosted(env, **over):
    settings, factory, tone, gate = env
    s = settings.model_copy(update={"mode": "hosted", "public_url": "http://testserver", **over})
    return create_app(s, factory), s, tone, gate


class Browser:
    """One person's browser: keeps its own cookies and always sends the header our pages send."""

    def __init__(self, app, settings):
        self.c = TestClient(app, headers=H)
        self.settings = settings

    def __enter__(self):
        self.c.__enter__()
        return self

    def __exit__(self, *a):
        self.c.__exit__(*a)

    def mails(self, to=None):
        out = []
        for f in sorted((Path(self.settings.work_dir) / "outbox").glob("*.txt")):
            t = f.read_text("utf-8")
            if to is None or f"To: {to}" in t:
                out.append(t)
        return out

    def link_token(self, to, kind):
        for t in reversed(self.mails(to)):
            m = re.search(rf"/{kind}\?token=([\w-]+)", t)
            if m:
                return m.group(1)
        raise AssertionError(f"no {kind} mail for {to}")

    def signup(self, email, password=GOOD, **extra):
        return self.c.post("/api/auth/signup", json={"email": email, "password": password, "terms": True, **extra})

    def register(self, email, password=GOOD):
        assert self.signup(email, password).status_code == 202
        assert self.c.post("/api/auth/verify", json={"token": self.link_token(email, "verify")}).status_code == 200
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["user"]

    def make_project(self, tone, **data):
        with open(tone, "rb") as f:
            return self.c.post("/api/projects", files={"file": (tone.name, f, "audio/wav")}, data={"clean": "false", "normalize": "false", **data})


def test_passwords_are_hashed_checked_and_policed():
    h = passwords.hash_password(GOOD)
    assert h.startswith("scrypt$") and GOOD not in h and passwords.verify_password(GOOD, h) and not passwords.verify_password("wrong", h)
    assert h != passwords.hash_password(GOOD)                              # a fresh salt every time
    assert not passwords.verify_password("x", "garbage") and not passwords.verify_password("x", "scrypt$1$2")
    assert passwords.policy_problem("short") and passwords.policy_problem("password123") and passwords.policy_problem("aaaaaaaaaaaa")
    assert passwords.policy_problem("me@example.com", "me@example.com") and passwords.policy_problem("a" * 500)
    assert passwords.policy_problem(GOOD, "me@example.com") is None


def test_nothing_works_without_logging_in_and_the_door_checks_the_header_and_origin(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b, TestClient(app) as bare:
        assert b.c.get("/api/health").json()["mode"] == "hosted"
        assert b.c.get("/api/projects").status_code == 401 and b.c.get("/api/storage").status_code == 401
        assert b.c.get("/api/projects/" + "0" * 32 + "/video").status_code == 401
        assert b.c.get("/api/auth/me").json()["user"] is None
        # a request without our header, or from another site, is refused before anything else
        assert bare.post("/api/auth/login", json={"email": "a@b.co", "password": GOOD}).status_code == 403
        assert b.c.post("/api/auth/login", json={"email": "a@b.co", "password": GOOD}, headers={**H, "Origin": "https://evil.example"}).status_code == 403
        assert b.c.post("/api/auth/login", json={"email": "a@b.co", "password": GOOD}).status_code == 401      # the header is there: now it is just a wrong login
        assert b.c.get("/api/health").headers["x-frame-options"] == "DENY" and "default-src 'self'" in b.c.get("/api/health").headers["content-security-policy"]


def test_sign_up_verification_login_logout(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        assert b.c.post("/api/auth/signup", json={"email": "t@example.com", "password": GOOD}).status_code == 422      # the terms were not accepted
        assert b.signup("not an address").status_code == 422
        assert b.signup("x@example.com", "short").status_code == 422
        assert b.signup("Ann@Example.com").status_code == 202
        assert b.signup("ann@example.com").status_code == 202                                  # same answer for a known address
        assert len(b.mails("ann@example.com")) == 2 and "already has an account" in b.mails("ann@example.com")[1]
        r = b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD})
        assert r.status_code == 403 and "Confirm your e-mail" in r.json()["detail"]
        assert b.c.post("/api/auth/verify", json={"token": "nonsense"}).status_code == 400
        tok = b.link_token("ann@example.com", "verify")
        assert b.c.post("/api/auth/verify", json={"token": tok}).status_code == 200
        assert b.c.post("/api/auth/verify", json={"token": tok}).status_code == 400            # a link works once
        bad = b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": "wrong password"})
        none = b.c.post("/api/auth/login", json={"email": "nobody@example.com", "password": GOOD})
        assert bad.status_code == none.status_code == 401 and bad.json() == none.json()        # the two failures look the same
        ok = b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD})
        assert ok.status_code == 200
        cookie = ok.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "avc_session=" in cookie
        me = b.c.get("/api/auth/me").json()
        assert me["user"]["email"] == "ann@example.com" and me["usage"]["projects"] == 0 and me["usage"]["max_projects"] == s.max_projects_per_user
        assert b.c.get("/api/projects").status_code == 200
        assert b.c.post("/api/auth/logout").status_code == 200
        assert b.c.get("/api/projects").status_code == 401                                      # the session is really gone, not just the cookie


def test_signups_can_be_invite_only_or_closed(env):
    app, s, _, _ = hosted(env, signups="invite", invite_codes="alpha, beta")
    with Browser(app, s) as b:
        assert b.signup("a@example.com").status_code == 403
        assert b.signup("a@example.com", invite="nope").status_code == 403
        assert b.signup("a@example.com", invite="beta").status_code == 202
    app2, s2, _, _ = hosted(env, signups="closed")
    with Browser(app2, s2) as b:
        assert b.signup("b@example.com").status_code == 403


PROJECT_ROUTES = [  # every kind of route under a project; user B must get 404 from all of them, a stranger 401
    ("GET", ""), ("GET", "/video"), ("GET", "/scenes"), ("GET", "/captions"), ("GET", "/timeline"), ("GET", "/media"), ("GET", "/attributions"),
    ("GET", "/credits"), ("GET", "/export"), ("GET", "/export/estimate"), ("GET", "/media/focus?asset=narration"), ("GET", "/media/proxy?asset=narration"),
    ("GET", "/scenes/1/thumb"), ("GET", "/scenes/1/candidates?query=x"), ("PUT", "/timeline"), ("PUT", "/captions"), ("POST", "/export"),
    ("POST", "/timeline/render"), ("POST", "/avatar"), ("POST", "/scenes/1/swap"), ("POST", "/media"), ("POST", "/media/prepare"), ("POST", "/bin/add"),
    ("GET", "/bin/search?q=x&kind=video"), ("DELETE", "/media?asset=x"), ("DELETE", ""),
]


def test_nobody_can_touch_somebody_elses_project_on_any_route(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as ann, Browser(app, s) as bob, TestClient(app, headers=H) as stranger:
        ann.register("ann@example.com")
        bob.register("bob@example.com")
        r = ann.make_project(tone)
        assert r.status_code == 202 and r.json()["owner"]
        pid = r.json()["id"]
        wait_done(ann.c, pid)
        assert [p["id"] for p in ann.c.get("/api/projects").json()] == [pid] and bob.c.get("/api/projects").json() == []
        for method, tail in PROJECT_ROUTES:
            url = f"/api/projects/{pid}{tail}"
            kw = {"json": {}} if method in ("PUT", "POST") and tail not in ("/media",) else {}
            assert bob.c.request(method, url, **kw).status_code == 404, ("bob", method, tail)
            assert stranger.request(method, url, **kw).status_code == 401, ("stranger", method, tail)
        # and the owner still has everything (the video file is really served)
        assert ann.c.get(f"/api/projects/{pid}/video").status_code == 200 and ann.c.get(f"/api/projects/{pid}/timeline").status_code == 200
        assert bob.c.delete(f"/api/projects/{pid}").status_code == 404 and ann.c.get(f"/api/projects/{pid}").status_code == 200
        # a made-up or odd id leaks nothing either
        for bad in ("0" * 32, "..", "%2e%2e", "x" * 80):
            assert bob.c.get(f"/api/projects/{bad}").status_code == 404
        assert ann.c.delete(f"/api/projects/{pid}").status_code == 204


def test_limits_one_job_at_a_time_projects_storage_and_exports(env):
    app, s, tone, gate = hosted(env, max_projects_per_user=2, max_exports_per_day=1)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        gate.clear()                                                                           # hold the first job: it is "running"
        first = b.make_project(tone)
        assert first.status_code == 202
        second = b.make_project(tone)
        assert second.status_code == 429 and "already have a video" in second.json()["detail"]
        gate.set()
        wait_done(b.c, first.json()["id"])
        second = b.make_project(tone)
        assert second.status_code == 202
        wait_done(b.c, second.json()["id"])
        assert b.make_project(tone).status_code == 429 and "at most 2 projects" in b.make_project(tone).json()["detail"]
        pid = first.json()["id"]
        assert b.c.post(f"/api/projects/{pid}/export", json={"preset": "720p"}).status_code == 202
        wait_done(b.c, pid)
        r = b.c.post(f"/api/projects/{pid}/export", json={"preset": "720p"})
        assert r.status_code == 429 and "exports a day" in r.json()["detail"]
    app2, s2, tone2, _ = hosted(env, max_storage_mb_per_user=0)
    with Browser(app2, s2) as b:
        b.register("zed@example.com")
        r = b.make_project(tone2)
        assert r.status_code == 413 and "storage is full" in r.json()["detail"]


def test_password_reset_ends_every_session_and_links_work_once(env):
    app, s, _, _ = hosted(env)
    with Browser(app, s) as b, Browser(app, s) as other:
        b.register("ann@example.com")
        assert other.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 200
        assert b.c.post("/api/auth/forgot", json={"email": "nobody@example.com"}).status_code == 202      # no hint whether the address exists
        assert b.mails("nobody@example.com") == []
        assert b.c.post("/api/auth/forgot", json={"email": "ann@example.com"}).status_code == 202
        tok = b.link_token("ann@example.com", "reset")
        assert b.c.post("/api/auth/reset", json={"token": tok, "password": "short"}).status_code == 422
        assert b.c.post("/api/auth/reset", json={"token": tok, "password": "a brand new passphrase"}).status_code == 200
        assert b.c.post("/api/auth/reset", json={"token": tok, "password": "another new passphrase"}).status_code == 400
        assert b.c.get("/api/projects").status_code == 401 and other.c.get("/api/projects").status_code == 401   # both old sessions are gone
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 401
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": "a brand new passphrase"}).status_code == 200


def test_logging_in_is_rate_limited_per_account(env):
    app, s, _, _ = hosted(env)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        codes = [b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": "wrong password!"}).status_code for _ in range(10)]
        assert codes[:7] == [401] * 7 and codes[7] == 429                                      # eight tries per ten minutes, the sign-up's own log-in counted
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 429   # even the right password waits


def test_the_account_can_be_exported_and_deleted_with_everything_in_it(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b, Browser(app, s) as other:
        b.register("ann@example.com")
        other.register("bob@example.com")
        pid = b.make_project(tone).json()["id"]
        wait_done(b.c, pid)
        z = b.c.get("/api/auth/export")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        out = Path(s.work_dir) / "got.zip"
        out.write_bytes(z.content)
        names = zipfile.ZipFile(out).namelist()
        assert "account.txt" in names and f"{pid}/project.json" in names and f"{pid}/preview.mp4" in names
        assert "bob" not in zipfile.ZipFile(out).read("account.txt").decode()
        assert b.c.request("DELETE", "/api/auth/account", json={"password": "wrong password!"}).status_code == 401
        assert b.c.request("DELETE", "/api/auth/account", json={"password": GOOD}).status_code == 200
        assert not (Path(s.projects_dir) / pid).exists()                                          # the files are gone, not just hidden
        assert b.c.get("/api/projects").status_code == 401
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 401
        assert other.c.get("/api/projects").status_code == 200                                    # nobody else is affected


def test_only_administrators_may_clean_the_server_disk(env):
    app, s, _, _ = hosted(env, admin_emails="boss@example.com")
    with Browser(app, s) as user, Browser(app, s) as boss:
        user.register("ann@example.com")
        boss.register("boss@example.com")
        assert user.c.get("/api/storage").status_code == 403 and user.c.post("/api/storage/clean").status_code == 403
        assert boss.c.get("/api/storage").status_code == 200 and boss.c.post("/api/storage/clean").status_code == 200
        assert boss.c.get("/api/auth/me").json()["user"]["admin"] is True and user.c.get("/api/auth/me").json()["user"]["admin"] is False


def test_local_mode_has_no_login_and_reports_it(env):
    settings, factory, tone, _ = env
    with TestClient(create_app(settings, factory)) as c:
        me = c.get("/api/auth/me").json()
        assert me["mode"] == "local" and me["user"]["id"] == "local"
        assert c.get("/api/projects").status_code == 200 and c.post("/api/auth/login", json={"email": "a@b.co", "password": GOOD}).status_code == 404


def test_the_hosted_site_never_fetches_from_its_own_network():
    from app.http import HttpError, assert_public_url

    for bad in ("http://127.0.0.1/x", "http://10.0.0.5/a", "http://192.168.1.10/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://localhost:8742/api/health",
                "file:///etc/passwd", "ftp://example.com/x", "http://0.0.0.0/"):
        with pytest.raises(HttpError):
            assert_public_url(bad)
    assert_public_url("https://93.184.216.34/ok.mp4")                         # a public address passes


def test_the_free_voices_stay_off_the_public_site_unless_the_operator_allows_them():
    from app.config import Settings
    from app.providers.tts import create_tts, voices_allowed

    assert voices_allowed(Settings(_env_file=None)) is True                     # local: personal use
    hostedset = Settings(_env_file=None, mode="hosted")
    assert voices_allowed(hostedset) is False and create_tts(hostedset).languages() == []
    assert voices_allowed(Settings(_env_file=None, mode="hosted", allow_noncommercial_voices=True)) is True
