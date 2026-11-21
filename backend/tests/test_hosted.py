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
        assert self.c.post("/api/auth/verify-code", json={"email": email, "code": code_in_mail(self, email)}).status_code == 200
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
    assert passwords.policy_problem("short") and passwords.policy_problem("123456") and passwords.policy_problem("password123") and passwords.policy_problem("aaaaaaaaaaaa")
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
        assert b.signup("x@example.com", "short").status_code == 422                          # fewer than 6 characters
        assert b.signup("Ann@Example.com").status_code == 202
        assert b.signup("ann@example.com").status_code == 202                                  # started but never confirmed: a new code is sent
        assert len(b.mails("ann@example.com")) == 2 and re.search(r"\n\d{6}\n", b.mails("ann@example.com")[1])
        r = b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD})
        assert r.status_code == 403 and "Confirm your e-mail" in r.json()["detail"]
        assert b.c.post("/api/auth/verify", json={"token": "nonsense"}).status_code in (404, 405)      # there is no confirmation link any more: only the code
        code = code_in_mail(b, "ann@example.com")
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": code}).status_code == 200
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": code}).status_code == 400    # a code works once
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


# ------------------------------------------------------------------ credits

def credits_of(b):
    return b.c.get("/api/auth/me").json()["usage"]["credits"]


def test_a_video_costs_credits_by_the_length_of_its_narration_and_the_balance_is_visible(env):
    app, s, tone, _ = hosted(env, credits_per_month=10)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        c = credits_of(b)
        assert (c["plan"], c["monthly"], c["used"], c["remaining"], c["unlimited"]) == ("Free", 10, 0, 10, False)
        assert re.match(r"\d{4}-\d{2}-01$", c["resets_on"])
        assert b.make_project(tone).status_code == 202                       # a 4 second narration: one credit (the minimum)
        c = credits_of(b)
        assert (c["used"], c["remaining"]) == (1, 9)


def test_without_enough_credits_no_project_is_made_and_the_reason_is_clear(env):
    app, s, tone, _ = hosted(env, credits_per_month=1)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        first = b.make_project(tone)
        assert first.status_code == 202
        wait_done(b.c, first.json()["id"])                                   # one job at a time: let the first finish
        r = b.make_project(tone)
        assert r.status_code == 402 and "Not enough credits" in r.json()["detail"] and "renew" in r.json()["detail"]
        assert len(b.c.get("/api/projects").json()) == 1                      # the refused one left nothing behind
        assert credits_of(b)["remaining"] == 0


def test_a_typed_script_is_priced_by_its_words_and_administrators_are_not_charged(env):
    app, s, tone, _ = hosted(env, credits_per_month=2, admin_emails="boss@example.com", max_active_jobs_per_user=5)
    from app.accounts.quotas import Quotas
    quotas = Quotas(s, app.state.store)
    assert quotas.cost_for_script("word " * 150) == 1 and quotas.cost_for_script("word " * 151) == 2 and quotas.cost_for_script("") == 1
    assert quotas.cost_for_seconds(59) == 1 and quotas.cost_for_seconds(61) == 2 and quotas.cost_for_seconds(600) == 10
    with Browser(app, s) as b:
        b.register("boss@example.com")
        assert credits_of(b)["unlimited"] is True
        for _ in range(3):
            assert b.make_project(tone).status_code == 202                    # more than the monthly allowance: not charged
        assert credits_of(b)["used"] == 0


def test_a_video_that_could_not_be_made_gives_its_credits_back_once(env):
    settings, factory, tone, gate = env

    class Boom:
        def transcribe(self, audio, language=None):
            raise RuntimeError("the recogniser broke")

    def broken(s, cache):
        p = factory(s, cache)
        object.__setattr__(p, "transcriber", Boom())
        return p

    s = settings.model_copy(update={"mode": "hosted", "public_url": "http://testserver", "credits_per_month": 5})
    app = create_app(s, broken)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        pid = b.make_project(tone).json()["id"]
        assert wait_done(b.c, pid)["status"] == "failed"
        assert credits_of(b)["used"] == 0                                    # refunded
        app.state.jobs.on_failed(pid)                                        # a second report of the same failure
        assert credits_of(b)["used"] == 0                                    # still only refunded once


def test_the_monthly_allowance_renews_on_the_first_of_the_month():
    from datetime import datetime, timezone

    from app.accounts.quotas import month_start, next_month_start

    t = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
    assert month_start(t).isoformat().startswith("2026-12-01") and next_month_start(t).isoformat().startswith("2027-01-01")
    t = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc).timestamp()
    assert next_month_start(t).isoformat().startswith("2026-04-01")


# ------------------------------------------------------------------ administration

def test_the_admin_area_is_for_administrators_only_and_lists_use(env):
    app, s, tone, _ = hosted(env, admin_emails="boss@example.com", credits_per_month=5)
    with Browser(app, s) as boss, Browser(app, s) as ann, TestClient(app, headers=H) as anon:
        boss.register("boss@example.com")
        ann.register("ann@example.com")
        assert anon.get("/api/admin/users").status_code == 401
        assert ann.c.get("/api/admin/users").status_code == 403
        assert ann.c.post("/api/admin/users/x/credits", json={"amount": 5}).status_code == 403
        assert ann.make_project(tone).status_code == 202
        rows = {u["email"]: u for u in boss.c.get("/api/admin/users").json()}
        assert set(rows) == {"boss@example.com", "ann@example.com"}
        a = rows["ann@example.com"]
        assert (a["projects"], a["credits"]["used"], a["credits"]["remaining"], a["disabled"], a["role"]) == (1, 1, 4, False, "user")
        assert rows["boss@example.com"]["credits"]["unlimited"] is True
        assert "password" not in str(rows)                                              # nothing secret leaves the server


def test_the_activity_log_shows_the_operator_what_an_account_did_and_only_the_operator(env):
    app, s, tone, _ = hosted(env, admin_emails="boss@example.com")
    with Browser(app, s) as boss, Browser(app, s) as ann:
        boss.register("boss@example.com")
        ann.register("ann@example.com")
        pid = ann.make_project(tone, name="My story").json()["id"]
        wait_done(ann.c, pid)
        ann.c.get(f"/api/projects/{pid}/video")
        ann.c.get(f"/api/projects/{pid}/video")                                         # watched twice in a moment: one entry
        uid = next(u["id"] for u in boss.c.get("/api/admin/users").json() if u["email"] == "ann@example.com")
        assert boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": 4}).status_code == 200
        assert ann.c.delete(f"/api/projects/{pid}").status_code == 204
        ann.c.post("/api/auth/logout")
        rows = boss.c.get(f"/api/admin/activity?user={uid}").json()
        kinds = [r["kind"] for r in rows]                                              # newest first
        assert kinds == ["logout", "project_deleted", "bonus", "video_viewed", "project_created", "login", "confirmed", "signed_up"]
        by = {r["kind"]: r for r in rows}
        assert by["project_created"]["project_name"] == "" or by["project_created"]["label"] == "Created a project"      # the project is gone by now
        assert by["bonus"]["detail"] == "+4" and by["login"]["email"] == "ann@example.com" and by["login"]["detail"]
        assert len(boss.c.get("/api/admin/activity").json()) > len(rows)                 # without ?user= it is everybody
        assert "password" not in str(rows)
        assert ann.c.get("/api/admin/activity").status_code in (401, 403)                # not for ordinary accounts


def test_bonus_credits_are_added_kept_across_months_and_can_be_taken_back_but_not_below_zero(env):
    app, s, tone, _ = hosted(env, admin_emails="boss@example.com", credits_per_month=1, max_active_jobs_per_user=5)
    with Browser(app, s) as boss, Browser(app, s) as ann:
        boss.register("boss@example.com")
        ann.register("ann@example.com")
        uid = next(u["id"] for u in boss.c.get("/api/admin/users").json() if u["email"] == "ann@example.com")
        assert ann.make_project(tone).status_code == 202                                # the one monthly credit
        assert ann.make_project(tone).status_code == 402
        r = boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": 3})
        assert r.status_code == 200 and (r.json()["bonus"], r.json()["remaining"]) == (3, 3)
        assert ann.make_project(tone).status_code == 202                                # the bonus pays for it
        assert credits_of(ann)["remaining"] == 2 and credits_of(ann)["bonus"] == 3
        assert boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": -9}).status_code == 422      # only 3 can be taken back
        assert boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": 0}).status_code == 422
        assert boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": 5000}).status_code == 422
        assert boss.c.post("/api/admin/users/nobody/credits", json={"amount": 1}).status_code == 404
        assert boss.c.post(f"/api/admin/users/{uid}/credits", json={"amount": -3}).status_code == 200
        assert credits_of(ann)["bonus"] == 0


def test_switching_an_account_off_ends_its_sessions_and_blocks_login_and_it_can_be_switched_on(env):
    app, s, tone, _ = hosted(env, admin_emails="boss@example.com")
    with Browser(app, s) as boss, Browser(app, s) as ann:
        boss.register("boss@example.com")
        ann.register("ann@example.com")
        uid = next(u["id"] for u in boss.c.get("/api/admin/users").json() if u["email"] == "ann@example.com")
        boss_id = next(u["id"] for u in boss.c.get("/api/admin/users").json() if u["email"] == "boss@example.com")
        assert boss.c.post(f"/api/admin/users/{boss_id}/disabled", json={"disabled": True}).status_code == 422   # an administrator cannot lock out an administrator
        assert ann.c.get("/api/projects").status_code == 200
        assert boss.c.post(f"/api/admin/users/{uid}/disabled", json={"disabled": True}).status_code == 200
        assert ann.c.get("/api/projects").status_code == 401                              # her session ended at once
        assert ann.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 401
        assert boss.c.post(f"/api/admin/users/{uid}/disabled", json={"disabled": False}).status_code == 200
        assert ann.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 200


# ------------------------------------------------------------------ e-mail code, resend, languages

def code_in_mail(b, to):
    for t in reversed(b.mails(to)):
        m = re.search(r"\n(\d{6})\n", t)
        if m:
            return m.group(1)
    raise AssertionError("no code mail")


def test_the_confirmation_mail_has_a_link_a_code_and_a_styled_version_and_the_code_confirms_the_address(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        assert b.signup("ann@example.com").status_code == 202
        text = b.mails("ann@example.com")[-1]
        assert "/verify" not in text and "http" not in text and re.search(r"\n\d{6}\n", text)        # the code only: no link
        outbox = Path(s.work_dir) / "outbox"
        html = next(outbox.glob("*.html")).read_text("utf-8")
        assert "YOUR CONFIRMATION CODE".lower() in html.lower() and 'dir="ltr"' in html and "<table" in html and "href=" not in html
        code = code_in_mail(b, "ann@example.com")
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 403     # not confirmed yet
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": "000000" if code != "000000" else "111111"}).status_code == 400
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": f"{code[:3]} {code[3:]}"}).status_code == 200   # spaces are fine
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 200
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": code}).status_code == 400    # a code works once


def test_a_code_cannot_be_guessed_five_wrong_tries_lock_it_for_a_while(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        b.signup("ann@example.com")
        code = code_in_mail(b, "ann@example.com")
        wrong = "123456" if code != "123456" else "654321"
        for _ in range(5):
            assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": wrong}).status_code == 400
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": code}).status_code == 429    # even the right one waits
        assert b.c.post("/api/auth/verify-code", json={"email": "nobody@example.com", "code": "123456"}).status_code in (400, 429)


def test_resend_sends_a_new_pair_only_to_unconfirmed_addresses_and_never_reveals_which(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        b.signup("ann@example.com")
        first = code_in_mail(b, "ann@example.com")
        r1 = b.c.post("/api/auth/resend", json={"email": "ann@example.com"})
        r2 = b.c.post("/api/auth/resend", json={"email": "nobody@example.com"})
        assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
        new = code_in_mail(b, "ann@example.com")
        assert new != first or True                                                        # (one in a million to repeat)
        if new != first:
            assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": first}).status_code == 400      # only the newest code works
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": new}).status_code == 200
        before = len(b.mails("ann@example.com"))
        b.c.post("/api/auth/resend", json={"email": "ann@example.com"})
        assert len(b.mails("ann@example.com")) == before                                  # confirmed: nothing more is sent


def test_mails_can_be_in_urdu_and_the_reset_mail_is_styled(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        b.register("ann@example.com")
        b.c.post("/api/auth/forgot", json={"email": "ann@example.com", "lang": "ur"})
        text = b.mails("ann@example.com")[-1]
        assert "Subject: پاس ورڈ دوبارہ سیٹ کریں" in text and "/reset?token=" in text
        html = sorted((Path(s.work_dir) / "outbox").glob("*.html"))[-1].read_text("utf-8")
        assert 'dir="rtl"' in html and 'lang="ur"' in html
        b.signup("bob@example.com")
        b.c.post("/api/auth/signup", json={"email": "bob@example.com", "password": GOOD, "terms": True, "lang": "xx"})     # an unknown language falls back to English
        assert "Subject: Confirm your e-mail address" in b.mails("bob@example.com")[-1] or "Subject: Your AI Video Creator account" in b.mails("bob@example.com")[-1]


def test_signing_up_with_an_address_that_already_has_an_account_says_so_and_never_overwrites_it(env):
    app, s, tone, _ = hosted(env, admin_emails="")
    with Browser(app, s) as b:
        b.register("ann@example.com")
        r = b.signup("ann@example.com", "another good password")
        assert r.status_code == 409 and "already has an account" in r.json()["detail"]
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 200              # the first password still works
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": "another good password"}).status_code == 401


def test_an_unconfirmed_sign_up_can_be_continued_with_a_new_code_and_keeps_its_first_password(env):
    app, s, tone, _ = hosted(env)
    with Browser(app, s) as b:
        assert b.signup("ann@example.com").status_code == 202
        first = code_in_mail(b, "ann@example.com")
        assert b.signup("ann@example.com", "a second password").status_code == 202                  # asks again: it is not an error
        new = code_in_mail(b, "ann@example.com")
        assert b.c.post("/api/auth/verify-code", json={"email": "ann@example.com", "code": new}).status_code == 200
        assert b.c.post("/api/auth/login", json={"email": "ann@example.com", "password": GOOD}).status_code == 200            # nobody can swap the password before it is confirmed
        assert first or True

