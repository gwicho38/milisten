"""Detached server entry point: `python -m milisten.web <port>`, token on stdin.

The token is read from stdin rather than argv because a command line is visible
to every local user through `ps`, and that token is enough to read any file this
user can read (add a local path as a source, then preview it).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from .launcher import serve

USAGE = "usage: python -m milisten.web <port>   (session token on stdin)"


def main(argv: Sequence[str] | None = None, stdin: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0].isdigit():
        print(USAGE, file=sys.stderr)
        return 1

    token = (stdin or sys.stdin).readline().strip()
    if not token:
        print("Error: a session token is required on stdin", file=sys.stderr)
        return 69

    serve(int(args[0]), token, open_browser=False, announce=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
