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


def test_two_column_page_with_narrow_gutter_and_top_continuation():
    """Verify that a two-column page with tight gutters (~9pt) and text at top does not merge columns or cut off top text."""
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Column 1: x in [40, 260] (width 220)
    page.insert_text(fitz.Point(40, 45), "Airport Program text starting right at top.")
    page.insert_text(fitz.Point(40, 60), "civil airports throughout the country.")
    page.insert_text(fitz.Point(40, 100), "The Federal Aviation Act of 1958.")
    page.insert_text(fitz.Point(40, 150), "By mid-century, air traffic had increased.")

    # Column 2: x in [270, 500] (gutter between 260 and 270 is 10pt)
    page.insert_text(fitz.Point(270, 45), "the future. DOT began operation in 1967.")
    page.insert_text(fitz.Point(270, 60), "Federal Aviation Agency was renamed FAA.")
    page.insert_text(fitz.Point(270, 100), "The role of CAB was assumed by NTSB.")
    page.insert_text(fitz.Point(270, 150), "investigation of all transport accidents.")

    # Folio at bottom
    page.insert_text(fitz.Point(40, 750), "1-6")

    layout = analyze_page_layout(page, page_number=6)

    # 1. Body should be partitioned into TWO distinct ordered columns
    body_blocks = [b for b in layout.blocks if b.type == "body"]
    assert len(body_blocks) == 2, f"Expected 2 body blocks, got {len(body_blocks)}"

    assert body_blocks[0].order == 1
    assert "Airport Program" in body_blocks[0].text
    assert "By mid-century" in body_blocks[0].text
    assert "the future" not in body_blocks[0].text  # Col 1 must not interleave Col 2!

    assert body_blocks[1].order == 2
    assert "the future" in body_blocks[1].text
    assert "investigation of all transport accidents" in body_blocks[1].text

    # 2. Folio should be recognized as footer
    footers = [b for b in layout.blocks if b.type == "header_footer"]
    assert any("1-6" in f.text for f in footers)
    assert not any("Airport Program" in f.text for f in footers)  # Top text must NOT be a header!


def test_page_with_diagram_and_figure_caption():
    """Verify figure captions are identified and muted, while body columns remain readable."""
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Figure caption
    page.insert_text(fitz.Point(40, 300), "Figure 1-10. First Administrator of the FAA was General Quesada.")

    # Body narrative text
    page.insert_text(fitz.Point(40, 100), "Standard running narrative body paragraph text here.")
    page.insert_text(fitz.Point(40, 150), "More continuous body text explaining aviation history.")

    layout = analyze_page_layout(page, page_number=10)

    captions = [b for b in layout.blocks if b.type == "figure_caption"]
    assert len(captions) == 1
    assert "Figure 1-10" in captions[0].text
    assert captions[0].audio_muted is True

    bodies = [b for b in layout.blocks if b.type == "body"]
    assert len(bodies) == 1
    assert "Standard running narrative" in bodies[0].text
    assert "Figure 1-10" not in bodies[0].text  # Caption must NOT be in body text


def test_academic_running_header_with_folio_and_ocr_marginalia():
    """Verify that running headers with folios (e.g. '32 TERTULLIAN AGAINST PRAXEAS') and OCR'd margin notes are properly handled."""
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    # 304 x 481 small book page
    page = doc.new_page(width=304, height=481)

    # 1. Running Header line with folio
    page.insert_text(fitz.Point(66, 38), "32")
    page.insert_text(fitz.Point(100, 38), "TERTULLIAN AGAINST PRAXEAS")

    # 2. Main body column (x from 66 to 295)
    page.insert_text(fitz.Point(66, 60), "anxious to preach 1 \"monarchy,\" while even the")
    page.insert_text(fitz.Point(66, 75), "Greeks are unwilling to understand \"economy.\"")
    page.insert_text(fitz.Point(66, 90), "But I, if I have culled any knowledge of both")
    page.insert_text(fitz.Point(66, 105), "languages, know that \"monarchy\" means nothing")
    page.insert_text(fitz.Point(66, 350), "angels,\" as it is written: \"a hundred thousand")

    # 3. Left margin notes with OCR noise (x in [25, 58])
    page.insert_text(fitz.Point(27, 365), "c'. Matt.")
    page.insert_text(fitz.Point(27, 375), "xxvi. 53")

    # 4. Footnote apparatus at bottom (smaller size)
    page.insert_text(fitz.Point(66, 410), "1 Sonare = praedicare, significare.", fontsize=8)
    page.insert_text(fitz.Point(66, 422), "2 \"Agents.\" Personas in theology.", fontsize=8)

    layout = analyze_page_layout(page, page_number=36)

    # Header check
    headers = [b for b in layout.blocks if b.type == "header_footer"]
    assert len(headers) == 1
    assert "TERTULLIAN AGAINST PRAXEAS" in headers[0].text
    assert "32" in headers[0].text
    assert headers[0].audio_muted is True

    # Marginalia check: c'. Matt. and xxvi. 53 must NOT be swallowed into body
    marginalia = [b for b in layout.blocks if b.type == "marginalia"]
    assert len(marginalia) == 1
    assert "c'. Matt." in marginalia[0].text
    assert "xxvi." in marginalia[0].text
    assert marginalia[0].audio_muted is True

    # Body check: must NOT contain margin notes
    bodies = [b for b in layout.blocks if b.type == "body"]
    assert len(bodies) == 1
    assert "c'. Matt." not in bodies[0].text
    assert "anxious to preach" in bodies[0].text
    assert bodies[0].audio_muted is False

    # Footnote check
    footnotes = [b for b in layout.blocks if b.type == "footnote"]
    assert len(footnotes) == 1
    assert "Sonare = praedicare" in footnotes[0].text
    assert footnotes[0].audio_muted is True


def test_textbook_two_column_top_headings_not_marked_as_headers():
    """Verify that multi-column textbook pages starting with section headings at top do NOT mark headings as headers."""
    import pymupdf as fitz
    from app.services.layout.engine import analyze_page_layout

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Col 1 top: Section Title + paragraph
    page.insert_text(fitz.Point(40, 50), "Flight Standards District Office (FSDO)")
    page.insert_text(fitz.Point(40, 65), "The FAA has approximately 80 FSDOs. These")
    page.insert_text(fitz.Point(40, 80), "offices provide information and services.")

    # Col 2 top: Paragraph text
    page.insert_text(fitz.Point(320, 50), "Safety Team (FAASTeam) exemplifies this commitment.")
    page.insert_text(fitz.Point(320, 65), "The FAASTeam has replaced the Aviation Safety Program.")
    page.insert_text(fitz.Point(320, 80), "Its success led to its demise because causes were fixed.")

    # Bottom footer
    page.insert_text(fitz.Point(540, 760), "1-9")

    layout = analyze_page_layout(page, page_number=9)

    # There should be 2 body columns
    bodies = [b for b in layout.blocks if b.type == "body"]
    assert len(bodies) == 2

    # Column 1 should include the section heading at the top
    assert "Flight Standards District Office (FSDO)" in bodies[0].text
    assert "The FAA has approximately 80 FSDOs" in bodies[0].text

    # Column 2 should include its top text
    assert "Safety Team (FAASTeam)" in bodies[1].text

    # No spurious running header
    headers = [b for b in layout.blocks if b.type == "header_footer" and b.bbox[1] < 0.2]
    assert len(headers) == 0


