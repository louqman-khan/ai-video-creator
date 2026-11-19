import smtplib

from app.accounts.mailer import ConsoleMailer, SmtpMailer, create_mailer
from app.config import Settings


class Fake:
    """Stands in for smtplib's classes: records what a mailer does, sends nothing."""

    log: list = []

    def __init__(self, kind):
        self.kind = kind

    def __call__(self, host, port, timeout=None):
        Fake.log.append((self.kind, host, port))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        Fake.log.append(("starttls",))

    def login(self, user, password):
        Fake.log.append(("login", user, bool(password)))

    def send_message(self, msg):
        Fake.log.append(("send", msg["To"], msg["From"], msg["Subject"]))


def mail(port, monkeypatch):
    Fake.log = []
    monkeypatch.setattr(smtplib, "SMTP", Fake("plain"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", Fake("ssl"))
    s = Settings(_env_file=None, smtp_host="mail.example.com", smtp_port=port, smtp_user="u@example.com", smtp_password="pw", mail_from="App <u@example.com>")
    SmtpMailer(s).send("to@example.com", "Hello", "body")
    return Fake.log


def test_port_465_is_encrypted_from_the_start_and_does_not_start_tls_again(monkeypatch):
    log = mail(465, monkeypatch)
    assert log == [("ssl", "mail.example.com", 465), ("login", "u@example.com", True), ("send", "to@example.com", "App <u@example.com>", "Hello")]


def test_port_587_starts_plain_and_upgrades(monkeypatch):
    log = mail(587, monkeypatch)
    assert log == [("plain", "mail.example.com", 587), ("starttls",), ("login", "u@example.com", True), ("send", "to@example.com", "App <u@example.com>", "Hello")]


def test_without_a_host_mail_goes_to_the_outbox_folder(tmp_path):
    assert isinstance(create_mailer(Settings(_env_file=None, smtp_host="", work_dir=str(tmp_path))), ConsoleMailer)
    assert isinstance(create_mailer(Settings(_env_file=None, smtp_host="mail.example.com")), SmtpMailer)
