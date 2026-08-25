"""One build path, consumed by both the CLI and the web job runner.

render_area is a generator: it yields a Progress event per step so a caller can
print to a terminal or push to a polling HTTP client without either owning the
sequencing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import manifest, package, tts
from .chunk import chunk
from .extract import ExtractionError, extract
from .models import Chapter, Source
from .normalize import normalize


@dataclass(frozen=True, slots=True)
class Progress:
    kind: str
    title: str = ""
    index: int = 0
    total: int = 0
    seconds: float = 0.0
    chunks: int = 0
    detail: str = ""
    path: Path | None = None


def workdir(destination: Path, area: str) -> Path:
    return destination / f".{area}"


def render_area(
    area: str,
    sources: Sequence[Source],
    destination: Path,
    engine: str = "kokoro",
    voice: str = "heart",
    speed: float = 1.0,
    layout: bool = False,
    keep_wav: bool = False,
) -> Iterator[Progress]:
    destination.mkdir(parents=True, exist_ok=True)
    scratch = workdir(destination, area)
    scratch.mkdir(parents=True, exist_ok=True)

    yield Progress("loading", detail=f"loading the {engine} voice")
    try:
        synth = tts.build(engine, voice, speed)
    except RuntimeError as exc:
        yield Progress("failed", detail=str(exc))
        return

    chapters: list[Chapter] = []
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        yield Progress("chapter-start", source.title, index, total)
        try:
            body = normalize(extract(source, layout).body)
            pieces = [c.text for c in chunk(body)]
            wav = scratch / f"{source.slug or f'part-{index}'}.wav"
            seconds = tts.render(synth, pieces, wav)
        except (ExtractionError, OSError, RuntimeError) as exc:
            yield Progress("skipped", source.title, index, total, detail=str(exc))
            continue
        chapters.append(Chapter(source.title, wav, seconds))
        yield Progress("chapter-done", source.title, index, total, seconds, len(pieces))

    if not chapters:
        yield Progress("failed", detail=f"nothing rendered for {area}")
        return

    yield Progress("packaging", detail=f"muxing {len(chapters)} chapters")
    audio = destination / f"{area}.m4b"
    try:
        package.build_m4b(chapters, audio, area)
    except (RuntimeError, ValueError) as exc:
        yield Progress("failed", detail=str(exc))
        return
    manifest.write(audio, manifest.to_dict(area, chapters, voice, engine))

    if not keep_wav:
        for chapter in chapters:
            chapter.audio.unlink(missing_ok=True)
        scratch.rmdir()

    yield Progress(
        "done",
        area,
        len(chapters),
        total,
        manifest.duration(chapters),
        path=audio,
    )
