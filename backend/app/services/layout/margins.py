import re
from typing import Sequence
from .geometry import normalize_bbox

FOOTNOTE_PATTERN = re.compile(
    r"^(\d{1,3}|[\*†‡§#])[\s\.\)]+[A-Z\"\'\(\[]",
)

MARGINALIA_PATTERN = re.compile(
    r"^(?:cf\.|see|ibid\.|psalm|john|matt|mark|luke|rom|cor|gen|ex|deut|v\.|vv\.|p\.|pp\.|ch\.|vol\.|bk\.)\s+",
    re.IGNORECASE,
)


def is_header_footer(bbox: Sequence[float], text: str) -> bool:
    """Return True if block is in the extreme top or bottom band and not a footnote."""
    y0, y1 = bbox[1], bbox[3]
    # Extreme top (running header)
    if y1 <= 0.08:
        return True
    # Extreme bottom (folio / page number)
    if y0 >= 0.93 and not FOOTNOTE_PATTERN.match(text.strip()):
        return True
    return False


def is_footnote(bbox: Sequence[float], text: str) -> bool:
    """Return True if block is located in the bottom third and begins with footnote apparatus markers."""
    y0 = bbox[1]
    clean_text = text.strip()
    if y0 >= 0.70 and bool(FOOTNOTE_PATTERN.match(clean_text)):
        return True
    return False


def compute_body_column_bounds(
    blocks: Sequence[dict],
) -> tuple[float, float]:
    """
    Compute dominant body column boundaries [Xmin, Xmax] across text blocks
    excluding extreme headers and footers.
    """
    valid_blocks = [
        b for b in blocks
        if not is_header_footer(b["bbox"], b.get("text", ""))
        and len(b.get("text", "").strip()) > 30
    ]
    if not valid_blocks:
        return (0.15, 0.85)

    # Median or 10th/90th percentile of left and right borders
    lefts = sorted(b["bbox"][0] for b in valid_blocks)
    rights = sorted(b["bbox"][2] for b in valid_blocks)

    xmin = lefts[len(lefts) // 5] if len(lefts) >= 5 else lefts[0]
    xmax = rights[(len(rights) * 4) // 5] if len(rights) >= 5 else rights[-1]

    return (max(0.05, xmin), min(0.95, xmax))


def is_marginalia(
    bbox: Sequence[float],
    text: str,
    page_number: int,
    body_xmin: float,
    body_xmax: float,
) -> bool:
    """
    Classify if a block sits in the outer page margin.
    Verso (Even pages): Outer margin is on the left (x1 < body_xmin).
    Recto (Odd pages): Outer margin is on the right (x0 > body_xmax).
    """
    clean_text = text.strip()
    x0, y0, x1, y1 = bbox

    # Don't tag header/footers as marginalia
    if is_header_footer(bbox, text):
        return False

    # Check textual citation pattern
    has_ref_pattern = bool(MARGINALIA_PATTERN.match(clean_text))

    is_even = (page_number % 2 == 0)

    if is_even:
        # Verso page: Outer margin is on the left
        if x1 <= body_xmin + 0.015 or (x1 <= 0.28 and x0 < 0.15):
            return True
        if has_ref_pattern and x1 <= body_xmin + 0.05:
            return True
    else:
        # Recto page: Outer margin is on the right
        if x0 >= body_xmax - 0.015 or (x0 >= 0.72 and x1 > 0.85):
            return True
        if has_ref_pattern and x0 >= body_xmax - 0.05:
            return True

    # General fallback for narrow side-column blocks containing reference patterns
    if has_ref_pattern and (x1 - x0) <= 0.25 and (x1 <= 0.32 or x0 >= 0.68):
        return True

    return False
