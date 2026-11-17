"""Sending e-mail (verification and password reset). Without SMTP settings the message is written to <work_dir>/outbox/ and the log: enough for development and tests."""

from __future__ import annotations

import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from app.config import Settings

log = logging.getLogger("avc.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    def __init__(self, outbox: Path) -> None:
        self.outbox = outbox

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}.txt"
        (self.outbox / name).write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", "utf-8")
        log.info("e-mail to %s: %s (written to %s)", to, subject, self.outbox / name)


class SmtpMailer:
    def __init__(self, s: Settings) -> None:
        self.s = s

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.mail_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


def create_mailer(s: Settings) -> Mailer:
    return SmtpMailer(s) if s.smtp_host else ConsoleMailer(Path(s.work_dir) / "outbox")
