"""Disposable DNS process: parent imposes a hard deadline without leaked threads."""

import json
import socket
import sys


def main() -> None:
    answers = socket.getaddrinfo(sys.argv[1], 443, type=socket.SOCK_STREAM)
    addresses = sorted({str(item[4][0]) for item in answers})
    if len(addresses) > 64:
        raise ValueError("DNS answer limit")
    print(json.dumps(addresses))


if __name__ == "__main__":
    main()
