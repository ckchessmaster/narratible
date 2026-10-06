import re
from typing import Sequence
from .geometry import normalize_bbox

FOOTNOTE_PATTERN = re.compile(
    r"^(\d{1,3}|[\*†‡§#])(?:[\s\.\)]+|\s*)(?:[A-Za-z\"\'\(\[]|\b[a-z]{2,}\b)",
)

MARGINALIA_PATTERN = re.compile(
    r"^(?:(?:cf?['\.,]|~f|rf|tf|ef)\.?\s*|see\b|ibid\b|psalm\b|john\b|matt\b|mark\b|luke\b|rom\b|cor\b|gen\b|ex\b|deut\b|act\b|rev\b|gal\b|eph\b|phil\b|col\b|thess\b|tim\b|tit\b|heb\b|pet\b|jas\b|jude\b|dan\b|l>an\b|isa\b|jer\b|ezek\b|v\.|vv\.|p\.|pp\.|ch\.|vol\.|bk\.|[ivxlcdm]{1,8}\.|\b[1i]v\b|\d{1,3}\s*[\.:,]\s*\d+|\b[1-3]\b\s+[A-Za-z]{2,}|\d{1,3}\.)",
    re.IGNORECASE,
)


def is_header_footer(bbox: Sequence[float], text: str) -> bool:
    """Return True if block is in the extreme top or bottom band and matches header/footer traits."""
    y0, y1 = bbox[1], bbox[3]
    clean_text = text.strip()
    if not clean_text:
        return False

    # Extreme top (running header): must be short title, folio, or header pattern
    if y1 <= 0.10 or (y0 <= 0.08 and y1 <= 0.12):
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
        # Legitimate body paragraphs continuing from previous page have many words or start with lowercase
        is_continuation = clean_text[0].islower()
        is_prose_paragraph = len(clean_text) > 100 or len(clean_text.split()) > 14 or len(lines) > 2
        if not is_continuation and not is_prose_paragraph:
            return True
        return False

    # Extreme bottom (folio / page number)
    if y0 >= 0.92 and not is_footnote(bbox, text):
        # Folios are typically short (e.g. page numbers '1-6', '44')
        if len(clean_text) <= 35 or len(clean_text.split()) <= 6 or y0 >= 0.95:
            return True
    return False


def is_footnote(bbox: Sequence[float], text: str) -> bool:
    """Return True if block is located in the bottom third and begins with footnote apparatus markers."""
    y0 = bbox[1]
    clean_text = text.strip()
    if y0 >= 0.65 and bool(FOOTNOTE_PATTERN.match(clean_text)):
        return True
    return False


def compute_body_column_bounds(
    blocks: Sequence[dict],
) -> tuple[float, float]:
    """
    Compute dominant body column boundaries [Xmin, Xmax] across text blocks
    excluding extreme headers, footers, and marginalia.
    """
    valid_blocks = [
        b for b in blocks
        if not is_header_footer(b["bbox"], b.get("text", ""))
        and len(b.get("text", "").strip()) > 40
        and (b["bbox"][2] - b["bbox"][0]) >= 0.35  # Must be substantial width to be a body column
    ]
    if not valid_blocks:
        return (0.20, 0.85)

    # Median of left and right borders of substantial blocks
    lefts = sorted(b["bbox"][0] for b in valid_blocks)
    rights = sorted(b["bbox"][2] for b in valid_blocks)

    xmin = lefts[len(lefts) // 4] if len(lefts) >= 4 else lefts[0]
    xmax = rights[(len(rights) * 3) // 4] if len(rights) >= 4 else rights[-1]

    return (max(0.05, round(xmin, 4)), min(0.98, round(xmax, 4)))


def is_marginalia(
    bbox: Sequence[float],
    text: str,
    page_number: int,
    body_xmin: float,
    body_xmax: float,
) -> bool:
    """
    Classify if a block sits in the outer page margin.
    Verso (Even pages): Outer margin is typically on the left (x1 <= body_xmin).
    Recto (Odd pages): Outer margin is typically on the right (x0 >= body_xmax).
    However, many scans have margins on the left or both sides regardless of parity,
    or page numbering is offset from book folio.
    """
    clean_text = text.strip()
    x0, y0, x1, y1 = bbox

    # Don't tag header/footers as marginalia
    if is_header_footer(bbox, text):
        return False

    # Discard non-alphanumeric noise and isolated single-char specks
    has_alnum = any(c.isalnum() for c in clean_text)
    if not has_alnum or len(clean_text) <= 1:
        return False

    # Check textual citation pattern or multi-word note
    has_ref_pattern = bool(MARGINALIA_PATTERN.match(clean_text))
    has_multiple_words = len(clean_text.split()) >= 2 and any(c.isalpha() for c in clean_text)
    has_valid_content = has_ref_pattern or has_multiple_words
    if not has_valid_content:
        return False

    is_narrow = (x1 - x0) <= 0.28

    # 1. Definite left margin: Block is to the left of the body column
    if x1 <= body_xmin + 0.02:
        return True
    if has_ref_pattern and x1 <= body_xmin + 0.06:
        return True

    # 2. Definite right margin: Block is to the right of the body column
    if x0 >= body_xmax - 0.02:
        return True
    if has_ref_pattern and x0 >= body_xmax - 0.06:
        return True

    # 3. Outer boundary check in gutters
    if (x1 <= 0.28 and x0 < 0.18) or (x0 >= 0.72 and x1 > 0.82):
        return True

    # 4. Narrow margin notes containing reference patterns or short citation text in outer gutters
    if has_ref_pattern and is_narrow and (x1 <= 0.35 or x0 >= 0.65):
        return True

    return False
