"""Linux-only proof that a killed render parent cannot leave its child running."""

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    if sys.platform != "linux":
        raise RuntimeError("Linux process-boundary verification required")
    launch = """
import os, subprocess, sys, time
subprocess.Popen([sys.executable, '-m', 'zoclip.rendering.runner', '10', '1048576',
                  str(os.getpid()), sys.executable, '-c',
                  'import os,time;print(os.getpid(),flush=True);time.sleep(30)'])
time.sleep(30)
"""
    parent = subprocess.Popen([sys.executable, "-c", launch], stdout=subprocess.PIPE)
    child = None
    try:
        assert parent.stdout is not None
        # Child prints only after the boundary has set and checked PDEATHSIG.
        child = int(parent.stdout.readline())
        parent.terminate()
        parent.wait(timeout=3)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = Path(f"/proc/{child}/status")
            if not status.exists() or "State:\tZ" in status.read_text():
                print("PASS: SIGTERM of render parent kills its running child (PDEATHSIG)")
                return
            time.sleep(0.1)
        raise AssertionError("Render child survived parent termination")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if parent.stdout:
            parent.stdout.close()
        if child:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    main()
