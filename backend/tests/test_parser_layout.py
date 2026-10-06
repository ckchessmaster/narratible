"""Unit tests for parser layout assembly heuristics.

Runnable with pytest or directly: ``python tests/test_parser_layout.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import parser  # noqa: E402
from app.parser import _assemble_chapters_from_blocks, extract_pdf_metadata  # noqa: E402


def test_extract_pdf_metadata_uses_supplied_front_matter_without_page_text(monkeypatch, tmp_path):
    class FakeDoc:
        metadata = {"title": "PDF Title", "author": "PDF Author"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __len__(self):
            return 4

        def __getitem__(self, index):
            raise AssertionError("page text should not be read when front matter is supplied")

    monkeypatch.setattr(parser.fitz, "open", lambda path: FakeDoc())

    metadata, front_matter = extract_pdf_metadata(
        tmp_path / "book.pdf",
        front_matter_text="ISBN 978-1-234-56789-7\nLanguage: en",
    )

    assert metadata["title"] == "PDF Title"
    assert metadata["author"] == "PDF Author"
    assert metadata["isbn"] == "978-1-234-56789-7"
    assert metadata["language"] == "en"
    assert front_matter.startswith("ISBN")


def test_small_attribution_blocks_are_preserved():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "Body before.", "size": 10.0, "page": 0},
            {"text": "C. S. LEWIS", "size": 6.0, "page": 0},
            {"text": "Till We Have Faces1", "size": 6.0, "page": 0},
            {"text": "Body after.", "size": 10.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "Body before." in raw_text
    assert "C. S. LEWIS" in raw_text
    assert "Till We Have Faces1" in raw_text
    assert "Body after." in raw_text


def test_small_letter_spaced_attribution_blocks_are_preserved():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "Body before.", "size": 10.0, "page": 0},
            {"text": "C . S . L E W I S", "size": 6.0, "page": 0},
            {"text": "Till We Have Faces", "size": 6.0, "page": 0},
            {"text": "C S L E W I S", "size": 6.0, "page": 0},
            {"text": "Surprised by Joy", "size": 6.0, "page": 0},
            {"text": "Body after.", "size": 10.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "C . S . L E W I S" in raw_text
    assert "Till We Have Faces" in raw_text
    assert "C S L E W I S" in raw_text
    assert "Surprised by Joy" in raw_text


def test_small_combined_attribution_and_source_block_is_preserved():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "Body before.", "size": 10.0, "page": 0},
            {"text": "C . S . L E W I S\nTill We Have Faces1", "size": 6.0, "page": 0},
            {"text": "Body after.", "size": 10.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "C . S . L E W I S" in raw_text
    assert "Till We Have Faces1" in raw_text


def test_drop_cap_initial_blocks_are_preserved():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "C", "size": 30.0, "page": 0},
            {"text": "hristian Hedonism begins here.", "size": 10.0, "page": 0},
            {"text": "I", "size": 30.0, "page": 0},
            {"text": "n this book I will use many words.", "size": 10.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "C" in raw_text
    assert "hristian Hedonism" in raw_text
    assert "I" in raw_text
    assert "n this book" in raw_text


def test_small_scripture_reference_blocks_are_preserved():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "O God, you are my God;", "size": 10.0, "page": 0},
            {"text": "PSALM 63:1", "size": 6.0, "page": 0},
            {"text": "P S A L M 4 3 : 4", "size": 6.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "PSALM 63:1" in raw_text
    assert "P S A L M 4 3 : 4" in raw_text


def test_small_ordinary_footnote_blocks_are_still_skipped():
    result = _assemble_chapters_from_blocks(
        [[
            {"text": "Body before.", "size": 10.0, "page": 0},
            {"text": "1 This is a small footnote.", "size": 6.0, "page": 0},
            {"text": "Body after.", "size": 10.0, "page": 0},
        ]],
        median_size=10.0,
    )
    raw_text = result["raw_text"]
    assert "Body before." in raw_text
    assert "Body after." in raw_text
    assert "small footnote" not in raw_text


def test_detect_printed_toc_and_folio_calibration():
    import pymupdf as fitz
    from app.parser import _detect_printed_toc

    doc = fitz.open()

    # Sheet 1: Cover/Front matter
    p0 = doc.new_page(width=400, height=600)
    p0.insert_text(fitz.Point(50, 100), "A Great Treatise on Economics")

    # Sheet 2: Printed Table of Contents
    p1 = doc.new_page(width=400, height=600)
    p1.insert_text(fitz.Point(50, 50), "Contents")
    p1.insert_text(fitz.Point(50, 100), "Introduction ........................ 1")
    p1.insert_text(fitz.Point(50, 130), "Supply and Demand .................. 10")
    p1.insert_text(fitz.Point(50, 160), "Market Equilibrium ................. 25")

    # Sheets 3..35: Content with printed page numbers in header
    # Printed page 1 starts on Sheet 3 (offset = sheet_index_1based - printed_page = 3 - 1 = +2)
    for printed_pg in range(1, 30):
        p = doc.new_page(width=400, height=600)
        # Header with printed page number
        p.insert_text(fitz.Point(350, 30), str(printed_pg))
        if printed_pg == 1:
            p.insert_text(fitz.Point(50, 60), "Introduction")
            p.insert_text(fitz.Point(50, 100), "Welcome to this treatise on economic foundations.")
        elif printed_pg == 10:
            p.insert_text(fitz.Point(50, 60), "Supply and Demand")
            p.insert_text(fitz.Point(50, 100), "The law of supply and demand dictates the distribution.")
        elif printed_pg == 25:
            p.insert_text(fitz.Point(50, 60), "Market Equilibrium")
            p.insert_text(fitz.Point(50, 100), "When buyers and sellers reach clearing prices.")
        else:
            p.insert_text(fitz.Point(50, 100), f"Body paragraph content for page {printed_pg}.")

    bookmarks = _detect_printed_toc(doc)
    assert bookmarks is not None
    assert len(bookmarks) == 3

    # Check that entries match and sheet numbers are calibrated to physical sheets
    assert bookmarks[0][1] == "Introduction"
    assert bookmarks[0][2] == 3  # Physical Sheet 3

    assert bookmarks[1][1] == "Supply and Demand"
    assert bookmarks[1][2] == 12  # Physical Sheet 12 (10 + 2)

    assert bookmarks[2][1] == "Market Equilibrium"
    assert bookmarks[2][2] == 27  # Physical Sheet 27 (25 + 2)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    if failures:
        print(f"\n{failures} test(s) failed.")
        sys.exit(1)
    print("\nAll tests passed.")