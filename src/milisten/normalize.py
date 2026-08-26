"""Rewrite legal and academic prose into text a speech engine reads correctly.

Every function here is pure: text in, text out. Rule order matters — composite
citations are expanded before their component abbreviations are touched.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from functools import reduce

Rule = tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]

# How much help the voice needs. A good neural voice reads "SEC" and "et al."
# correctly, so expanding them only makes it stilted; a robotic voice needs all
# of it. Same rules throughout — the level chooses which groups run.
LIGHT = 1
STANDARD = 2
FULL = 3
LEVEL_NAMES = {LIGHT: "light", STANDARD: "standard", FULL: "full"}


def _spell(token: str) -> str:
    return " ".join(token)


def _dashes_spoken(value: str) -> str:
    spelled = re.sub(r"[A-Za-z]{2,}", lambda m: _spell(m[0]), value)
    out = re.sub(r"[-–]", " dash ", spelled)
    return re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", out)


ROMAN = {
    "I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6",
    "VII": "7", "VIII": "8", "IX": "9", "X": "10", "XI": "11", "XII": "12",
}

CIRCUITS = {
    "1": "First", "2": "Second", "3": "Third", "4": "Fourth", "5": "Fifth",
    "6": "Sixth", "7": "Seventh", "8": "Eighth", "9": "Ninth",
}

QUARTERS = {"1": "first", "2": "second", "3": "third", "4": "fourth"}

MAGNITUDES = {"k": "thousand", "m": "million", "b": "billion", "bn": "billion",
              "t": "trillion", "tn": "trillion"}

# Read as words, never spelled letter by letter.
WORD_ACRONYMS = frozenset({
    "HIPAA", "NASA", "SALI", "FEMA", "OSHA", "ERISA", "COBRA", "NAFTA",
    "ARPA", "CARES", "SCOTUS", "POTUS", "FIRREA", "FINRA", "NAIC", "LIBOR",
})

# Multi-word expansions applied before letter-spelling.
PHRASES: dict[str, str] = {
    "NPRM": "notice of proposed rulemaking",
    "ADMT": "automated decision-making technology",
    "RWI": "representation and warranty insurance",
    "NCII": "non-consensual intimate imagery",
    "CSAM": "child sexual abuse material",
    "NPP": "notice of privacy practices",
    "ePHI": "electronic protected health information",
    "PHI": "protected health information",
    "PII": "personally identifiable information",
    "SLP": "speech-language pathology",
    "IaC": "infrastructure as code",
}

COURTS: dict[str, str] = {
    r"N\.D\.\s*Tex\.": "the Northern District of Texas",
    r"S\.D\.N\.Y\.": "the Southern District of New York",
    r"E\.D\.\s*Va\.": "the Eastern District of Virginia",
    r"D\.\s*Del\.": "the District of Delaware",
    r"Fed\.\s*Cir\.": "the Federal Circuit",
    r"\bDel\.\s*Ch\.": "Delaware Chancery",
    r"\bDel\.(?=\s|\)|,)": "Delaware",
    r"\bCal\.(?=\s|\)|,)": "California",
    r"\bColo\.(?=\s|\)|,)": "Colorado",
    r"\bTex\.(?=\s|\)|,)": "Texas",
}

MONTHS: dict[str, str] = {
    "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
    "Jun": "June", "Jul": "July", "Aug": "August", "Sept": "September",
    "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December",
}

LATIN: dict[str, str] = {
    r"\bet\s+al\.": "and others",
    r"\bcf\.": "compare",
    r"\be\.g\.,?": "for example,",
    r"\bi\.e\.,?": "that is,",
    r"\bibid\.": "the same source",
    r"\bid\.(?=\s|$)": "the same source",
    r"\bsupra\b": "above",
    r"\binfra\b": "below",
    r"\bviz\.": "namely",
}


def _rule(pattern: str, repl: str | Callable[[re.Match[str]], str]) -> Rule:
    return re.compile(pattern), repl


# Level 1 and up: things every engine, neural or not, reads wrongly.
CORE_RULES: tuple[Rule, ...] = (
    # Composite citations first — they contain abbreviations handled later.
    _rule(r"arXiv:\s*(\d{4})\.(\d{4,5})", r"arXiv preprint \1 point \2"),
    _rule(
        r"\b(\d{1,3})\s+Fed\.?\s*Reg\.?\s+([\d,]+)",
        r"volume \1 of the Federal Register at page \2",
    ),
    _rule(r"\bFed\.?\s*Reg\.", "the Federal Register"),
    _rule(
        r"R\.\s*Soc\.\s*Open\s*Sci\.\s*(\d+)\((\d+)\):(\d+)",
        r"Royal Society Open Science, volume \1, issue \2, article \3",
    ),
    _rule(r"\b(\d+)\((\d+)\):(\d+)\b", r"volume \1, issue \2, article \3"),
    _rule(
        r"\bNos?\.\s*\d+:(\d+)-([a-z]{2,3})-0*(\d+)(?:-([A-Z]))?",
        lambda m: "case number {} {} {}{}".format(
            m[1], _spell(m[2]), m[3], f" {m[4]}" if m[4] else ""
        ),
    ),
    _rule(
        r"\bRelease\s+Nos?\.\s*([\d–-]+)",
        lambda m: f"Release Number {_dashes_spoken(m[1])}",
    ),
    _rule(
        r"\bFile\s+Nos?\.\s*([A-Z]?[\d–-]+[\dA-Z-]*)",
        lambda m: f"File Number {_dashes_spoken(m[1])}",
    ),
    _rule(r"\bRIN\s*([\w–-]+)", lambda m: f"R I N {_dashes_spoken(m[1])}"),
    _rule(
        r"\bReg(?:ulation)?\.?\s*\(EU\)\s*(\d{4})/(\d+)",
        r"E U Regulation \1 slash \2",
    ),
    _rule(r"\b(\d{4})/(\d{1,4})\b(?!\s*(?:am|pm))", r"\1 slash \2"),
    _rule(r"\bArts?\.\s*(\d+)\((\d+)\)", r"Article \1, paragraph \2"),
    _rule(r"\bArt\.\s*(\d+)", r"Article \1"),
    _rule(r"\bArts\.\s*", "Articles "),
    _rule(
        r"\b(Annex|Title|Chapter|Part|Schedule|Recital|Phase)\s+([IVXLC]{1,5})\b",
        lambda m: f"{m[1]} {ROMAN.get(m[2], m[2])}",
    ),
    _rule(r"\bS\.?\s?B\.?\s+(\d+[-–]\d+)", r"Senate Bill \1"),
    _rule(r"\bH\.?\s?B\.?\s+(\d+[-–]\d+)", r"House Bill \1"),
    _rule(r"\bH\.\s*R\.\s*(\d+)", r"House Bill \1"),
    _rule(r"\bS\.\s*(\d{3,5})\b", r"Senate Bill \1"),
    _rule(r"§§\s*", "sections "),
    _rule(r"§\s*", "section "),
    _rule(r"¶¶\s*", "paragraphs "),
    _rule(r"¶\s*", "paragraph "),
    _rule(r"\b(\d)(?:d|th|st|nd|rd)\s+Cir\.", lambda m: f"the {CIRCUITS[m[1]]} Circuit"),
    *(_rule(p, r) for p, r in COURTS.items()),
    _rule(r"(?<=[a-z’'\)])\s+v\.\s+(?=[A-Z])", " versus "),
    _rule(r"\bQ([1-4])\s+(\d{4})", lambda m: f"{QUARTERS[m[1]]} quarter of {m[2]}"),
)

# Level 2 and up. A neural voice reads most of these acceptably on its own, so
# expanding them buys clarity at the cost of sounding stilted.
ABBREVIATION_RULES: tuple[Rule, ...] = (
    # An abbreviation period followed by a capital was also ending a sentence.
    # Expanding it away merges two sentences, which costs the chunker a boundary
    # and the voice a pause. "Aug. Term" is the rarer reading; we accept it.
    _rule(
        r"\b(" + "|".join(MONTHS) + r")\.(?=\s+[A-Z])",
        lambda m: MONTHS[m[1]] + ".",
    ),
    _rule(
        r"\b(" + "|".join(MONTHS) + r")\.",
        lambda m: MONTHS[m[1]],
    ),
    *(_rule(p, r) for p, r in LATIN.items()),
    _rule(r"\b(\d+)\s*pp\.(?=\s+[A-Z“\"])", r"\1 pages."),
    _rule(r"\b(\d+)\s*pp\.", r"\1 pages"),
    _rule(r"\bpp\.\s*(\d+)\s*[-–]\s*(\d+)", r"pages \1 to \2"),
    _rule(r"\bpp\.", "pages"),
    _rule(r"\bp\.\s*(\d+)", r"page \1"),
    _rule(r"\bNos\.\s*", "numbers "),
    _rule(r"\bNo\.\s*", "number "),
    _rule(r"\bRel\.\s*", "release "),
    _rule(r"\bReg\.\s*", "regulation "),
    _rule(r"\bSecs?\.\s*", "section "),
    _rule(r"\bsee\s+also\b", "see also"),
)

NUMBER_RULES: tuple[Rule, ...] = (
    _rule(
        r"\$\s*([\d.,]+)\s*(bn|tn|[kmbt])\b",
        lambda m: f"{m[1]} {MAGNITUDES[m[2].lower()]} dollars",
    ),
    _rule(r"\$\s*([\d.,]+)", r"\1 dollars"),
    _rule(r"([\d.,]+)\s*%", r"\1 percent"),
    # ASCII arrows carry a leading hyphen the old character class left stranded,
    # which read aloud as "26 percent- to 18 percent".
    _rule(r"\s*(?:-{0,2}>|[→➔]+)\s*(?=[\d$])", " to "),
    _rule(r"\b([\d,]+)\s*\+", r"over \1"),
    _rule(r"\b(\d{4})\s*[–—]\s*(\d{4})\b", r"\1 to \2"),
    _rule(r"\b(\d+)\s*[–—]\s*(\d+)\b", r"\1 to \2"),
    _rule(r"\b(\d+)-state\b", r"\1 state"),
    _rule(r"\s*&\s*", " and "),
)


def strip_links(text: str) -> str:
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    out = re.sub(r"\[([^\]]+)\]\((?:https?|mailto)[^)]*\)", r"\1", out)
    out = re.sub(r"\[PDF\]\s*", "", out)
    out = re.sub(r"<https?://[^>]+>", "", out)
    # Stop before trailing punctuation: \S+ would eat the sentence's own full stop
    # and run it into the next one.
    out = re.sub(r"https?://\S+?(?=[.,;:!?'\")\]]*(?:\s|$))", "", out)
    out = re.sub(r"\bwww\.\S+?(?=[.,;:!?'\")\]]*(?:\s|$))", "", out)
    return re.sub(r"\S+@\S+\.\w+", "", out)


def dehyphenate(text: str) -> str:
    return re.sub(r"(\w)[-‐]\n\s*(\w)", r"\1\2", text)


def unwrap(text: str) -> str:
    """Rejoin hard-wrapped PDF lines. A speech engine treats every newline as a pause."""
    return re.sub(r"([^\n.!?:;\]\)”\"])\n(?=[a-z0-9(“\"’])", r"\1 ", text)


def drop_page_artifacts(text: str) -> str:
    lines = text.split("\n")
    kept = [
        line
        for line in lines
        if not re.fullmatch(r"\s*\d{1,4}\s*", line)
        and not re.fullmatch(r"\s*(?:Page\s+)?\d+\s+of\s+\d+\s*", line, re.IGNORECASE)
        and not re.fullmatch(r"\s*[-–—_=*]{3,}\s*", line)
    ]
    joined = "\n".join(kept)
    return re.sub(r"\.\d{1,3}(?=\s+[A-Z“])", ".", joined)


def expand_phrases(text: str) -> str:
    def sub(match: re.Match[str]) -> str:
        return PHRASES[match[0]]

    if not PHRASES:
        return text
    pattern = r"\b(" + "|".join(map(re.escape, PHRASES)) + r")\b"
    return re.sub(pattern, sub, text)


def _apply(rules: Sequence[Rule], text: str) -> str:
    return reduce(lambda acc, rule: rule[0].sub(rule[1], acc), rules, text)


def expand_citations(text: str, level: int = 3) -> str:
    rules = CORE_RULES + (ABBREVIATION_RULES if level >= STANDARD else ())
    return _apply(rules, text)


def expand_numbers(text: str) -> str:
    return _apply(NUMBER_RULES, text)


def _is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) > 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7


def spell_acronyms(text: str) -> str:
    token = re.compile(r"(?<![.\w])([A-Z][A-Z0-9&]{1,5})\b")

    def sub(match: re.Match[str]) -> str:
        word = match[1]
        if word in WORD_ACRONYMS or re.fullmatch(r"[IVXLC]+", word):
            return word
        if not any(c.isalpha() for c in word) or word.isdigit():
            return word
        return _spell(word)

    return "\n".join(
        line if _is_heading(line) else token.sub(sub, line) for line in text.split("\n")
    )


def collapse_space(text: str) -> str:
    out = re.sub(r"[ \t]+", " ", text)
    # Removing a URL or a bracketed cite leaves empty delimiters and orphaned space
    # in front of the punctuation that followed it.
    out = re.sub(r"\(\s*\)|\[\s*\]|\"\s*\"|'\s*'", "", out)
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" ?\n ?", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


STRUCTURAL: tuple[Callable[[str], str], ...] = (
    strip_links,
    dehyphenate,
    drop_page_artifacts,
    unwrap,
)


def pipeline_for(level: int) -> tuple[Callable[[str], str], ...]:
    """Rule groups by how much help the voice needs.

    A neural voice says "SEC" and "et al." correctly, so spelling them out only
    makes it stilted. A weak voice needs every one of them expanded. The level
    picks which groups run; the rules themselves never change.
    """
    steps: list[Callable[[str], str]] = list(STRUCTURAL)
    if level >= STANDARD:
        steps.append(expand_phrases)
    steps.append(lambda text: expand_citations(text, level))
    steps.append(expand_numbers)
    if level >= FULL:
        steps.append(spell_acronyms)
    steps.append(collapse_space)
    return tuple(steps)


def normalize(
    text: str,
    level: int = FULL,
    pipeline: Sequence[Callable[[str], str]] | None = None,
) -> str:
    steps = pipeline if pipeline is not None else pipeline_for(level)
    return reduce(lambda acc, step: step(acc), steps, text)


# Kept so callers that passed the old module-level pipeline keep working.
PIPELINE: tuple[Callable[[str], str], ...] = pipeline_for(FULL)
