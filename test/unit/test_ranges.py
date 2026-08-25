import pytest

from milisten.web.ranges import content_range, parse

SIZE = 1000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-200", (800, 999)),
        ("bytes=0-", (0, 999)),
        (" bytes=5-10 ", (5, 10)),
    ],
)
def test_supported_range_forms(header, expected):
    assert parse(header, SIZE) == expected


@pytest.mark.parametrize(
    "header",
    [None, "", "items=0-10", "bytes=abc-def", "bytes=-", "bytes=0-10, 20-30"],
)
def test_unusable_headers_fall_back_to_the_whole_file(header):
    assert parse(header, SIZE) is None


def test_end_is_clamped_to_the_last_byte():
    assert parse("bytes=900-99999", SIZE) == (900, 999)


def test_start_past_the_end_is_unsatisfiable():
    assert parse("bytes=1000-", SIZE) is None
    assert parse("bytes=5000-6000", SIZE) is None


def test_inverted_range_is_rejected():
    assert parse("bytes=500-100", SIZE) is None


def test_suffix_longer_than_the_file_yields_the_whole_file():
    assert parse("bytes=-5000", SIZE) == (0, 999)


def test_empty_file_has_no_satisfiable_range():
    assert parse("bytes=0-10", 0) is None


def test_content_range_header_is_inclusive_and_carries_total():
    assert content_range(0, 99, SIZE) == "bytes 0-99/1000"
