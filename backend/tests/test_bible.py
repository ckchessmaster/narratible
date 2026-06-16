"""Unit tests for the Bible parsing module.

Runnable with pytest or directly: ``python tests/test_bible.py``.
"""

import sys
from pathlib import Path

# Ensure the backend root (containing the ``app`` package) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsing_modules.bible import tts_transform, transform  # noqa: E402
from app.parsing_modules import apply_modules, apply_tts_modules, list_modules  # noqa: E402


def test_basic_abbreviation_expands():
    assert transform("Ps 1:4") == "Psalms 1:4"


def test_multiple_abbreviations_same_book():
    assert transform("Mat 5:9") == "Matthew 5:9"
    assert transform("Matt 5:9") == "Matthew 5:9"
    assert transform("Mt 5:9") == "Matthew 5:9"


def test_numbered_book_preserves_range_reference():
    assert transform("1 Cor 13:4-7") == "1 Corinthians 13:4-7"


def test_unspaced_numbered_book():
    assert transform("1Cor 13:4") == "1 Corinthians 13:4"


def test_trailing_period_is_consumed():
    assert transform("Ps. 23:1") == "Psalms 23:1"


def test_reference_portion_left_untouched():
    assert transform("Mt 5:3,9") == "Matthew 5:3,9"


def test_case_insensitive_input_normalizes_output():
    assert transform("ps 1:4") == "Psalms 1:4"


def test_no_false_positive_on_ordinary_word():
    # "is" is the abbreviation for Isaiah, but without a chapter:verse
    # reference it must be left alone.
    assert transform("this is a test") == "this is a test"
    assert transform("it is 3 apples") == "it is 3 apples"


def test_bare_book_mention_not_expanded():
    # No reference => no expansion, even for a valid abbreviation.
    assert transform("Read Ps today") == "Read Ps today"


def test_full_name_unchanged():
    assert transform("Matthew 5:9") == "Matthew 5:9"


def test_within_sentence():
    assert (
        transform("As it says in Jn 3:16, God so loved the world.")
        == "As it says in John 3:16, God so loved the world."
    )


def test_apply_modules_uses_bible():
    assert apply_modules("Ps 1:4", ["bible"]) == "Psalms 1:4"


def test_apply_modules_ignores_unknown_and_empty():
    assert apply_modules("Ps 1:4", []) == "Ps 1:4"
    assert apply_modules("Ps 1:4", ["does-not-exist"]) == "Ps 1:4"


def test_bible_tts_transform_expands_scripture_for_local_engines():
    assert tts_transform("Ps 1:4", "kokoro") == "Psalms 1, verse 4"
    assert tts_transform("Psalms 63:1", "f5-tts") == (
        "Psalms chapter 63, verse 1"
    )


def test_apply_tts_modules_respects_enabled_modules():
    assert apply_tts_modules("Ps 1:4", [], "f5-tts") == "Ps 1:4"
    assert apply_tts_modules("Ps 1:4", ["does-not-exist"], "f5-tts") == "Ps 1:4"
    assert apply_tts_modules("Ps 1:4", ["bible"], "f5-tts") == (
        "Psalms chapter 1, verse 4"
    )


def test_list_modules_exposes_bible():
    ids = [m["id"] for m in list_modules()]
    assert "bible" in ids
    bible = next(m for m in list_modules() if m["id"] == "bible")
    assert "transform" not in bible  # callable must not leak to the API
    assert "tts_transform" not in bible


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
