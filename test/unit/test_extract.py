from milisten.extract import BLOCKED, RETRYABLE, detect_kind, resolve, sniff, source_host
from milisten.models import SourceKind


def test_pdf_extension_is_recognized():
    assert detect_kind("https://example.com/rule.pdf") == SourceKind.PDF


def test_query_string_does_not_hide_the_extension():
    assert detect_kind("https://example.com/rule.pdf?dl=1") == SourceKind.PDF


def test_extensionless_url_defers_to_sniffing():
    assert detect_kind("https://arxiv.org/pdf/2410.21279") == SourceKind.AUTO


def test_pdf_magic_bytes_win_over_a_missing_extension():
    assert sniff(b"%PDF-1.7\n%...") == SourceKind.PDF


def test_content_type_identifies_a_pdf_without_magic_bytes():
    assert sniff(b"", "application/pdf; charset=binary") == SourceKind.PDF


def test_doctype_identifies_html():
    assert sniff(b"<!DOCTYPE html><html><body>hi") == SourceKind.HTML


def test_plain_text_is_the_fallback():
    assert sniff(b"Just some prose.", "text/plain") == SourceKind.TEXT


def test_resolve_never_overrides_an_explicit_kind():
    assert resolve(SourceKind.TEXT, b"%PDF-1.7") == SourceKind.TEXT
    assert resolve(SourceKind.AUTO, b"%PDF-1.7") == SourceKind.PDF


def test_bot_wall_codes_are_not_retried():
    assert 403 in BLOCKED and 401 in BLOCKED
    assert not (BLOCKED & RETRYABLE)


def test_transient_codes_are_retryable():
    for code in (429, 500, 502, 503, 504):
        assert code in RETRYABLE


def test_source_host_extracts_the_hostname():
    assert source_host("https://www.americanbar.org/a/b.pdf") == "www.americanbar.org"
