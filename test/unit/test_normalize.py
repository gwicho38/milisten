import pytest

from milisten.normalize import (
    FULL,
    LIGHT,
    STANDARD,
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("91pp. Comments closed.", "91 pages. Comments closed."),
        ("filed in Aug. The court ruled.", "filed in August. The court ruled."),
        ("36pp., is long.", "36 pages, is long."),
        ("due Feb. 2026 under the rule.", "due February 2026 under the rule."),
        ("see pp. 12-14. Then compare.", "see pages 12 to 14. Then compare."),
    ],
)
def test_abbreviation_periods_that_also_end_a_sentence_are_kept(raw, expected):
    assert expand_citations(raw) == expected


def test_a_swallowed_boundary_would_cost_the_chunker_a_split():
    from milisten.chunk import chunk

    assert len(chunk(normalize("The rule is 91pp. Comments closed today."))) >= 1
    assert ". " in normalize("The rule is 91pp. Comments closed today.")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("26%->18%", "26 percent to 18 percent"),
        ("26%→18%", "26 percent to 18 percent"),
        ("55%-->63%", "55 percent to 63 percent"),
        ("69%>82%", "69 percent to 82 percent"),
    ],
)
def test_arrow_forms_all_read_as_to(raw, expected):
    assert expand_numbers(raw) == expected


def test_typographic_dash_ranges_become_to():
    assert expand_numbers("2020–2025") == "2020 to 2025"


def test_ascii_hyphens_are_left_alone_because_they_are_usually_identifiers():
    """A plain hyphen is as often a bill or docket number as a range, and
    "Senate Bill 26 to 189" is a far worse error than an unexpanded range."""
    for identifier in ("SB 26-189", "33-11414", "2020-2025"):
        assert expand_numbers(identifier) == identifier


# --- normalization levels --------------------------------------------------

SPECIMEN = "SEC and the EDPB agree; see 91 Fed. Reg. 24968, 91pp., e.g. Art. 50(2)."


def test_light_leaves_acronyms_and_abbreviations_alone():
    out = normalize(SPECIMEN, LIGHT)
    assert "SEC" in out and "EDPB" in out
    assert "e.g." in out and "91pp." in out


def test_light_still_fixes_what_every_engine_misreads():
    out = normalize(SPECIMEN, LIGHT)
    assert "volume 91 of the Federal Register at page 24968" in out
    assert "Article 50, paragraph 2" in out


def test_standard_expands_abbreviations_but_keeps_acronyms_whole():
    out = normalize(SPECIMEN, STANDARD)
    assert "91 pages" in out and "for example" in out
    assert "SEC" in out and "S E C" not in out


def test_full_spells_acronyms():
    assert "S E C" in normalize(SPECIMEN, FULL)


def test_levels_are_monotonic_in_how_much_they_rewrite():
    light, standard, full = (normalize(SPECIMEN, lvl) for lvl in (LIGHT, STANDARD, FULL))
    assert light != standard != full


def test_every_level_strips_urls_and_stays_idempotent():
    raw = "See https://sec.gov/x. Per the rule, 26%->18%."
    for level in (LIGHT, STANDARD, FULL):
        once = normalize(raw, level)
        assert "http" not in once
        assert normalize(once, level) == once


def test_default_level_is_full_so_existing_callers_are_unchanged():
    assert normalize(SPECIMEN) == normalize(SPECIMEN, FULL)


def test_unknown_high_level_behaves_as_full():
    assert normalize(SPECIMEN, 99) == normalize(SPECIMEN, FULL)


# --- URL removal must not eat the sentence's own punctuation ---------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("See https://sec.gov/x. Per the rule.", "See. Per the rule."),
        ("see (https://a.co/b) and more.", "see and more."),
        ('quoted "https://a.co/b". Next.', "quoted. Next."),
        ("comma https://a.co/b, then more.", "comma, then more."),
    ],
)
def test_url_removal_preserves_following_punctuation(raw, expected):
    assert normalize(raw, LIGHT) == expected


def test_a_stripped_url_no_longer_merges_two_sentences():
    out = normalize("See https://sec.gov/x. Per the rule.", LIGHT)
    assert out.count(".") == 2


def test_markdown_images_are_dropped_not_read_as_alt_text():
    assert strip_links("before ![a chart of rates](https://x.co/i.png) after") == "before  after"


def test_markdown_links_still_keep_their_label():
    assert strip_links("see [the rule](https://x.co/r) now") == "see the rule now"
