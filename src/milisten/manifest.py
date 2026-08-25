"""Chapter manifests. Pure functions plus one read and one write.

A rendered .m4b carries chapter marks that browsers cannot read, so every build
writes a sibling <area>.json describing the same spans. The player reads it to
list chapters and to seek.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .models import Chapter

VERSION = 1


@dataclass(frozen=True, slots=True)
class Span:
    title: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return self.end - self.start


def spans(chapters: Sequence[Chapter]) -> tuple[Span, ...]:
    out: list[Span] = []
    cursor = 0.0
    for chapter in chapters:
        out.append(Span(chapter.title, cursor, cursor + chapter.seconds))
        cursor += chapter.seconds
    return tuple(out)


def duration(chapters: Sequence[Chapter]) -> float:
    return sum(c.seconds for c in chapters)


def to_dict(area: str, chapters: Sequence[Chapter], voice: str, engine: str) -> dict:
    return {
        "version": VERSION,
        "area": area,
        "engine": engine,
        "voice": voice,
        "seconds": duration(chapters),
        "chapters": [
            {"title": s.title, "start": round(s.start, 3), "end": round(s.end, 3)}
            for s in spans(chapters)
        ],
    }


def path_for(audio: Path) -> Path:
    return audio.with_suffix(".json")


def write(audio: Path, payload: dict) -> Path:
    target = path_for(audio)
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def read(audio: Path) -> dict | None:
    try:
        return json.loads(path_for(audio).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
