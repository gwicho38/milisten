import pytest

from milisten.normalize import (
    collapse_space,
    drop_page_artifacts,
    expand_citations,
    expand_numbers,
    normalize,
    spell_acronyms,
    strip_links,
    unwrap,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("90 Fed. Reg. 898", "volume 90 of the Federal Register at page 898"),
        ("91 Fed. Reg. 24968", "volume 91 of the Federal Register at page 24968"),
        ("arXiv:2410.21279", "arXiv preprint 2410 point 21279"),
        ("Art. 50(2)", "Article 50, paragraph 2"),
        ("Annex III", "Annex 3"),
        ("Annex I", "Annex 1"),
        ("Reg. (EU) 2026/1744", "E U Regulation 2026 slash 1744"),
        ("SB 26-189", "Senate Bill 26-189"),
        ("H.R. 7148", "House Bill 7148"),
        ("Q1 2026", "first quarter of 2026"),
        ("§ 164.312", "section 164.312"),
        ("16pp.", "16 pages"),
        ("Aug. 2026", "August 2026"),
        ("et al.", "and others"),
    ],
)
def test_citation_expansion(raw, expected):
    assert expand_citations(raw) == expected


def test_case_citation_reads_as_a_case():
    out = expand_citations("Rutledge v. Clearway Energy (Del. 27 Feb. 2026)")
    assert out == "Rutledge versus Clearway Energy (Delaware 27 February 2026)"


def test_docket_number_drops_division_and_padding():
    assert expand_citations("No. 2:24-cv-00228-Z") == "case number 24 c v 228 Z"


def test_northern_district_of_texas_is_spoken_in_full():
    assert "the Northern District of Texas" in expand_citations("(N.D. Tex. 18 June 2025)")


def test_rin_is_spelled_and_dashes_spoken():
    assert expand_citations("RIN 0945-AA22") == "R I N 0945 dash A A 22"


def test_journal_locator_becomes_words():
    out = expand_citations("R. Soc. Open Sci. 13(2):242234")
    assert out == "Royal Society Open Science, volume 13, issue 2, article 242234"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$569bn", "569 billion dollars"),
        ("26%→18%", "26 percent to 18 percent"),
        ("2,300+", "over 2,300"),
        ("2020–2025", "2020 to 2025"),
        ("50-state", "50 state"),
    ],
)
def test_number_expansion(raw, expected):
    assert expand_numbers(raw) == expected


def test_acronyms_are_spelled_letter_by_letter():
    assert spell_acronyms("The EDPB and EDPS agree") == "The E D P B and E D P S agree"


def test_word_acronyms_survive_intact():
    assert spell_acronyms("HIPAA applies") == "HIPAA applies"


def test_roman_numerals_are_not_spelled():
    assert spell_acronyms("Part III applies") == "Part III applies"


def test_all_caps_headings_are_left_alone():
    heading = "SUMMARY OF PROPOSED CHANGES"
    assert spell_acronyms(heading) == heading


def test_urls_are_never_read_aloud():
    out = strip_links("See [the rule](https://example.com/x) at https://example.com/y now")
    assert "http" not in out
    assert "the rule" in out


def test_pdf_page_numbers_and_rules_are_dropped():
    raw = "Body text here.\n12\nPage 3 of 91\n-----\nMore body."
    assert drop_page_artifacts(raw) == "Body text here.\nMore body."


def test_footnote_marker_after_sentence_is_dropped():
    assert drop_page_artifacts("...as required.14 The Department") == "...as required. The Department"


def test_collapse_space_is_idempotent():
    once = collapse_space("a  b\n\n\n\nc  ")
    assert once == collapse_space(once) == "a b\n\nc"


def test_full_pipeline_on_a_real_citation_string():
    raw = (
        "[PDF] SEC, Semiannual Reporting, Release Nos. 33-11414, File No. S7-2026-15, "
        "91 Fed. Reg. 24968 (7 May 2026), 91pp. See https://sec.gov/rules for detail."
    )
    out = normalize(raw)
    assert "http" not in out
    assert "S E C" in out
    assert "volume 91 of the Federal Register at page 24968" in out
    assert "91 pages" in out
    assert "Release Number 33 dash 11414" in out


def test_normalize_is_stable_under_reapplication():
    raw = "Colorado SB 26-189 repeals SB 24-205; see Art. 50(2) and 90 Fed. Reg. 898."
    once = normalize(raw)
    assert normalize(once) == once


def test_hard_wrapped_pdf_lines_are_rejoined():
    raw = "This paper\ncompares three distinct\napproaches."
    assert unwrap(raw) == "This paper compares three distinct approaches."


def test_sentence_ends_keep_their_line_break():
    raw = "First sentence.\nSecond sentence."
    assert unwrap(raw) == raw


def test_title_case_headings_are_not_merged_into_body():
    raw = "Comparative Global Regulation: Policy\nPerspectives from the EU"
    assert unwrap(raw) == raw


def test_dotted_category_codes_are_not_letter_split():
    assert spell_acronyms("[cs.CY]") == "[cs.CY]"


def test_bracketed_acronym_is_still_spelled():
    assert spell_acronyms("(EU) rules") == "(E U) rules"
