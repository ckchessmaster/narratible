import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.services.layout.models import LayoutBlock, PageLayout
from app.services.layout.geometry import (
    normalize_bbox,
    denormalize_bbox,
    recursive_xy_cut,
    bbox_centroid,
    bbox_contains,
)
from app.services.layout.margins import (
    is_header_footer,
    is_footnote,
    is_marginalia,
    compute_body_column_bounds,
)


def test_geometry_normalization():
    norm = normalize_bbox([100, 200, 300, 400], 1000, 1000)
    assert norm == [0.1, 0.2, 0.3, 0.4]

    denorm = denormalize_bbox(norm, 1000, 1000)
    assert denorm == [100.0, 200.0, 300.0, 400.0]


def test_recursive_xy_cut_column_sorting():
    # Two columns: Column 1 on left (x: 0.1->0.4), Column 2 on right (x: 0.6->0.9)
    # Give them in interleaved vertical order
    blocks = [
        {"id": "col2_top", "bbox": [0.6, 0.1, 0.9, 0.3]},
        {"id": "col1_top", "bbox": [0.1, 0.1, 0.4, 0.3]},
        {"id": "col2_bot", "bbox": [0.6, 0.5, 0.9, 0.8]},
        {"id": "col1_bot", "bbox": [0.1, 0.5, 0.4, 0.8]},
    ]
    sorted_blocks = recursive_xy_cut(blocks, bbox_key="bbox")
    ordered_ids = [b["id"] for b in sorted_blocks]
    # In natural reading order, left column should come first, then right column!
    assert ordered_ids == ["col1_top", "col1_bot", "col2_top", "col2_bot"]


def test_margins_header_footer():
    # Header
    assert is_header_footer([0.1, 0.02, 0.9, 0.05], "44 TERTULLIAN AGAINST PRAXEAS")
    # Body
    assert not is_header_footer([0.1, 0.20, 0.9, 0.60], "Standard narrative text here.")
    # Folio / Page number at bottom
    assert is_header_footer([0.45, 0.95, 0.55, 0.98], "44")


def test_margins_verso_recto_marginalia():
    xmin, xmax = 0.25, 0.85
    # Even page (Verso): Outer margin is on LEFT
    assert is_marginalia([0.05, 0.2, 0.22, 0.4], "cf. John viii. 26", page_number=44, body_xmin=xmin, body_xmax=xmax)
    # Odd page (Recto): Outer margin is on RIGHT
    assert is_marginalia([0.88, 0.2, 0.98, 0.4], "cf. John viii. 26", page_number=45, body_xmin=xmin, body_xmax=xmax)
    # Inside body should NOT be marginalia
    assert not is_marginalia([0.30, 0.2, 0.80, 0.4], "Regular body text", page_number=44, body_xmin=xmin, body_xmax=xmax)


def test_footnote_detection():
    # Footnote with number marker in bottom region
    assert is_footnote([0.25, 0.85, 0.90, 0.92], "1 For structus = instructus, cf. Hoppe")
    assert is_footnote([0.25, 0.90, 0.90, 0.95], "* See Harnack, Dogmengeschichte")
    # Non-footnote text in middle of page
    assert not is_footnote([0.25, 0.30, 0.90, 0.40], "1 For structus is not a footnote here")


def test_analyze_page_layout_pipeline():
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # 1. Header
    page.insert_text(fitz.Point(50, 40), "CHAPTER VIII. TERTULLIAN")

    # 2. Left margin (Verso page = 44)
    page.insert_text(fitz.Point(30, 150), "cf. John viii. 26")

    # 3. Main body column
    page.insert_text(fitz.Point(180, 150), "Now if you think that this constitutes two Gods, you must consider.")
    page.insert_text(fitz.Point(180, 250), "Whatever things the Father commanded Him to do, these He also spoke.")

    # 4. Footnote
    page.insert_text(fitz.Point(180, 720), "1 For structus = instructus, cf. Hoppe.")

    # 5. Folio
    page.insert_text(fitz.Point(300, 780), "44")

    layout = analyze_page_layout(page, page_number=44)
    assert layout.page_number == 44
    assert len(layout.blocks) >= 4

    types = {b.type for b in layout.blocks}
    assert "header_footer" in types
    assert "marginalia" in types
    assert "body" in types
    assert "footnote" in types

    # Check muting and order
    body_blocks = [b for b in layout.blocks if b.type == "body"]
    assert len(body_blocks) >= 1
    assert body_blocks[0].audio_muted is False
    assert body_blocks[0].order == 1

    marginalia_blocks = [b for b in layout.blocks if b.type == "marginalia"]
    assert marginalia_blocks[0].audio_muted is True
    # Should be bound to body block
    assert marginalia_blocks[0].associated_para_id is not None


def test_academic_page_with_scripture_marginalia_and_footnotes():
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # 1. Running Header: 102 TERTULLIAN AGAINST PRAXEAS [26
    page.insert_text(fitz.Point(60, 45), "102")
    page.insert_text(fitz.Point(180, 45), "TERTULLIAN AGAINST PRAXEAS")
    page.insert_text(fitz.Point(540, 45), "[26")

    # 2. Left-hand Margin references
    page.insert_text(fitz.Point(40, 220), "Luke i. 35")
    page.insert_text(fitz.Point(40, 360), "Ibid.")
    page.insert_text(fitz.Point(40, 390), "49.")
    page.insert_text(fitz.Point(40, 430), "cf. Mark i. 24, etc.")

    # 3. Main body text
    page.insert_text(fitz.Point(150, 100), "as he himself also is from whom it comes and whose it is.")
    page.insert_text(fitz.Point(150, 200), "portion of the whole, much more the power of the Most High.")
    page.insert_text(fitz.Point(150, 300), "stances, but accidental attributes of each substance.")
    page.insert_text(fitz.Point(150, 400), "Father's house? Satan, also, in his trials of Him.")
    page.insert_text(fitz.Point(150, 500), "Himself worships the Father. When recognised by Peter as God's Christ.")

    # 4. Scholarly footnotes apparatus
    page.insert_text(fitz.Point(150, 680), "1 Tertullian's view is in error here, cf. c. 28, etc. and d'Alès, p. 84.")
    page.insert_text(fitz.Point(150, 710), "2 hactenus . . . qua: an excellent instance of the original force of hactenus.")

    layout = analyze_page_layout(page, page_number=26)

    # 1. Body should be consolidated into unified reading macrozone
    body_blocks = [b for b in layout.blocks if b.type == "body"]
    assert len(body_blocks) == 1
    assert "as he himself also is" in body_blocks[0].text
    assert "Himself worships the Father" in body_blocks[0].text
    assert body_blocks[0].order == 1

    # 2. Marginalia should be consolidated into unified margin macrozone
    marginalia_blocks = [b for b in layout.blocks if b.type == "marginalia"]
    assert len(marginalia_blocks) == 1
    assert "Luke i. 35" in marginalia_blocks[0].text
    assert "Ibid." in marginalia_blocks[0].text
    assert marginalia_blocks[0].audio_muted is True

    # 3. Footnotes should be consolidated into unified scholarly apparatus macrozone
    footnote_blocks = [b for b in layout.blocks if b.type == "footnote"]
    assert len(footnote_blocks) == 1
    assert "Tertullian's view is in error" in footnote_blocks[0].text
    assert "hactenus" in footnote_blocks[0].text
    assert footnote_blocks[0].audio_muted is True

    # 4. Running Header should be consolidated into a single header block
    header_blocks = [b for b in layout.blocks if b.type == "header_footer"]
    assert len(header_blocks) == 1
    assert "TERTULLIAN AGAINST PRAXEAS" in header_blocks[0].text
    assert header_blocks[0].audio_muted is True
