"""Fresh-process Linux boundary for FFmpeg and sampled OpenCV (no preexec_fn)."""

import os
import signal
import sys


def main() -> None:
    cpu, size = int(sys.argv[1]), int(sys.argv[2])
    if sys.platform == "linux":
        import ctypes

        # No orphan FFmpeg/OpenCV after a killed RQ workhorse. Check the launch
        # parent's PID after setting the signal to close the parent-death race.
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "parent death protection unavailable")
        if os.getppid() != int(sys.argv[3]):
            raise SystemExit(1)
    if sys.platform != "win32":
        import resource

        for limit, value in (
            (resource.RLIMIT_CPU, cpu),
            (resource.RLIMIT_AS, 1536 * 1024**2),
            (resource.RLIMIT_FSIZE, size),
            (resource.RLIMIT_NOFILE, 64),
            (resource.RLIMIT_CORE, 0),
        ):
            resource.setrlimit(limit, (value, value))
    os.environ.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    os.execvp(sys.argv[4], sys.argv[4:])


if __name__ == "__main__":
    main()
