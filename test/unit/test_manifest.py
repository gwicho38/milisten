from pathlib import Path

from milisten import manifest
from milisten.models import Chapter


def _chapters():
    return (
        Chapter("First", Path("/tmp/a.wav"), 60.0),
        Chapter("Second", Path("/tmp/b.wav"), 30.5),
        Chapter("Third", Path("/tmp/c.wav"), 9.5),
    )


def test_spans_are_contiguous_from_zero():
    spans = manifest.spans(_chapters())
    assert spans[0].start == 0.0
    assert [s.start for s in spans[1:]] == [s.end for s in spans[:-1]]


def test_span_length_matches_its_chapter():
    assert [round(s.seconds, 1) for s in manifest.spans(_chapters())] == [60.0, 30.5, 9.5]


def test_duration_is_the_sum():
    assert manifest.duration(_chapters()) == 100.0


def test_empty_chapter_list_has_no_spans():
    assert manifest.spans(()) == ()
    assert manifest.duration(()) == 0


def test_payload_records_engine_and_voice():
    payload = manifest.to_dict("hipaa", _chapters(), "heart", "kokoro")
    assert payload["area"] == "hipaa"
    assert payload["voice"] == "heart"
    assert payload["engine"] == "kokoro"
    assert payload["seconds"] == 100.0
    assert len(payload["chapters"]) == 3


def test_manifest_sits_beside_the_audio(tmp_path):
    audio = tmp_path / "ma.m4b"
    assert manifest.path_for(audio) == tmp_path / "ma.json"


def test_round_trip_through_disk(tmp_path):
    audio = tmp_path / "ma.m4b"
    payload = manifest.to_dict("ma", _chapters(), "emma", "say")
    manifest.write(audio, payload)
    assert manifest.read(audio) == payload


def test_missing_manifest_reads_as_none(tmp_path):
    assert manifest.read(tmp_path / "nothing.m4b") is None


def test_corrupt_manifest_reads_as_none(tmp_path):
    audio = tmp_path / "ma.m4b"
    manifest.path_for(audio).write_text("{not json")
    assert manifest.read(audio) is None
