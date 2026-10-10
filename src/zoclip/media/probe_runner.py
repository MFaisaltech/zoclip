"""Linux resource boundary executed in a fresh process, never preexec_fn in threads."""

import os
import sys


def main() -> None:
    if sys.platform != "win32":
        import resource

        for limit, value in (
            (resource.RLIMIT_CPU, 20),
            (resource.RLIMIT_AS, 512 * 1024**2),
            (resource.RLIMIT_FSIZE, 128 * 1024),
            (resource.RLIMIT_NOFILE, 32),
            (resource.RLIMIT_CORE, 0),
        ):
            resource.setrlimit(limit, (value, value))
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
