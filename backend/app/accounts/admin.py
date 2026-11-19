"""The operator's view of a hosted site: who has an account, what they use, bonus credits, switching an account off. Administrators only (the guard checks
`/api/admin/*` before any of this runs); the router exists in hosted mode only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.accounts.db import Accounts
from app.accounts.quotas import Quotas


class BonusIn(BaseModel):
    amount: int = Field(..., ge=-1000, le=1000)   # negative takes bonus credits back


class DisableIn(BaseModel):
    disabled: bool


def build_router(accounts: Accounts, quotas: Quotas) -> APIRouter:
    r = APIRouter(prefix="/api/admin", tags=["admin"])

    @r.get("/users")
    def users() -> list[dict]:
        out = []
        for u in accounts.list_users():
            admin = u["role"] == "admin"
            out.append({**u, "projects": len(quotas.projects(u["id"])), "storage_bytes": quotas.storage_bytes(u["id"]), "credits": quotas.credits(u["id"], admin)})
        return out

    @r.post("/users/{uid}/credits")
    def give(uid: str, body: BonusIn) -> dict:
        user = accounts.user_by_id(uid)
        if user is None:
            raise HTTPException(404, "No such account")
        if body.amount == 0:
            raise HTTPException(422, "Choose a number of credits other than zero.")
        c = quotas.credits(uid, user.is_admin)
        if body.amount < 0 and c["bonus"] + body.amount < 0:
            raise HTTPException(422, f"This account only has {c['bonus']} bonus credits to take back.")
        accounts.credit_add(uid, body.amount, "bonus")
        return quotas.credits(uid, user.is_admin)

    @r.post("/users/{uid}/disabled")
    def disable(uid: str, body: DisableIn) -> dict:
        user = accounts.user_by_id(uid)
        if user is None:
            raise HTTPException(404, "No such account")
        if user.is_admin and body.disabled:
            raise HTTPException(422, "An administrator account cannot be switched off here.")
        accounts.set_disabled(uid, body.disabled)
        return {"id": uid, "disabled": body.disabled}

    return r
