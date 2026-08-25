"""Reading-queue persistence. A single JSON file, rewritten atomically.

Paths are resolved per call, not at import: MILISTEN_HOME has to be honoured by
a process that sets it after this module loads, and a default argument bound to
a module constant cannot be overridden at all.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from .extract import detect_kind
from .models import Source, SourceKind


def home() -> Path:
    return Path(os.environ.get("MILISTEN_HOME", Path.home() / ".milisten")).expanduser()


def queue_path() -> Path:
    return home() / "queue.json"


def audio_path() -> Path:
    return Path(os.environ.get("MILISTEN_AUDIO", home() / "audio")).expanduser()


def load(path: Path | None = None) -> tuple[Source, ...]:
    target = path or queue_path()
    if not target.exists():
        return ()
    try:
        raw = json.loads(target.read_text())
    except json.JSONDecodeError:
        return ()
    return tuple(
        Source(
            ref=row["ref"],
            title=row["title"],
            kind=SourceKind(row["kind"]),
            area=row.get("area", "unfiled"),
        )
        for row in raw
    )


def save(sources: Sequence[Source], path: Path | None = None) -> None:
    target = path or queue_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"ref": s.ref, "title": s.title, "kind": str(s.kind), "area": s.area} for s in sources
    ]
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(target)


def add(sources: Sequence[Source], ref: str, title: str, area: str) -> tuple[Source, ...]:
    if any(s.ref == ref for s in sources):
        return tuple(sources)
    return (*sources, Source(ref=ref, title=title, kind=detect_kind(ref), area=area))


def remove(sources: Sequence[Source], ref: str) -> tuple[Source, ...]:
    return tuple(s for s in sources if s.ref != ref and s.slug != ref)


def by_area(sources: Sequence[Source]) -> dict[str, tuple[Source, ...]]:
    areas: dict[str, list[Source]] = {}
    for source in sources:
        areas.setdefault(source.area, []).append(source)
    return {area: tuple(items) for area, items in areas.items()}
