"""HTTP Range parsing. Pure — seeking a ten-hour audiobook depends on it.

A player cannot jump to chapter 40 of a 3GB file without byte ranges, so the
audio route must answer 206 with a correct Content-Range. Only single ranges are
supported, which is all any browser media element asks for.
"""

from __future__ import annotations

import re

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 1 << 20


def parse(header: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive (start, end) clamped to size, or None to send the whole file."""
    if not header or size <= 0:
        return None
    match = RANGE.match(header.strip())
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:
        length = min(int(last), size)
        return (size - length, size - 1) if length else None
    start = int(first)
    if start >= size:
        return None
    end = min(int(last), size - 1) if last else size - 1
    return (start, end) if end >= start else None


def content_range(start: int, end: int, size: int) -> str:
    return f"bytes {start}-{end}/{size}"
