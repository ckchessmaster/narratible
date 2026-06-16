"""Unit tests for running header/footer cleanup.

Runnable with pytest or directly: ``python tests/test_cleaner_artifacts.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cleaner import fix_soft_hyphenation, regex_clean_text  # noqa: E402
from app.page_artifacts import remove_running_headers  # noqa: E402
from app.parsing_modules import apply_modules, list_modules  # noqa: E402
from app.parsing_modules.prose_reflow import reflow_wrapped_prose  # noqa: E402


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


def test_repeated_author_attribution_lines_are_preserved():
    text = (
        "Quote one.\n\n"
        "C. S. LEWIS\n\n"
        "Till We Have Faces1\n\n"
        "Quote two.\n\n"
        "C. S. LEWIS\n\n"
        "Surprised by Joy2"
    )
    assert remove_running_headers(text) == text


def test_author_attribution_with_footnote_number_is_preserved():
    text = "Quote one.\n\nC. S. LEWIS 1\n\nQuote two.\n\nC. S. LEWIS 2"
    assert remove_running_headers(text) == text


def test_letter_spaced_author_attribution_lines_are_preserved():
    text = (
        "Quote one.\n\n"
        "C . S . L E W I S\n\n"
        "Till We Have Faces\n\n"
        "Quote two.\n\n"
        "C S L E W I S\n\n"
        "Surprised by Joy"
    )
    assert remove_running_headers(text) == text


def test_scripture_attribution_lines_are_preserved():
    text = (
        "O God, you are my God;\n\n"
        "earnestly I seek you;\n\n"
        "PSALM 63:1\n\n"
        "Then I will go to the altar of God,\n\n"
        "PSALM 43:4"
    )
    assert remove_running_headers(text) == text


def test_spaced_scripture_attribution_lines_are_preserved():
    text = "O God, you are my God;\n\nP S A L M 6 3 : 1\n\nThen I will go."
    assert remove_running_headers(text) == text


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


def test_soft_hyphen_split_with_space_is_joined():
    text = "Therefore let me say at the begin- ning that joy matters."
    assert fix_soft_hyphenation(text) == (
        "Therefore let me say at the beginning that joy matters."
    )


def test_remove_running_headers_embedded_page_numbers():
    from app.page_artifacts import remove_running_headers

    text = """Taking God’s Demand for Delight
Seriously
D

o these two things really go together? Fighting and joy? 

Why I Wrote This Book 35 The Call to Fight for Joy in God 35 the world, and people loved the darkness rather than the light because their deeds were evil” (John 3:19). Here the issue of salvation is loving or hating the light.

Why I Wrote This Book 37 The Call to Fight for Joy in God 37 you were called” (6:12). Faith is something that must be fought for, if it is to thrive and survive."""

    result = remove_running_headers(text)
    
    # We expect the text body lines to be preserved and fused.
    assert "Why I Wrote This Book" not in result
    assert "the world, and people loved the darkness" in result
    assert "you were called” (6:12). Faith is something" in result


def test_soft_hyphen_split_across_page_gap_is_joined():
    text = "The sweet-\n\nest thing in all my life has been the longing."
    assert fix_soft_hyphenation(text) == (
        "The sweetest thing in all my life has been the longing."
    )


def test_regex_clean_text_repairs_soft_hyphenation():
    text = "The sweet-\n\nest thing at the begin- ning was mercy."
    assert regex_clean_text(text) == "The sweetest thing at the beginning was mercy."


def test_inline_hyphenated_words_are_preserved():
    text = "This is a long-term commitment, not a short-term impulse."
    assert fix_soft_hyphenation(text) == text


def test_single_letter_drop_caps_are_not_removed_as_page_numbers():
    text = "C\n\nhristian Hedonism begins here.\n\nI\n\nn this book I will use words."
    assert regex_clean_text(text) == text


def test_prose_reflow_joins_drop_cap_initials_without_space():
    text = "C\n\nhristian Hedonism begins here.\n\nI\n\nn this book I will use words."
    assert apply_modules(regex_clean_text(text), ["prose_reflow"]) == (
        "Christian Hedonism begins here.\n\nIn this book I will use words."
    )


def test_prose_reflow_does_not_trap_drop_cap_after_subtitle_lines():
    text = "Discovering How Both and Neither\n\nIs the Goal\n\nI\n\nn this book begins."
    assert apply_modules(regex_clean_text(text), ["prose_reflow"]) == (
        "Discovering How Both and Neither Is the Goal\n\nIn this book begins."
    )


def test_wrapped_prose_single_newlines_are_reflowed():
    text = "One sentence spans\nmultiple visual lines\ndue to PDF width."
    assert reflow_wrapped_prose(text) == (
        "One sentence spans multiple visual lines due to PDF width."
    )


def test_fake_blank_line_wrapped_epigraph_prose_is_reflowed():
    text = (
        "It was when I was happiest that I longed most. . . . The sweet-\n\n"
        "est thing in all my life has been the longing . . . to find the place\n\n"
        "where all the beauty came from.\n\n"
        "C. S. LEWIS\n\n"
        "Till We Have Faces1"
    )
    cleaned = regex_clean_text(text)
    assert apply_modules(cleaned, ["prose_reflow"]) == (
        "It was when I was happiest that I longed most. . . . The sweetest thing "
        "in all my life has been the longing . . . to find the place where all "
        "the beauty came from.\n\n"
        "C. S. LEWIS\n\n"
        "Till We Have Faces1"
    )


def test_wrapped_prose_with_fake_blank_lines_is_reflowed():
    text = (
        "The very nature of Joy makes nonsense of our common distinc-\n\n"
        "tion between having and wanting. There, to have is to want and\n\n"
        "to want is to have. Thus, the moment mattered."
    )
    cleaned = regex_clean_text(text)
    assert apply_modules(cleaned, ["prose_reflow"]) == (
        "The very nature of Joy makes nonsense of our common distinction between "
        "having and wanting. There, to have is to want and to want is to have. "
        "Thus, the moment mattered."
    )


def test_psalm_verse_line_structure_is_preserved():
    text = (
        "O God, you are my God;\n\n"
        "earnestly I seek you;\n\n"
        "my soul thirsts for you;\n\n"
        "my flesh faints for you,\n\n"
        "as in a dry and weary land\n\n"
        "where there is no water.\n\n"
        "PSALM 63:1"
    )
    assert reflow_wrapped_prose(text) == (
        "O God, you are my God;\n"
        "earnestly I seek you;\n"
        "my soul thirsts for you;\n"
        "my flesh faints for you,\n"
        "as in a dry and weary land\n"
        "where there is no water.\n\n"
        "PSALM 63:1"
    )


def test_full_epigraph_and_scripture_attributions_survive_cleanup_flow():
    text = (
        "It was when I was happiest that I longed most. . . . The sweet-\n\n"
        "est thing in all my life has been the longing . . . to find the place\n\n"
        "where all the beauty came from.\n\n"
        "C. S. LEWIS\n\n"
        "Till We Have Faces1\n\n"
        "O God, you are my God;\n\n"
        "earnestly I seek you;\n\n"
        "my soul thirsts for you;\n\n"
        "PSALM 63:1"
    )
    cleaned = regex_clean_text(text)
    assert apply_modules(cleaned, ["prose_reflow"]) == (
        "It was when I was happiest that I longed most. . . . The sweetest thing "
        "in all my life has been the longing . . . to find the place where all "
        "the beauty came from.\n\n"
        "C. S. LEWIS\n\n"
        "Till We Have Faces1\n\n"
        "O God, you are my God;\n"
        "earnestly I seek you;\n"
        "my soul thirsts for you;\n\n"
        "PSALM 63:1"
    )


def test_numbered_lists_are_not_reflowed():
    text = "1. First item\n2. Second item\n3. Third item"
    assert reflow_wrapped_prose(text) == text


def test_prose_reflow_module_is_exposed_to_ui_metadata():
    modules = list_modules()
    ids = [module["id"] for module in modules]
    assert "prose_reflow" in ids
    prose = next(module for module in modules if module["id"] == "prose_reflow")
    assert prose["name"] == "Prose Reflow"
    assert "transform" not in prose


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