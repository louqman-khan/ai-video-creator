import os

# Tests must never call an online service because a developer's .env happens to hold a key.
os.environ["CLEANUP"] = "off"
os.environ["SMTP_HOST"] = ""   # and never send real e-mail from a test, even when the developer's .env holds real mail settings


# On GitHub Actions, show each failing test as an annotation on the run (readable through the public API and on the run's summary page).
_reported = 0


def pytest_runtest_logreport(report):
    global _reported
    if os.environ.get("GITHUB_ACTIONS") and report.failed and _reported < 10:
        _reported += 1
        text = ((report.longreprtext or "")[-700:] + "\nSTDOUT: " + (report.capstdout or "")[-700:]).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"\n::error title={report.nodeid.replace(',', ' ').replace(':', ' ')[:120]}::{text}")
