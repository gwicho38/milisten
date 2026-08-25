"""Assemble rendered WAVs into a chaptered .m4b via ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .models import Chapter


def _escape(value: str) -> str:
    for char in ("\\", "=", ";", "#", "\n"):
        value = value.replace(char, " " if char == "\n" else f"\\{char}")
    return value


def ffmetadata(chapters: Sequence[Chapter], album: str) -> str:
    lines = [";FFMETADATA1", f"title={_escape(album)}", "artist=milisten", "genre=Speech"]
    start = 0.0
    for chapter in chapters:
        end = start + chapter.seconds
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={_escape(chapter.title)}",
        ]
        start = end
    return "\n".join(lines) + "\n"


def concat_list(chapters: Sequence[Chapter]) -> str:
    return "".join(f"file '{c.audio.resolve()}'\n" for c in chapters)


def build_m4b(chapters: Sequence[Chapter], out: Path, album: str, bitrate: str = "64k") -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    if not chapters:
        raise ValueError("no chapters to package")

    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    listing = work / f"{out.stem}.concat.txt"
    meta = work / f"{out.stem}.meta.txt"
    listing.write_text(concat_list(chapters))
    meta.write_text(ffmetadata(chapters, album))

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-i", str(meta), "-map_metadata", "1",
            "-metadata", f"title={album}", "-metadata", f"album={album}",
            "-metadata", "artist=milisten", "-metadata", "genre=Speech",
            "-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart",
            str(out),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")
    listing.unlink(missing_ok=True)
    meta.unlink(missing_ok=True)
    return out
