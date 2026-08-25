"""Split normalized text into speech-sized pieces on sentence boundaries."""

from __future__ import annotations

import re
from collections.abc import Iterator

from .models import Chunk

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"“'(\[]?[A-Z0-9])")
TARGET = 900
HARD_MAX = 1800


def sentences(text: str) -> tuple[str, ...]:
    parts = (s.strip() for block in text.split("\n\n") for s in SENTENCE_END.split(block))
    return tuple(s for s in parts if s)


def _split_oversize(sentence: str, limit: int) -> Iterator[str]:
    while len(sentence) > limit:
        cut = sentence.rfind(", ", 0, limit)
        cut = cut + 1 if cut > limit // 3 else sentence.rfind(" ", 0, limit)
        cut = cut if cut > 0 else limit
        yield sentence[:cut].strip()
        sentence = sentence[cut:].strip()
    if sentence:
        yield sentence


def pack(items: tuple[str, ...], target: int = TARGET, hard_max: int = HARD_MAX) -> tuple[str, ...]:
    packed: list[str] = []
    buffer = ""
    for raw in items:
        for piece in _split_oversize(raw, hard_max):
            candidate = f"{buffer} {piece}".strip()
            if buffer and len(candidate) > target:
                packed.append(buffer)
                buffer = piece
            else:
                buffer = candidate
    if buffer:
        packed.append(buffer)
    return tuple(packed)


def chunk(text: str, target: int = TARGET) -> tuple[Chunk, ...]:
    return tuple(Chunk(i, t) for i, t in enumerate(pack(sentences(text), target)))
