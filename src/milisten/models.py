from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path


class SourceKind(StrEnum):
    AUTO = "auto"
    HTML = "html"
    PDF = "pdf"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class Source:
    ref: str
    title: str
    kind: SourceKind
    area: str = "unfiled"

    @property
    def is_local(self) -> bool:
        return not self.ref.startswith(("http://", "https://"))

    @property
    def slug(self) -> str:
        flat = "".join(c.lower() if c.isalnum() else "-" for c in self.title)
        return "-".join(filter(None, flat.split("-")))[:80]


@dataclass(frozen=True, slots=True)
class Document:
    source: Source
    body: str

    def with_body(self, body: str) -> Document:
        return replace(self, body=body)


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    audio: Path
    seconds: float
