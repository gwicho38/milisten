"""Imperative shell: every side effect in milisten is invoked from here."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import library, package, tts
from .chunk import chunk
from .extract import ExtractionError, extract
from .models import Chapter
from .normalize import normalize

OUT = library.HOME / "audio"


def _err(message: str) -> None:
    click.secho(f"  ! {message}", fg="red", err=True)


@click.group(help="Turn articles, papers and regulatory PDFs into chaptered audiobooks.")
@click.version_option(package_name="milisten")
def main() -> None: ...


@main.command()
@click.argument("ref")
@click.option("--title", "-t", default=None, help="Chapter title; defaults to the file/URL stem.")
@click.option("--area", "-a", default="unfiled", help="Grouping used to build volumes.")
def add(ref: str, title: str | None, area: str) -> None:
    """Queue a URL or local file (PDF, HTML, text)."""
    resolved = str(Path(ref).expanduser()) if not ref.startswith("http") else ref
    name = title or Path(resolved.split("?")[0]).stem.replace("-", " ").replace("_", " ").strip()
    sources = library.add(library.load(), resolved, name or resolved, area)
    library.save(sources)
    click.echo(f"queued [{area}] {name}")


@main.command("import")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def import_list(path: Path) -> None:
    """Bulk-queue from a text file of `area | title | ref` lines (blank lines and # ignored)."""
    sources = library.load()
    count = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            _err(f"skipped malformed line: {line[:60]}")
            continue
        area, title, ref = parts
        before = len(sources)
        sources = library.add(sources, ref, title, area)
        count += len(sources) > before
    library.save(sources)
    click.echo(f"queued {count} new sources ({len(sources)} total)")


@main.command("list")
def list_queue() -> None:
    """Show the queue grouped by area."""
    sources = library.load()
    if not sources:
        click.echo("queue is empty — try: milisten add <url>")
        return
    for area, items in library.by_area(sources).items():
        click.secho(f"\n{area}  ({len(items)})", bold=True)
        for source in items:
            tag = "file" if source.is_local else str(source.kind)
            click.echo(f"  [{tag:>4}] {source.title}")


@main.command()
@click.argument("ref")
def remove(ref: str) -> None:
    """Drop a source by URL, path or slug."""
    library.save(library.remove(library.load(), ref))
    click.echo(f"removed {ref}")


@main.command()
@click.argument("ref", required=False)
@click.option("--layout", is_flag=True, help="Preserve PDF column layout during extraction.")
@click.option("--chars", default=1800, help="How much normalized text to print.")
def preview(ref: str | None, layout: bool, chars: int) -> None:
    """Print normalized text without synthesizing. The fastest way to tune rules."""
    sources = library.load()
    targets = [s for s in sources if ref in (s.ref, s.slug)] if ref else list(sources[:1])
    if not targets:
        _err("no matching source in the queue")
        sys.exit(1)
    for source in targets:
        click.secho(f"\n=== {source.title} ===", bold=True)
        try:
            body = normalize(extract(source, layout).body)
        except (ExtractionError, OSError) as exc:
            _err(str(exc))
            continue
        pieces = chunk(body)
        click.echo(body[:chars])
        click.secho(f"\n[{len(body):,} chars, {len(pieces)} chunks]", fg="green")


@main.command()
@click.option("--area", "-a", default=None, help="Build one area only; default builds each area.")
@click.option("--engine", default="kokoro", type=click.Choice(["kokoro", "say"]))
@click.option("--voice", default="heart", help=f"One of: {', '.join(tts.VOICES)}")
@click.option("--speed", default=1.0, help="Playback rate baked into synthesis.")
@click.option("--layout", is_flag=True, help="Preserve PDF column layout during extraction.")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Output directory.")
@click.option("--keep-wav", is_flag=True, help="Leave per-chapter WAVs on disk.")
def build(
    area: str | None,
    engine: str,
    voice: str,
    speed: float,
    layout: bool,
    out: Path | None,
    keep_wav: bool,
) -> None:
    """Synthesize one .m4b per area, each source a chapter."""
    sources = library.load()
    if not sources:
        _err("queue is empty")
        sys.exit(1)

    groups = library.by_area(sources)
    if area:
        if area not in groups:
            _err(f"unknown area {area!r}; have: {', '.join(groups)}")
            sys.exit(1)
        groups = {area: groups[area]}

    destination = (out or OUT).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    synth = tts.build(engine, voice, speed)
    skipped: list[str] = []

    for group, items in groups.items():
        click.secho(f"\n{group}", bold=True)
        chapters: list[Chapter] = []
        wavs = destination / f".{group}"
        wavs.mkdir(parents=True, exist_ok=True)

        for source in items:
            click.echo(f"  {source.title[:70]} ", nl=False)
            try:
                body = normalize(extract(source, layout).body)
                pieces = [c.text for c in chunk(body)]
                wav = wavs / f"{source.slug or 'part'}.wav"
                seconds = tts.render(synth, pieces, wav)
            except (ExtractionError, OSError, RuntimeError) as exc:
                click.secho("skipped", fg="yellow")
                skipped.append(f"{source.title}: {exc}")
                continue
            chapters.append(Chapter(source.title, wav, seconds))
            click.secho(f"{seconds / 60:.1f} min", fg="green")

        if not chapters:
            _err(f"nothing rendered for {group}")
            continue
        book = package.build_m4b(chapters, destination / f"{group}.m4b", group)
        total = sum(c.seconds for c in chapters) / 60
        click.secho(f"  -> {book}  ({len(chapters)} chapters, {total:.0f} min)", fg="cyan")
        if not keep_wav:
            for chapter in chapters:
                chapter.audio.unlink(missing_ok=True)
            wavs.rmdir()

    if skipped:
        click.secho(f"\n{len(skipped)} source(s) skipped:", fg="yellow")
        for note in skipped:
            click.echo(f"  - {note}")


if __name__ == "__main__":
    main()
