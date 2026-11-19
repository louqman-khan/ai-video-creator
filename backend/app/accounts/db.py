"""Accounts, sessions, one-time tokens and usage events in a SQL database (SQLite on one machine, PostgreSQL later: only the URL changes).
Secrets are never stored: sessions and tokens are kept as SHA-256 hashes, passwords as scrypt hashes."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from app.config import Settings

meta = sa.MetaData()
users = sa.Table(
    "users", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("email", sa.String(254), unique=True, nullable=False),
    sa.Column("password_hash", sa.String(300), nullable=False),
    sa.Column("verified", sa.Boolean, nullable=False, default=False),
    sa.Column("role", sa.String(10), nullable=False, default="user"),
    sa.Column("disabled", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("last_login", sa.Float),
)
sessions = sa.Table(
    "sessions", meta,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
)
tokens = sa.Table(
    "tokens", meta,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
    sa.Column("kind", sa.String(10), nullable=False),  # "verify" | "reset"
    sa.Column("expires_at", sa.Float, nullable=False),
)
usage = sa.Table(
    "usage_events", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(32), index=True, nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("ts", sa.Float, nullable=False),
)
credit_events = sa.Table(
    "credit_events", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(32), index=True, nullable=False),
    sa.Column("ts", sa.Float, nullable=False),
    sa.Column("delta", sa.Integer, nullable=False),          # negative: spent; positive: refund or bonus
    sa.Column("reason", sa.String(20), nullable=False),      # "video" | "refund" | "bonus"
    sa.Column("project_id", sa.String(32), index=True),
)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    verified: bool
    role: str
    disabled: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


LOCAL_USER = User(id="local", email="local@localhost", verified=True, role="admin")  # the one person of the desktop app


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def database_url(s: Settings) -> str:
    return s.database_url or f"sqlite:///{Path(s.work_dir) / 'app.db'}"


class Accounts:
    def __init__(self, s: Settings) -> None:
        url = database_url(s)
        if url.startswith("sqlite"):
            Path(s.work_dir).mkdir(parents=True, exist_ok=True)
            self.engine = sa.create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

            @sa.event.listens_for(self.engine, "connect")
            def _pragmas(dbapi, _):  # WAL: readers do not block the writer; foreign keys are off by default in SQLite
                cur = dbapi.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        else:
            self.engine = sa.create_engine(url, pool_pre_ping=True)
        meta.create_all(self.engine)
        self.admin_emails = {e.strip().lower() for e in s.admin_emails.split(",") if e.strip()}
        self.session_seconds = s.session_days * 86400

    # ---- users
    @staticmethod
    def _user(row) -> User:
        return User(id=row.id, email=row.email, verified=row.verified, role=row.role, disabled=row.disabled)

    def create_user(self, email: str, password_hash: str, verified: bool = False) -> User | None:
        """None when the address already has an account."""
        email = email.strip().lower()
        uid = uuid.uuid4().hex
        role = "admin" if email in self.admin_emails else "user"
        try:
            with self.engine.begin() as c:
                c.execute(users.insert().values(id=uid, email=email, password_hash=password_hash, verified=verified, role=role, disabled=False, created_at=time.time()))
        except sa.exc.IntegrityError:
            return None
        return User(uid, email, verified, role)

    def by_email(self, email: str):
        with self.engine.connect() as c:
            return c.execute(users.select().where(users.c.email == email.strip().lower())).first()

    def by_id(self, user_id: str) -> User | None:
        with self.engine.connect() as c:
            row = c.execute(users.select().where(users.c.id == user_id)).first()
        return self._user(row) if row else None

    def set_verified(self, user_id: str) -> None:
        with self.engine.begin() as c:
            c.execute(users.update().where(users.c.id == user_id).values(verified=True))

    def set_password(self, user_id: str, password_hash: str) -> None:
        with self.engine.begin() as c:
            c.execute(users.update().where(users.c.id == user_id).values(password_hash=password_hash))
            c.execute(sessions.delete().where(sessions.c.user_id == user_id))  # a new password ends every session (someone may have stolen one)

    def delete_user(self, user_id: str) -> None:
        with self.engine.begin() as c:
            c.execute(sessions.delete().where(sessions.c.user_id == user_id))
            c.execute(tokens.delete().where(tokens.c.user_id == user_id))
            c.execute(usage.delete().where(usage.c.user_id == user_id))
            c.execute(credit_events.delete().where(credit_events.c.user_id == user_id))
            c.execute(users.delete().where(users.c.id == user_id))

    # ---- sessions
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.engine.begin() as c:
            c.execute(sessions.delete().where(sessions.c.expires_at < now))  # tidy up while we are here
            c.execute(sessions.insert().values(token_hash=digest(token), user_id=user_id, created_at=now, expires_at=now + self.session_seconds))
            c.execute(users.update().where(users.c.id == user_id).values(last_login=now))
        return token

    def session_user(self, token: str) -> User | None:
        now = time.time()
        with self.engine.begin() as c:
            row = c.execute(sa.select(sessions.c.user_id, sessions.c.expires_at).where(sessions.c.token_hash == digest(token))).first()
            if not row or row.expires_at < now:
                return None
            u = c.execute(users.select().where(users.c.id == row.user_id)).first()
        if not u or u.disabled:
            return None
        return self._user(u)

    def end_session(self, token: str) -> None:
        with self.engine.begin() as c:
            c.execute(sessions.delete().where(sessions.c.token_hash == digest(token)))

    # ---- one-time tokens (e-mail verification, password reset)
    def create_token(self, user_id: str, kind: str, hours: float) -> str:
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as c:
            c.execute(tokens.delete().where(sa.and_(tokens.c.user_id == user_id, tokens.c.kind == kind)))  # only the newest link works
            c.execute(tokens.insert().values(token_hash=digest(token), user_id=user_id, kind=kind, expires_at=time.time() + hours * 3600))
        return token

    def create_code(self, user_id: str, minutes: float = 30) -> str:
        """A six-digit code to type instead of clicking the link. Stored only as a hash (of the code and the account), one per account."""
        code = f"{secrets.randbelow(10**6):06d}"
        with self.engine.begin() as c:
            c.execute(tokens.delete().where(sa.and_(tokens.c.user_id == user_id, tokens.c.kind == "code")))
            c.execute(tokens.insert().values(token_hash=digest(f"{user_id}:{code}"), user_id=user_id, kind="code", expires_at=time.time() + minutes * 60))
        return code

    def consume_code(self, user_id: str, code: str) -> bool:
        return self.consume_token(f"{user_id}:{code}", "code") == user_id

    def clear_verification(self, user_id: str) -> None:
        """After the address is confirmed, neither the link nor the code may be used again."""
        with self.engine.begin() as c:
            c.execute(tokens.delete().where(sa.and_(tokens.c.user_id == user_id, tokens.c.kind.in_(["verify", "code"]))))

    def consume_token(self, token: str, kind: str) -> str | None:
        """The user id the token belongs to, once: a used or expired token gives None."""
        with self.engine.begin() as c:
            row = c.execute(tokens.select().where(tokens.c.token_hash == digest(token))).first()
            if not row or row.kind != kind:
                return None
            c.execute(tokens.delete().where(tokens.c.token_hash == row.token_hash))
        return row.user_id if row.expires_at >= time.time() else None

    # ---- usage
    def record(self, user_id: str, kind: str) -> None:
        with self.engine.begin() as c:
            c.execute(usage.insert().values(user_id=user_id, kind=kind, ts=time.time()))

    def count_since(self, user_id: str, kind: str, seconds: float) -> int:
        with self.engine.connect() as c:
            return c.execute(sa.select(sa.func.count()).select_from(usage).where(
                sa.and_(usage.c.user_id == user_id, usage.c.kind == kind, usage.c.ts > time.time() - seconds))).scalar_one()

    # ---- credits (a ledger: the balance is the sum of the events of the current month)
    def credit_add(self, user_id: str, delta: int, reason: str, project_id: str | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(credit_events.insert().values(user_id=user_id, ts=time.time(), delta=delta, reason=reason, project_id=project_id))

    def credit_sum(self, user_id: str, since: float) -> int:
        """What this month's videos and refunds add up to (bonus credits are counted separately: they do not expire)."""
        with self.engine.connect() as c:
            return int(c.execute(sa.select(sa.func.coalesce(sa.func.sum(credit_events.c.delta), 0)).where(
                sa.and_(credit_events.c.user_id == user_id, credit_events.c.ts >= since, credit_events.c.reason != "bonus"))).scalar_one())

    def credit_event_for(self, project_id: str, reason: str) -> int | None:
        """The amount of the first event of this kind for a project (None when there is none)."""
        with self.engine.connect() as c:
            row = c.execute(sa.select(credit_events.c.delta).where(
                sa.and_(credit_events.c.project_id == project_id, credit_events.c.reason == reason)).limit(1)).first()
        return None if row is None else int(row[0])

    # ---- administration
    def list_users(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(sa.select(users).order_by(users.c.created_at.desc())).all()
        return [{"id": r.id, "email": r.email, "role": r.role, "verified": bool(r.verified), "disabled": bool(r.disabled), "created_at": r.created_at, "last_login": r.last_login} for r in rows]

    def set_disabled(self, user_id: str, disabled: bool) -> bool:
        """False when there is no such account. Disabling also ends every session of the person."""
        with self.engine.begin() as c:
            n = c.execute(users.update().where(users.c.id == user_id).values(disabled=disabled)).rowcount
            if n and disabled:
                c.execute(sessions.delete().where(sessions.c.user_id == user_id))
        return bool(n)

    def user_by_id(self, user_id: str) -> User | None:
        with self.engine.connect() as c:
            row = c.execute(sa.select(users).where(users.c.id == user_id)).first()
        return self._user(row) if row else None

    def credit_bonus_total(self, user_id: str) -> int:
        """Bonus credits given to the account so far (they do not expire with the month)."""
        with self.engine.connect() as c:
            return int(c.execute(sa.select(sa.func.coalesce(sa.func.sum(credit_events.c.delta), 0)).where(
                sa.and_(credit_events.c.user_id == user_id, credit_events.c.reason == "bonus"))).scalar_one())

