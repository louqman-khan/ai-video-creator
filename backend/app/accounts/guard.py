"""The door of the hosted server: one dependency that every /api request passes (see `create_app`).

In local mode it lets everyone in as the one local user. In hosted mode it
  1. refuses state-changing requests that do not come from our own pages (CSRF: a custom header, and an Origin that matches);
  2. lets only a few routes through without a login (health, sign-up, log-in, verify, reset, avatar pictures);
  3. requires a valid session cookie for everything else;
  4. for anything under /api/projects/<id>/: answers 404 unless the project belongs to the user (never 403: do not reveal that it exists);
  5. keeps the storage clean-up for administrators;
  6. applies the per-user limits (projects, storage, one job at a time, exports per day).
Because it is a single global dependency, a new route cannot be forgotten: it is protected from the day it exists."""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

from app.accounts.db import LOCAL_USER, Accounts, User
from app.accounts.quotas import Quotas
from app.accounts.ratelimit import RateLimiter
from app.api.store import ProjectNotFound, ProjectStore
from app.config import Settings

COOKIE = "avc_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "avc"
SAFE = {"GET", "HEAD", "OPTIONS"}
PUBLIC = {"/api/health", "/api/auth/me", "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/verify", "/api/auth/verify-code", "/api/auth/resend", "/api/auth/forgot", "/api/auth/reset"}
PROJECT_PATH = re.compile(r"^/api/projects/([^/]+)(/.*)?$")
JOB_STARTERS = [  # (method, path pattern) that start a render or another long job
    ("POST", re.compile(r"^/api/projects$")),
    ("POST", re.compile(r"^/api/projects/[^/]+/(export|avatar|timeline/render)$")),
    ("POST", re.compile(r"^/api/projects/[^/]+/scenes/\d+/swap$")),
    ("PUT", re.compile(r"^/api/projects/[^/]+/captions$")),
]
GROWS_STORAGE = [
    ("POST", re.compile(r"^/api/projects$")),
    ("POST", re.compile(r"^/api/projects/[^/]+/(media|bin/add|avatar|export)$")),
]


def client_ip(request: Request, trusted_proxy: bool) -> str:
    if trusted_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


class Guard:
    def __init__(self, s: Settings, store: ProjectStore, accounts: Accounts | None, quotas: Quotas | None, limiter: RateLimiter) -> None:
        self.s, self.store, self.accounts, self.quotas, self.limiter = s, store, accounts, quotas, limiter

    def user_of(self, request: Request) -> User | None:
        if self.accounts is None:
            return LOCAL_USER
        token = request.cookies.get(COOKIE)
        return self.accounts.session_user(token) if token else None

    async def __call__(self, request: Request) -> None:
        path, method = request.url.path, request.method
        if not path.startswith("/api"):
            return
        if self.accounts is None:  # local mode
            request.state.user = LOCAL_USER
            return

        # 1. CSRF: our own pages send a header that another site cannot make a browser send without our consent
        if method not in SAFE:
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                raise HTTPException(403, "This request did not come from the app.")
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
                raise HTTPException(403, "This request came from another site.")

        # 2/3. who is it
        user = self.user_of(request)
        request.state.user = user
        public = path in PUBLIC or (method == "GET" and (path == "/api/avatars" or path.startswith("/api/avatars/")))
        if user is None:
            if public:
                return
            raise HTTPException(401, "Please log in.")
        if path in PUBLIC and path != "/api/health" and method == "POST" and path != "/api/auth/logout":
            return  # a logged-in user asking for sign-up or log-in again: the route decides

        # 4. ownership
        m = PROJECT_PATH.match(path)
        if m:
            try:
                info = self.store.get(m.group(1))
            except (ProjectNotFound, ValueError, OSError):
                raise HTTPException(404, "Project not found") from None
            if info.owner != user.id:
                raise HTTPException(404, "Project not found")

        # 5. administrators only
        if path.startswith(("/api/storage", "/api/admin")) and not user.is_admin:
            raise HTTPException(403, "Only administrators can do that.")

        # 6. limits
        assert self.quotas is not None
        pid = m.group(1) if m else None
        if any(method == mt and pat.match(path) for mt, pat in JOB_STARTERS):
            if self.quotas.active_jobs(user.id, except_project=pid) >= self.s.max_active_jobs_per_user:
                raise HTTPException(429, "You already have a video being made. Wait until it has finished.")
        if any(method == mt and pat.match(path) for mt, pat in GROWS_STORAGE):
            if self.quotas.storage_bytes(user.id) >= self.s.max_storage_mb_per_user * 1024 * 1024:
                raise HTTPException(413, "Your storage is full. Delete a project you no longer need.")
        if method == "POST" and path == "/api/projects" and len(self.quotas.projects(user.id)) >= self.s.max_projects_per_user:
            raise HTTPException(429, f"You can have at most {self.s.max_projects_per_user} projects. Delete one first.")
        if method == "POST" and path.endswith("/export") and m:
            if self.accounts.count_since(user.id, "export", 86400) >= self.s.max_exports_per_day:
                raise HTTPException(429, f"You can make {self.s.max_exports_per_day} exports a day. Try again tomorrow.")
            self.accounts.record(user.id, "export")
