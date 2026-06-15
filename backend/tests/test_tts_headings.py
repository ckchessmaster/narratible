"""Unit tests for chapter-heading composition in the TTS pipeline.

Runnable with pytest or directly: ``python tests/test_tts_headings.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tts import compose_tts_text  # noqa: E402


def test_disabled_returns_body_only():
    assert compose_tts_text("Chapter 1", "Once upon a time.", read_headings=False) == "Once upon a time."


def test_empty_title_returns_body_only():
    assert compose_tts_text("", "Once upon a time.", read_headings=True) == "Once upon a time."
    assert compose_tts_text("   ", "Once upon a time.", read_headings=True) == "Once upon a time."


def test_heading_prepended_with_pause():
    assert compose_tts_text("Chapter 1", "Once upon a time.", read_headings=True) == (
        "Chapter 1.\n\nOnce upon a time."
    )


def test_existing_terminal_punctuation_preserved():
    assert compose_tts_text("Chapter 1.", "Once upon a time.", read_headings=True) == (
        "Chapter 1.\n\nOnce upon a time."
    )
    assert compose_tts_text("Why?", "Because.", read_headings=True) == "Why?\n\nBecause."


def test_body_already_starts_with_title_not_duplicated():
    body = "Chapter 1.  \nMANIFOLD are the ways."
    assert compose_tts_text("Chapter 1.", body, read_headings=True) == body


def test_dedup_is_case_and_whitespace_insensitive():
    body = "chapter   1\nThe story begins."
    assert compose_tts_text("Chapter 1", body, read_headings=True) == body


def test_partial_match_still_prepends():
    # Title is not a prefix of the body, so it must be spoken.
    body = "A long time ago in a galaxy far away."
    assert compose_tts_text("Chapter 1", body, read_headings=True) == (
        "Chapter 1.\n\nA long time ago in a galaxy far away."
    )


def test_empty_body_returns_heading_only():
    assert compose_tts_text("Chapter 1", "", read_headings=True) == "Chapter 1."
    assert compose_tts_text("Chapter 1", "   ", read_headings=True) == "Chapter 1."


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
