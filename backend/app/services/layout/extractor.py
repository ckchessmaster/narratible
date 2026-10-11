from typing import Sequence
import pymupdf as fitz
from .geometry import denormalize_bbox
from .models import LayoutBlock
from ...cleaner import fix_soft_hyphenation
from ...parsing_modules.prose_reflow import reflow_wrapped_prose, _looks_like_verse_lines


def extract_block_text(
    page: fitz.Page,
    normalized_bbox: Sequence[float],
    width: float,
    height: float,
) -> str:
    """
    Extract text strictly bounded within the given normalized bounding box
    using PyMuPDF clip rectangle extraction.
    """
    if width <= 0 or height <= 0:
        return ""

    x0, y0, x1, y1 = denormalize_bbox(normalized_bbox, width, height)
    # Ensure non-zero positive dimension
    if x1 <= x0 or y1 <= y0:
        return ""

    clip_rect = fitz.Rect(x0, y0, x1, y1)
    try:
        raw_text = page.get_text("text", clip=clip_rect) or ""
        return raw_text.strip()
    except Exception:
        return ""


def extract_layout_blocks_text(
    page: fitz.Page,
    blocks: list[LayoutBlock],
    width: float,
    height: float,
) -> list[LayoutBlock]:
    """
    Re-extract bounded text for each block in the layout using clip rectangles.
    Reflows wrapped lines and fixes soft hyphens for prose blocks while preserving verse stanzas.
    """
    updated_blocks: list[LayoutBlock] = []
    for b in blocks:
        txt = extract_block_text(page, b.bbox, width, height)
        # If extraction returned empty, keep previous text if available
        raw = txt if txt else b.text
        if b.format == "verse" or (b.format != "prose" and _looks_like_verse_lines(raw.splitlines())):
            final_text = raw.strip()
            fmt = "verse"
        else:
            final_text = reflow_wrapped_prose(fix_soft_hyphenation(raw)).strip()
            fmt = b.format
        updated_blocks.append(
            b.model_copy(update={"text": final_text, "format": fmt})
        )
    return updated_blocks
