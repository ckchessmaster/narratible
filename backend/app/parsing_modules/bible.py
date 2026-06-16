"""Bible parsing module.

Expands abbreviated scripture book names so they are read correctly by TTS
engines, e.g. ``Ps 1:4`` -> ``Psalms 1:4`` and ``Mat 5:9`` / ``Matt 5:9`` ->
``Matthew 5:9``.

This is a purely deterministic, offline transform — no LLM, API key, or GPU is
involved. To avoid mangling ordinary prose (for example the word "is" vs. the
book Isaiah), an abbreviation is only expanded when it is immediately followed
by a chapter:verse reference such as ``1:4`` or ``13:4-7``. The reference
portion itself is left untouched.
"""

import re

# Canonical book name -> list of accepted abbreviations (lowercase, no trailing
# period). Numbered books are listed with an arabic prefix (e.g. "1 cor"); the
# matcher also accepts the unspaced form ("1cor") automatically. Multiple
# abbreviations may map to the same book (e.g. "mat" and "matt" -> Matthew).
BOOKS: dict[str, list[str]] = {
    # ── Old Testament ──────────────────────────────────────────────────────
    "Genesis": ["gen", "ge", "gn"],
    "Exodus": ["exod", "exo", "ex"],
    "Leviticus": ["lev", "le", "lv"],
    "Numbers": ["num", "nu", "nm", "nb"],
    "Deuteronomy": ["deut", "deu", "dt"],
    "Joshua": ["josh", "jos", "jsh"],
    "Judges": ["judg", "jdg", "jdgs"],
    "Ruth": ["ruth", "rth", "ru"],
    "1 Samuel": ["1 sam", "1 sa", "1 sm", "i sam", "i samuel"],
    "2 Samuel": ["2 sam", "2 sa", "2 sm", "ii sam", "ii samuel"],
    "1 Kings": ["1 kings", "1 kgs", "1 ki", "i kgs", "i kings"],
    "2 Kings": ["2 kings", "2 kgs", "2 ki", "ii kgs", "ii kings"],
    "1 Chronicles": ["1 chron", "1 chr", "1 ch", "i chron", "i chronicles"],
    "2 Chronicles": ["2 chron", "2 chr", "2 ch", "ii chron", "ii chronicles"],
    "Ezra": ["ezra", "ezr"],
    "Nehemiah": ["neh", "ne"],
    "Esther": ["esth", "est", "es"],
    "Job": ["job", "jb"],
    "Psalms": ["ps", "psa", "pss", "psalm", "pslm", "psm"],
    "Proverbs": ["prov", "pro", "prv", "pr"],
    "Ecclesiastes": ["eccles", "eccl", "ecc", "ec", "qoh"],
    "Song of Solomon": [
        "song of songs", "song of sol", "song", "sos", "canticles", "cant",
    ],
    "Isaiah": ["isa", "is", "isai"],
    "Jeremiah": ["jer", "je", "jr"],
    "Lamentations": ["lam", "la"],
    "Ezekiel": ["ezek", "eze", "ezk"],
    "Daniel": ["dan", "da", "dn"],
    "Hosea": ["hos", "ho"],
    "Joel": ["joel", "jl"],
    "Amos": ["amos", "am"],
    "Obadiah": ["obad", "ob"],
    "Jonah": ["jonah", "jon", "jnh"],
    "Micah": ["mic", "mc"],
    "Nahum": ["nah", "na"],
    "Habakkuk": ["hab", "hb"],
    "Zephaniah": ["zeph", "zep", "zp"],
    "Haggai": ["hag", "hg"],
    "Zechariah": ["zech", "zec", "zc"],
    "Malachi": ["mal", "ml"],
    # ── New Testament ──────────────────────────────────────────────────────
    "Matthew": ["matt", "mat", "mt"],
    "Mark": ["mark", "mrk", "mk", "mr"],
    "Luke": ["luke", "luk", "lk"],
    "John": ["john", "jhn", "jn"],
    "Acts": ["acts", "act", "ac"],
    "Romans": ["rom", "ro", "rm"],
    "1 Corinthians": ["1 cor", "1 co", "i cor", "i corinthians"],
    "2 Corinthians": ["2 cor", "2 co", "ii cor", "ii corinthians"],
    "Galatians": ["gal", "ga"],
    "Ephesians": ["eph", "ephes"],
    "Philippians": ["phil", "php", "pp"],
    "Colossians": ["col", "cl"],
    "1 Thessalonians": ["1 thess", "1 thes", "1 th", "i thess", "i thessalonians"],
    "2 Thessalonians": ["2 thess", "2 thes", "2 th", "ii thess", "ii thessalonians"],
    "1 Timothy": ["1 tim", "1 ti", "i tim", "i timothy"],
    "2 Timothy": ["2 tim", "2 ti", "ii tim", "ii timothy"],
    "Titus": ["titus", "tit"],
    "Philemon": ["philem", "phlm", "phm", "pm"],
    "Hebrews": ["heb", "hebr"],
    "James": ["james", "jas", "jm"],
    "1 Peter": ["1 pet", "1 pe", "1 pt", "i pet", "i peter"],
    "2 Peter": ["2 pet", "2 pe", "2 pt", "ii pet", "ii peter"],
    "1 John": ["1 john", "1 jn", "1 jhn", "i john"],
    "2 John": ["2 john", "2 jn", "ii john"],
    "3 John": ["3 john", "3 jn", "iii john"],
    "Jude": ["jude", "jud"],
    "Revelation": ["rev", "re", "rv", "revelations"],
}


def _normalize(text: str) -> str:
    """Lowercase and strip all whitespace for whitespace-insensitive lookup.

    This lets both "1 cor" and "1cor" resolve to the same key.
    """
    return re.sub(r"\s+", "", text.strip().lower())


def _build_lookup(books: dict[str, list[str]]) -> dict[str, str]:
    """Map each normalized abbreviation to its canonical book name.

    The first definition wins so a curated abbreviation is never silently
    shadowed by a later book.
    """
    lookup: dict[str, str] = {}
    for canonical, abbrevs in books.items():
        for abbrev in abbrevs:
            lookup.setdefault(_normalize(abbrev), canonical)
    return lookup


_LOOKUP = _build_lookup(BOOKS)


def _build_book_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, abbrevs in BOOKS.items():
        lookup[_normalize(canonical)] = canonical
        for abbrev in abbrevs:
            lookup[_normalize(abbrev)] = canonical
    return lookup


_BOOK_LOOKUP = _build_book_lookup()


def _to_subpattern(abbrev: str) -> str:
    """Turn an abbreviation into a regex fragment that allows flexible spacing.

    Spaces become ``\\s*`` so both "1 cor" and "1cor" match.
    """
    return r"\s*".join(re.escape(part) for part in abbrev.split(" "))


# All original abbreviation strings (with their spaces), longest first so e.g.
# "song of songs" wins over "song".
_ABBREVS = sorted(
    (a for abbrevs in BOOKS.values() for a in abbrevs),
    key=len,
    reverse=True,
)
_ALTERNATION = "|".join(_to_subpattern(a) for a in _ABBREVS)

# Match a known abbreviation (with optional trailing period) only when it is
# immediately followed by a chapter:verse reference (e.g. " 1:4"). The reference
# is matched via look-ahead so it is preserved untouched in the output.
_PATTERN = re.compile(
    r"\b(" + _ALTERNATION + r")\.?(?=\s+\d+\s*:\s*\d+)",
    re.IGNORECASE,
)


def transform(text: str) -> str:
    """Expand abbreviated scripture book names to their canonical form."""

    def _replace(match: re.Match) -> str:
        return _LOOKUP.get(_normalize(match.group(1) or ""), match.group(0))

    return _PATTERN.sub(_replace, text)


def tts_transform(text: str, engine: str = "edge-tts") -> str:
    """Return Bible-reference text phrased for audio synthesis."""
    if engine not in {"kokoro", "f5-tts"}:
        return text

    text = transform(text)
    return expand_scripture_references(text, explicit_chapter=(engine == "f5-tts"))


def expand_scripture_references(text: str, explicit_chapter: bool = False) -> str:
    """Expand scripture chapter:verse references into spoken phrasing."""
    reference_pattern = re.compile(
        rf"\b(?P<book>{_book_pattern()})\.?\s+"
        r"(?P<chapter>\d{1,3})\s*:\s*"
        r"(?P<verses>\d{1,3}(?:\s*(?:[-\u2013\u2014]|,)\s*\d{1,3})*)",
        re.IGNORECASE,
    )

    def replace(match: re.Match) -> str:
        book = _BOOK_LOOKUP.get(_normalize(match.group("book") or ""), match.group("book").strip())
        chapter = match.group("chapter")
        verses = _speak_verses(match.group("verses"))
        if explicit_chapter:
            return f"{book} chapter {chapter}, {verses}"
        return f"{book} {chapter}, {verses}"

    return reference_pattern.sub(replace, text)


def _book_pattern() -> str:
    names = set(BOOKS.keys())
    for abbrevs in BOOKS.values():
        names.update(abbrevs)
    parts = sorted((_to_subpattern(name) for name in names), key=len, reverse=True)
    return "|".join(parts)


def _speak_verses(verses: str) -> str:
    normalized = re.sub(r"\s+", "", verses)
    if re.fullmatch(r"\d+", normalized):
        return f"verse {normalized}"

    range_match = re.fullmatch(r"(\d+)[-\u2013\u2014](\d+)", normalized)
    if range_match:
        start, end = range_match.groups()
        return f"verses {start} through {end}"

    comma_parts = re.fullmatch(r"\d+(?:,\d+)+", normalized)
    if comma_parts:
        parts = normalized.split(",")
        if len(parts) == 2:
            return f"verses {parts[0]} and {parts[1]}"
        return f"verses {', '.join(parts[:-1])}, and {parts[-1]}"

    return "verses " + normalized.replace("-", " through ")
