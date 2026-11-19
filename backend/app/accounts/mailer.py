"""Sending e-mail (verification and password reset). Without SMTP settings the message is written to <work_dir>/outbox/ and the log: enough for development and tests."""

from __future__ import annotations

import logging
import smtplib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from app.config import Settings

log = logging.getLogger("avc.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None: ...


class ConsoleMailer:
    def __init__(self, outbox: Path) -> None:
        self.outbox = outbox

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        self.outbox.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns()
        name = f"{stamp}.txt"
        (self.outbox / name).write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", "utf-8")
        if html:
            (self.outbox / f"{stamp}.html").write_text(html, "utf-8")   # open it in a browser to see the styled version
        log.info("e-mail to %s: %s (written to %s)", to, subject, self.outbox / name)


class SmtpMailer:
    def __init__(self, s: Settings) -> None:
        self.s = s

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.mail_from, to, subject
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")   # clients that show HTML use it; the others keep the plain text
        if self.s.smtp_port == 465:  # "implicit TLS": the connection is encrypted from the first byte (587 and 25 start plain and upgrade with STARTTLS)
            smtp = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, timeout=12)
        else:
            smtp = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=12)
        with smtp:
            if self.s.smtp_port != 465:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


class BackgroundMailer:
    """Sends in the background, with retries, so the person never waits for the mail server and a mail server that is slow or down cannot make sign-up fail:
    the request answers at once (as it must anyway, so that a known address cannot be told from an unknown one by the response time) and the e-mail follows.
    A message that cannot be sent after the retries is logged; the person can ask for a new one."""

    def __init__(self, inner: Mailer, tries: int = 4, pause: float = 3.0) -> None:
        self.inner, self.tries, self.pause = inner, tries, pause
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")
        self.failed = 0
        self._lock = threading.Lock()

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        self._pool.submit(self._deliver, to, subject, body, html)

    def _deliver(self, to: str, subject: str, body: str, html: str | None) -> None:
        for n in range(1, self.tries + 1):
            try:
                self.inner.send(to, subject, body, html)
                return
            except Exception as e:  # noqa: BLE001  a mail server can fail in many ways; none of them may crash the site
                log.warning("e-mail to %s: attempt %d of %d failed (%s: %s)", to.split("@")[-1], n, self.tries, type(e).__name__, str(e)[:100])
                if n < self.tries:
                    time.sleep(self.pause * n)
        with self._lock:
            self.failed += 1
        log.error("e-mail \"%s\" could not be delivered after %d attempts (the person can ask for a new one)", subject, self.tries)


def create_mailer(s: Settings) -> Mailer:
    return BackgroundMailer(SmtpMailer(s)) if s.smtp_host else ConsoleMailer(Path(s.work_dir) / "outbox")
