from pathlib import Path

from milisten.models import Chapter
from milisten.package import concat_list, ffmetadata


def _chapters():
    return (
        Chapter("First article", Path("/tmp/a.wav"), 60.0),
        Chapter("Second; with = specials", Path("/tmp/b.wav"), 30.5),
    )


def test_chapter_offsets_accumulate():
    meta = ffmetadata(_chapters(), "AI Governance")
    assert "START=0" in meta
    assert "END=60000" in meta
    assert "START=60000" in meta
    assert "END=90500" in meta


def test_metadata_escapes_ffmpeg_delimiters():
    meta = ffmetadata(_chapters(), "AI Governance")
    assert r"Second\; with \= specials" in meta


def test_album_title_lands_in_metadata():
    assert "title=AI Governance" in ffmetadata(_chapters(), "AI Governance")


def test_concat_list_quotes_absolute_paths():
    listing = concat_list(_chapters())
    assert listing.splitlines()[0].startswith("file '/")
    assert len(listing.splitlines()) == 2
