"""Imperative shell: every side effect in milisten is invoked from here."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import library, tts
from .build import render_area
from .chunk import chunk
from .extract import ExtractionError, extract
from .normalize import normalize


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

    destination = (out or library.audio_path()).expanduser()
    skipped: list[str] = []

    for group, items in groups.items():
        click.secho(f"\n{group}", bold=True)
        for event in render_area(
            group, items, destination, engine, voice, speed, layout, keep_wav
        ):
            if event.kind == "chapter-start":
                click.echo(f"  [{event.index}/{event.total}] {event.title[:64]} ", nl=False)
            elif event.kind == "chapter-done":
                click.secho(f"{event.seconds / 60:.1f} min", fg="green")
            elif event.kind == "skipped":
                click.secho("skipped", fg="yellow")
                skipped.append(f"{event.title}: {event.detail}")
            elif event.kind == "failed":
                _err(event.detail)
            elif event.kind == "done":
                click.secho(
                    f"  -> {event.path}  ({event.index} chapters,"
                    f" {event.seconds / 60:.0f} min)",
                    fg="cyan",
                )

    if skipped:
        click.secho(f"\n{len(skipped)} source(s) skipped:", fg="yellow")
        for note in skipped:
            click.echo(f"  - {note}")


@main.command()
@click.option("--port", default=0, help="Bind a specific port instead of a free one.")
@click.option("--no-browser", is_flag=True, help="Do not open a browser window.")
@click.option(
    "--stable-token",
    is_flag=True,
    help="Reuse the token in ~/.milisten/token so the URL stays bookmarkable.",
)
@click.argument("action", type=click.Choice(["run", "start", "stop", "open"]), default="run")
def ui(action: str, port: int, no_browser: bool, stable_token: bool) -> None:
    """Serve the local web UI for managing sources and recordings."""
    from .web import launcher

    launcher.dispatch(
        action, port=port, open_browser=not no_browser, stable=stable_token
    )


@main.group()
def agent() -> None:
    """Keep the web UI running at one bookmarkable URL, started at login."""


@agent.command("install")
@click.option("--port", default=None, type=int, help="Port to bind; defaults to 8765.")
def agent_install(port: int | None) -> None:
    """Install and load the launchd agent."""
    from .web import agent as agent_mod

    code, message = agent_mod.install(port or agent_mod.DEFAULT_PORT)
    if code:
        _err(message)
        sys.exit(code)
    click.secho(f"agent running  →  {message}", fg="green")
    click.echo("Bookmark that URL; it survives restarts and logins.")


@agent.command("uninstall")
def agent_uninstall() -> None:
    """Unload and remove the launchd agent."""
    from .web import agent as agent_mod

    click.echo(agent_mod.uninstall()[1])


@agent.command("status")
@click.option("--port", default=None, type=int, help="Port the agent binds.")
def agent_status(port: int | None) -> None:
    """Report whether the agent is installed and loaded."""
    from .web import agent as agent_mod

    code, message = agent_mod.status(port or agent_mod.DEFAULT_PORT)
    click.secho(message, fg="green" if code == 0 else "yellow")
    sys.exit(code)


if __name__ == "__main__":
    main()
