"""Unit tests for parser layout assembly heuristics.

Runnable with pytest or directly: ``python tests/test_parser_layout.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import parser  # noqa: E402
from app.parser import _assemble_chapters_from_blocks, _classify_page_blocks, extract_pdf_metadata, extract_structured_from_pdf  # noqa: E402


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


def test_layout_note_blocks_are_stored_outside_chapter_text():
    blocks = [
        {"text": "Chapter One", "size": 18.0, "page": 0},
        {"text": "Main body text starts here and continues normally.", "size": 10.0, "page": 0},
        {
            "text": "1 This is a bottom footnote.",
            "size": 6.0,
            "page": 0,
            "role": "footnote",
            "note": {"type": "footnote", "text": "1 This is a bottom footnote.", "page": 1},
        },
        {
            "text": "cf. John vi. 38",
            "size": 6.0,
            "page": 0,
            "role": "margin",
            "note": {"type": "margin", "text": "cf. John vi. 38", "page": 1},
        },
    ]

    result = _assemble_chapters_from_blocks([blocks], median_size=10.0)

    chapter = result["chapters"][0]
    assert "Main body text" in chapter["raw_text"]
    assert "bottom footnote" not in chapter["raw_text"]
    assert "John vi" not in chapter["raw_text"]
    assert [note["type"] for note in chapter["notes"]] == ["footnote", "margin"]


def test_extended_note_detection_classifies_margin_notes_only_when_enabled():
    blocks = [
        {
            "text": "Main body text starts here and continues normally across the prose column.",
            "size": 10.0,
            "page": 0,
            "bbox": (140.0, 100.0, 500.0, 130.0),
            "page_width": 612.0,
            "page_height": 792.0,
        },
        {
            "text": "cf. John vi. 38",
            "size": 6.0,
            "page": 0,
            "bbox": (55.0, 120.0, 120.0, 150.0),
            "page_width": 612.0,
            "page_height": 792.0,
        },
    ]

    conservative = _classify_page_blocks(blocks, 10.0, extended_note_detection=False)
    extended = _classify_page_blocks(blocks, 10.0, extended_note_detection=True)

    assert conservative[1].get("role") is None
    assert extended[1]["role"] == "margin"
    assert extended[1]["note"]["type"] == "margin"


def test_extended_note_detection_removes_inline_margin_spans_from_tertuallian_fixture():
    pdf_path = Path(__file__).parent / "test-files" / "tertuallian.pdf"

    conservative = extract_structured_from_pdf(pdf_path, extended_note_detection=False)
    result = extract_structured_from_pdf(pdf_path, extended_note_detection=True)

    assert "Matt. iv. 3" in conservative["chapters"][0]["raw_text"]
    text = result["chapters"][0]["raw_text"]
    notes = result["chapters"][0]["notes"]
    note_text = " ".join(note["text"] for note in notes)
    assert "Matt. iv. 3" not in text
    assert "Matt. iv. 6" not in text
    assert "cf. John" not in text
    assert "cf 1 Cor." not in text
    assert "cf. 1 Cor." not in text
    assert "Matt. iv. 3" in note_text
    assert "Matt. iv. 6" in note_text
    assert "cf. Luke iv. 9-11" in note_text
    assert "cf. John" in note_text


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