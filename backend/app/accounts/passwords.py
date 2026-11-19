"""Password hashing with scrypt (Python's standard library, OWASP-approved parameters) and the password policy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

N, R, P = 2**15, 8, 1
SALT_BYTES = 16
KEY_BYTES = 32
MIN_LENGTH = 6
MAX_LENGTH = 200  # scrypt on a huge input is a cheap way to burn CPU
COMMON = {"password", "passwordpassword", "1234567890", "qwertyuiop", "iloveyou12", "0123456789", "password123", "letmein1234", "1q2w3e4r5t",
          # with a short minimum the everyday favourites matter most
          "123456", "1234567", "12345678", "123456789", "111111", "000000", "654321", "123123", "121212", "abc123", "abcdef", "abc12345", "qwerty", "qwerty1", "qwerty12", "qwerty123",
          "password1", "passw0rd", "p@ssword", "welcome", "welcome1", "letmein", "iloveyou", "admin123", "administrator", "changeme", "football", "baseball", "monkey", "dragon", "sunshine", "princess",
          "pakistan", "pakistan1", "allahuakbar", "muhammad", "786786", "123456a", "1q2w3e", "zxcvbn", "asdfgh", "asdfghjk"}


def policy_problem(password: str, email: str = "") -> str | None:
    """Why this password is refused (None = fine)."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    low = password.lower()
    if low in COMMON or len(set(low)) < 3:
        return "That password is too easy to guess."
    if email and (low == email.lower() or low == email.split("@")[0].lower()):
        return "The password must not be your e-mail address."
    return None


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    key = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=KEY_BYTES, maxmem=128 * 1024 * 1024)
    return "scrypt$%d$%d$%d$%s$%s" % (N, R, P, base64.b64encode(salt).decode(), base64.b64encode(key).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode()[:MAX_LENGTH * 4], salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=KEY_BYTES, maxmem=128 * 1024 * 1024)
        return hmac.compare_digest(calc, base64.b64decode(key))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not-a-real-password")


def burn_time() -> None:
    """Spend the same time as a real check, so that an unknown e-mail cannot be told from a wrong password by the response time."""
    verify_password("x", _DUMMY)
