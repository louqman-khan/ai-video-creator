import os
import subprocess
import sys

from app.procutil import pid_alive


def test_pid_alive_knows_itself_a_running_child_and_a_dead_one():
    assert pid_alive(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert pid_alive(child.pid)
    finally:
        child.kill()
        child.wait()
    assert not pid_alive(child.pid)
    assert not pid_alive(0) and not pid_alive(-5)
