"""Unit tests for audio-only TTS text preparation.

Runnable with pytest or directly: ``python tests/test_tts_text.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tts_text import prepare_text_for_tts, segment_text_for_tts  # noqa: E402


def test_local_expands_scripture_range_and_etc():
    assert prepare_text_for_tts(
        "Matthew 10:14-15 says some stuff etc.",
        "kokoro",
        enabled_modules=["bible"],
    ) == "Matthew 10, verses 14 through 15 says some stuff et cetera."


def test_edge_keeps_service_side_normalization_available():
    assert prepare_text_for_tts(
        "Matthew 10:14-15 says some stuff etc.", "edge-tts"
    ) == "Matthew 10:14-15 says some stuff etc."


def test_f5_applies_narratible_pronunciation_hint_only_to_f5():
    assert prepare_text_for_tts("Welcome to narratible.", "f5-tts") == "Welcome to narratable."
    assert prepare_text_for_tts("Welcome to narratible.", "kokoro") == "Welcome to narratible."
    assert prepare_text_for_tts("Welcome to narratible.", "edge-tts") == "Welcome to narratible."


def test_scripture_book_abbreviation_and_single_verse_expand():
    assert prepare_text_for_tts(
        "Ps 1:4", "f5-tts", enabled_modules=["bible"]
    ) == "Psalms chapter 1, verse 4"


def test_scripture_does_not_expand_when_bible_module_disabled():
    assert prepare_text_for_tts("Ps 1:4", "f5-tts") == "Ps 1:4"


def test_comma_separated_verses_expand():
    assert prepare_text_for_tts(
        "Matthew 10:14,15", "kokoro", enabled_modules=["bible"]
    ) == (
        "Matthew 10, verses 14 and 15"
    )


def test_f5_normalizes_ligature_and_uses_enabled_bible_tts_transform():
    text = (
        "O God, you are my God;\n"
        "earnestly I seek you;\n"
        "my soul thirsts for you;\n"
        "my ﬂesh faints for you,\n"
        "as in a dry and weary land\n"
        "where there is no water.\n\n"
        "Psalms 63:1"
    )

    prepared = prepare_text_for_tts(text, "f5-tts", enabled_modules=["bible"])

    assert "my flesh faints for you" in prepared
    assert "ﬂ" not in prepared
    assert "Psalms chapter 63, verse 1" in prepared


def test_f5_ligature_normalization_is_not_module_gated():
    text = "my ﬂesh faints for you.\n\nPsalms 63:1"

    prepared = prepare_text_for_tts(text, "f5-tts")

    assert "my flesh faints for you" in prepared
    assert "ﬂ" not in prepared
    assert "Psalms 63:1" in prepared
    assert "Psalms chapter 63" not in prepared


def test_units_expand_in_numeric_context():
    assert prepare_text_for_tts("The car traveled 55 mph.", "kokoro") == (
        "The car traveled 55 miles per hour."
    )
    assert prepare_text_for_tts("Battery is 25%.", "f5-tts") == "Battery is 25 percent."


def test_false_positive_avoidance_for_common_text():
    text = (
        "Dr. Smith measured 3.14. Visit https://example.com/APIv1. "
        "Email a.b@example.com."
    )
    assert prepare_text_for_tts(text, "kokoro") == text


def test_footnotes_are_removed_for_all_engines():
    text = "Main text.[^1]\n\n[^1]: A note that should not be read."
    assert prepare_text_for_tts(text, "edge-tts") == "Main text."
    assert prepare_text_for_tts(text, "kokoro") == "Main text."


def test_local_segmentation_preserves_heading_pause():
    segments = segment_text_for_tts("Chapter 1.\n\nFirst sentence. Second sentence.", "kokoro")
    assert [segment.text for segment in segments] == [
        "Chapter 1.",
        "First sentence.",
        "Second sentence.",
    ]
    assert segments[0].pause_after_ms > segments[1].pause_after_ms > segments[2].pause_after_ms


def test_f5_segments_long_text():
    long_sentence = " ".join(["word"] * 120) + "."
    segments = segment_text_for_tts(long_sentence, "f5-tts")
    assert len(segments) > 1
    assert all(len(segment.text) <= 420 for segment in segments)


def test_f5_merges_short_preview_sentences_into_one_generation():
    text = (
        "The main topic of the doctrinal section of this letter is the free grace of God "
        "in saving people through Christ Jesus; especially as it appears in the doctrine "
        "of justification by faith alone. To show this doctrine more clearly and explain "
        "why it is true, the apostle first establishes this point: that no living person "
        "can be justified by the actions of the law."
    )

    segments = segment_text_for_tts(text, "f5-tts")

    assert len(segments) == 1
    assert segments[0].text == text
    assert segments[0].pause_after_ms == 0


def test_f5_merges_short_spoken_scripture_reference_segment():
    text = (
        "O God, you are my God;\n"
        "earnestly I seek you;\n"
        "my soul thirsts for you;\n"
        "my ﬂesh faints for you,\n"
        "as in a dry and weary land\n"
        "where there is no water.\n\n"
        "Psalms 63:1"
    )
    prepared = prepare_text_for_tts(text, "f5-tts", enabled_modules=["bible"])

    segments = segment_text_for_tts(prepared, "f5-tts")

    assert len(segments) == 1
    assert "my flesh faints for you" in segments[0].text
    assert "Psalms chapter 63, verse 1" in segments[0].text


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