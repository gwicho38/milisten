"""Reading-queue persistence. A single JSON file, rewritten atomically."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from .extract import detect_kind
from .models import Source, SourceKind

HOME = Path(os.environ.get("MILISTEN_HOME", Path.home() / ".milisten"))
QUEUE = HOME / "queue.json"


def load(path: Path = QUEUE) -> tuple[Source, ...]:
    if not path.exists():
        return ()
    raw = json.loads(path.read_text())
    return tuple(
        Source(ref=r["ref"], title=r["title"], kind=SourceKind(r["kind"]), area=r.get("area", "unfiled"))
        for r in raw
    )


def save(sources: Sequence[Source], path: Path = QUEUE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"ref": s.ref, "title": s.title, "kind": str(s.kind), "area": s.area} for s in sources
    ]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)


def add(sources: Sequence[Source], ref: str, title: str, area: str) -> tuple[Source, ...]:
    if any(s.ref == ref for s in sources):
        return sources
    return (*sources, Source(ref=ref, title=title, kind=detect_kind(ref), area=area))


def remove(sources: Sequence[Source], ref: str) -> tuple[Source, ...]:
    return tuple(s for s in sources if s.ref != ref and s.slug != ref)


def by_area(sources: Sequence[Source]) -> dict[str, tuple[Source, ...]]:
    areas: dict[str, list[Source]] = {}
    for source in sources:
        areas.setdefault(source.area, []).append(source)
    return {area: tuple(items) for area, items in areas.items()}
