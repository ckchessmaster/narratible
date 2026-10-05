"""Intelligent Layout Engine, Semantic Block Zoning & Academic PDF Parsing.

Provides spatial block classification (body, marginalia, footnote, callout,
figure_caption, header_footer), Recursive XY-Cut column sorting, Verso/Recto
outer margin filtering, and clipping text extraction.
"""

from .models import (
    BlockType,
    LayoutBlock,
    PageLayout,
    LayoutUpdateRequest,
    LayoutPropagateRequest,
    VisionExtractRequest,
)
from .engine import analyze_page_layout, extract_block_text

__all__ = [
    "BlockType",
    "LayoutBlock",
    "PageLayout",
    "LayoutUpdateRequest",
    "LayoutPropagateRequest",
    "VisionExtractRequest",
    "analyze_page_layout",
    "extract_block_text",
]
