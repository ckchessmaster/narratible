"""Unit tests for parser layout assembly heuristics.

Runnable with pytest or directly: ``python tests/test_parser_layout.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parser import _assemble_chapters_from_blocks  # noqa: E402


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