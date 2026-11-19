"""Sign-up, log-in, verification, password reset, account deletion and data export."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.accounts import passwords
from app.accounts.db import LOCAL_USER, Accounts
from app.accounts.guard import COOKIE, client_ip
from app.accounts.mailer import Mailer
from app.accounts.quotas import Quotas
from app.accounts.ratelimit import RateLimiter
from app.api.store import ProjectStore
from app.config import Settings

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


class SignUp(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=passwords.MAX_LENGTH)
    invite: str = Field("", max_length=100)
    terms: bool = False  # the person ticked "I accept the terms of use and the privacy policy"


class LogIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=passwords.MAX_LENGTH)


class TokenBody(BaseModel):
    token: str = Field(..., max_length=200)


class Forgot(BaseModel):
    email: str = Field(..., max_length=254)


class Reset(BaseModel):
    token: str = Field(..., max_length=200)
    password: str = Field(..., max_length=passwords.MAX_LENGTH)


class Confirm(BaseModel):
    password: str = Field(..., max_length=passwords.MAX_LENGTH)


def build_router(s: Settings, store: ProjectStore, accounts: Accounts | None, quotas: Quotas | None, mailer: Mailer | None, limiter: RateLimiter) -> APIRouter:
    router = APIRouter(prefix="/api/auth")
    secure = s.public_url.startswith("https://")
    generic = {"message": "If that is possible, an e-mail is on its way. Check your inbox (and the spam folder)."}

    def need_accounts() -> Accounts:
        if accounts is None or mailer is None or quotas is None:
            raise HTTPException(404, "Accounts are only used by the hosted site.")
        return accounts

    def throttle(request: Request, name: str, limit: int, seconds: float, extra: str = "") -> None:
        key = f"{name}:{client_ip(request, s.trusted_proxy)}" + (f":{extra.lower()}" if extra else "")
        if not limiter.allow(key, limit, seconds):
            raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")

    def set_cookie(response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, max_age=s.session_days * 86400, httponly=True, samesite="lax", secure=secure, path="/")

    @router.get("/me")
    def me(request: Request) -> dict:
        info = {"mode": s.mode, "signups": s.signups, "require_verification": s.require_email_verification}
        user = getattr(request.state, "user", None)
        if accounts is None:
            return {**info, "user": {"id": LOCAL_USER.id, "email": None, "admin": True}}
        if user is None:
            return {**info, "user": None}
        assert quotas is not None
        return {**info, "user": {"id": user.id, "email": user.email, "admin": user.is_admin, "verified": user.verified}, "usage": quotas.summary(user.id, user.is_admin)}

    @router.post("/signup", status_code=202)
    def signup(body: SignUp, request: Request) -> dict:
        acc = need_accounts()
        throttle(request, "signup", 5, 3600)
        if not body.terms:
            raise HTTPException(422, "Please accept the terms of use and the privacy policy.")
        if s.signups == "closed":
            raise HTTPException(403, "Sign-ups are closed at the moment.")
        if s.signups == "invite" and body.invite.strip() not in {c.strip() for c in s.invite_codes.split(",") if c.strip()}:
            raise HTTPException(403, "You need an invitation code to sign up.")
        email = body.email.strip().lower()
        if not EMAIL.match(email):
            raise HTTPException(422, "That does not look like an e-mail address.")
        problem = passwords.policy_problem(body.password, email)
        if problem:
            raise HTTPException(422, problem)
        user = acc.create_user(email, passwords.hash_password(body.password), verified=not s.require_email_verification)
        assert mailer is not None
        if user is None:  # the same answer as for a new address: nobody can use this form to find out who has an account
            mailer.send(email, "Your AI Video Creator account", "Someone tried to sign up with this address, but it already has an account.\nIf it was you, log in or reset your password:\n" + s.public_url + "/login\n")
        elif s.require_email_verification:
            token = acc.create_token(user.id, "verify", 48)
            mailer.send(email, "Confirm your e-mail address", f"Welcome to AI Video Creator.\nConfirm your address to start:\n{s.public_url}/verify?token={token}\n\nThe link works for 48 hours.\n")
        return generic

    @router.post("/verify")
    def verify(body: TokenBody, request: Request) -> dict:
        acc = need_accounts()
        throttle(request, "verify", 20, 3600)
        uid = acc.consume_token(body.token, "verify")
        if not uid:
            raise HTTPException(400, "This link is invalid or has expired. Sign up again or ask for a new link by logging in.")
        acc.set_verified(uid)
        return {"message": "Your e-mail address is confirmed. You can log in now."}

    @router.post("/login")
    def login(body: LogIn, request: Request, response: Response) -> dict:
        acc = need_accounts()
        throttle(request, "login", 20, 600)
        throttle(request, "login-account", 8, 600, body.email)
        row = acc.by_email(body.email)
        ok = bool(row) and passwords.verify_password(body.password, row.password_hash)
        if not row:
            passwords.burn_time()
        if not ok or row.disabled:
            raise HTTPException(401, "E-mail or password is wrong.")
        if not row.verified:
            raise HTTPException(403, "Confirm your e-mail address first: open the link we sent you.")
        set_cookie(response, acc.create_session(row.id))
        return {"user": {"id": row.id, "email": row.email, "admin": row.role == "admin", "verified": True}}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        if accounts is not None:
            token = request.cookies.get(COOKIE)
            if token:
                accounts.end_session(token)
        response.delete_cookie(COOKIE, path="/")
        return {"message": "Logged out."}

    @router.post("/forgot", status_code=202)
    def forgot(body: Forgot, request: Request) -> dict:
        acc = need_accounts()
        throttle(request, "forgot", 5, 3600)
        throttle(request, "forgot-account", 3, 3600, body.email)
        row = acc.by_email(body.email)
        if row and not row.disabled:
            token = acc.create_token(row.id, "reset", 1)
            assert mailer is not None
            mailer.send(row.email, "Reset your password", f"Choose a new password:\n{s.public_url}/reset?token={token}\n\nThe link works for one hour. If you did not ask for this, ignore this e-mail.\n")
        return generic

    @router.post("/reset")
    def reset(body: Reset, request: Request) -> dict:
        acc = need_accounts()
        throttle(request, "reset", 10, 3600)
        problem = passwords.policy_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        uid = acc.consume_token(body.token, "reset")
        if not uid:
            raise HTTPException(400, "This link is invalid or has expired. Ask for a new one.")
        acc.set_password(uid, passwords.hash_password(body.password))
        acc.set_verified(uid)  # reading the e-mail proves the address as well
        return {"message": "Your password has been changed. Log in with the new one."}

    @router.delete("/account")
    def delete_account(body: Confirm, request: Request, response: Response) -> dict:
        acc = need_accounts()
        user = request.state.user
        row = acc.by_email(user.email)
        throttle(request, "delete-account", 5, 3600, user.email)
        if not row or not passwords.verify_password(body.password, row.password_hash):
            raise HTTPException(401, "The password is wrong.")
        assert quotas is not None
        if quotas.active_jobs(user.id):
            raise HTTPException(409, "A video is still being made. Wait until it has finished, then delete the account.")
        for p in quotas.projects(user.id):
            store.delete(p.id)
        acc.delete_user(user.id)
        quotas.forget(user.id)
        response.delete_cookie(COOKIE, path="/")
        return {"message": "Your account and all your projects have been deleted."}

    @router.get("/export")
    def export_data(request: Request) -> FileResponse:
        """Everything of yours that cannot simply be made again, as one zip: projects (settings, timeline, scenes, credits), uploads and exports."""
        need_accounts()
        user = request.state.user
        assert quotas is not None
        throttle(request, "export-data", 3, 3600, user.email)
        tmp = Path(tempfile.mkdtemp(prefix="avc-export-"))
        target = tmp / "my-data.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            z.writestr("account.txt", f"E-mail: {user.email}\n")
            for p in quotas.projects(user.id):
                d = store.path(p.id)
                for name in ("project.json", "timeline.json", "scenes.json", "assets.json", "script.txt", "CREDITS.txt", "captions.json", "output.mp4", "preview.mp4"):
                    if (d / name).is_file():
                        z.write(d / name, f"{p.id}/{name}")
                if (d / "uploads").is_dir():
                    for f in (d / "uploads").iterdir():
                        if f.is_file() and ".part" not in f.name:
                            z.write(f, f"{p.id}/uploads/{f.name}")
        resp = FileResponse(target, media_type="application/zip", filename="my-data.zip")
        resp.background = _cleanup(tmp)
        return resp

    return router


def _cleanup(folder: Path):
    from starlette.background import BackgroundTask

    return BackgroundTask(shutil.rmtree, folder, True)
