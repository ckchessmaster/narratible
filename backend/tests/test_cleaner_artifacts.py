"""Unit tests for running header/footer cleanup.

Runnable with pytest or directly: ``python tests/test_cleaner_artifacts.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cleaner import regex_clean_text  # noqa: E402
from app.page_artifacts import remove_running_headers  # noqa: E402


def test_known_numbered_header_interrupting_sentence_is_removed_and_joined():
    text = (
        "Oh, taste and see\n\n"
        "16 When I Don\u2019t Desire GOD\n\n"
        "that the LORD is good!"
    )
    assert remove_running_headers(text, known_titles=["When I Don't Desire GOD"]) == (
        "Oh, taste and see that the LORD is good!"
    )


def test_repeated_numbered_headers_are_removed_without_known_title():
    text = (
        "First paragraph ends normally.\n\n"
        "15 When I Don't Desire GOD\n\n"
        "Next paragraph begins.\n\n"
        "16 When I Don't Desire GOD\n\n"
        "Final paragraph."
    )
    assert remove_running_headers(text) == (
        "First paragraph ends normally.\n\nNext paragraph begins.\n\nFinal paragraph."
    )


def test_trailing_page_number_header_is_removed():
    text = (
        "A sentence continues\n\n"
        "When I Don't Desire GOD 17\n\n"
        "because the thought was split."
    )
    assert remove_running_headers(text, known_titles=["When I Don't Desire GOD"]) == (
        "A sentence continues because the thought was split."
    )


def test_repeated_all_caps_book_title_is_removed():
    text = (
        "TERTULLIAN AGAINST PRAXEAS\n\n"
        "Body one.\n\n"
        "TERTULLIAN AGAINST PRAXEAS\n\n"
        "Body two."
    )
    assert remove_running_headers(text) == "Body one.\n\nBody two."


def test_standalone_page_numbers_are_removed():
    assert remove_running_headers("Text before.\n\n16\n\nText after.") == (
        "Text before.\n\nText after."
    )


def test_regex_clean_text_uses_running_header_cleanup():
    text = "Taste and see\n\n16 When I Don't Desire GOD\n\nthat the LORD is good."
    assert regex_clean_text(text, known_titles=["When I Don't Desire GOD"]) == (
        "Taste and see that the LORD is good."
    )


def test_numbered_footnote_and_scripture_citation_are_preserved():
    text = (
        "17 cf. Matt 13:25\n"
        "18 I.e. probably a reference to Tertullian himself."
    )
    assert remove_running_headers(text) == text


def test_real_chapter_heading_and_numbered_list_are_preserved():
    text = (
        "Chapter 16\n\n"
        "16 Reasons to Keep Reading\n\n"
        "1 First reason\n"
        "2 Second reason"
    )
    assert remove_running_headers(text) == text


def test_bibliography_page_ranges_are_preserved():
    text = "Hoppe, pp. 193-220\nJournal Theol. Studies, vol. iv. pp. 441 f."
    assert remove_running_headers(text) == text


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