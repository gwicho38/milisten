"""Assemble rendered WAVs into a chaptered .m4b via ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from . import manifest
from .models import Chapter


def _escape(value: str) -> str:
    for char in ("\\", "=", ";", "#", "\n"):
        value = value.replace(char, " " if char == "\n" else f"\\{char}")
    return value


def ffmetadata(chapters: Sequence[Chapter], album: str) -> str:
    lines = [";FFMETADATA1", f"title={_escape(album)}", "artist=milisten", "genre=Speech"]
    for span in manifest.spans(chapters):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(span.start * 1000)}",
            f"END={int(span.end * 1000)}",
            f"title={_escape(span.title)}",
        ]
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


def probe_chapters(path: Path) -> tuple[Chapter, ...]:
    """Recover chapter spans from an existing .m4b, for recordings built before manifests."""
    if not shutil.which("ffprobe"):
        return ()
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    try:
        found = json.loads(result.stdout).get("chapters", [])
    except json.JSONDecodeError:
        return ()
    return tuple(
        Chapter(
            c.get("tags", {}).get("title", f"Chapter {i + 1}"),
            path,
            float(c["end_time"]) - float(c["start_time"]),
        )
        for i, c in enumerate(found)
    )
