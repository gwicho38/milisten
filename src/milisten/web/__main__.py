"""Detached server entry point: `python -m milisten.web <port> <token>`."""

from __future__ import annotations

import sys

from .launcher import serve


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m milisten.web <port> <token>", file=sys.stderr)
        return 1
    serve(int(sys.argv[1]), sys.argv[2], open_browser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
