"""Tests for F5-TTS reference transcript selection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tts import (  # noqa: E402
    _f5_reference_was_clipped,
    _select_f5_reference_text,
    _is_plausible_f5_reference_text,
)


def test_f5_reference_text_accepts_transcript_that_matches_clip_duration():
    text = "This is a clear reference sentence for the speaker."

    assert _is_plausible_f5_reference_text(text, duration_seconds=4.0)
    assert _select_f5_reference_text(text, "", duration_seconds=4.0) == text


def test_f5_reference_text_prefers_asr_when_supplied_text_is_too_long_for_clip():
    full_clip_transcript = " ".join(["reference"] * 80)
    clipped_asr_transcript = "This is the part of the reference clip F5 can actually use."

    selected = _select_f5_reference_text(
        full_clip_transcript,
        clipped_asr_transcript,
        duration_seconds=6.0,
    )

    assert selected == clipped_asr_transcript


def test_f5_reference_text_rejects_full_transcript_for_twelve_second_clip():
    full_reference_text = (
        "But the truth doesn't have an end. It just keeps going, and if you don't have the guts "
        "to follow it, you die. She would learn that the loss doesn't go away. It lives in you, "
        "with you, a snake around your throat, and this is the secret nobody tells you. The coils "
        "don't let go. You just learn to live with your ghosts."
    )

    assert not _is_plausible_f5_reference_text(full_reference_text, duration_seconds=12.0)


def test_f5_reference_text_fails_when_no_usable_transcript_exists():
    with pytest.raises(ValueError, match="could not transcribe"):
        _select_f5_reference_text("", "", duration_seconds=6.0)


def test_f5_reference_text_uses_processed_clip_asr_when_source_was_clipped():
    full_source_transcript = (
        "This text covers the entire long recording, including words spoken after "
        "the twelve second reference limit."
    )
    processed_clip_transcript = "This text covers only the audio F5 kept."

    selected = _select_f5_reference_text(
        full_source_transcript,
        processed_clip_transcript,
        duration_seconds=8.0,
        reference_was_clipped=True,
    )

    assert selected == processed_clip_transcript


def test_f5_reference_text_does_not_reuse_full_text_if_clipped_asr_fails():
    with pytest.raises(ValueError, match="clipped the reference audio"):
        _select_f5_reference_text(
            "A plausible-looking transcript for the entire source recording.",
            "",
            duration_seconds=8.0,
            reference_was_clipped=True,
        )


def test_f5_clipping_detected_from_preprocessor_message():
    assert _f5_reference_was_clipped(
        None,
        processed_duration_seconds=9.0,
        preprocessing_messages=["Audio is over 12s, clipping short. (1)"],
    )


def test_f5_clipping_detected_by_duration_when_preprocessed_audio_is_cached():
    assert _f5_reference_was_clipped(
        original_duration_seconds=23.0,
        processed_duration_seconds=11.8,
        preprocessing_messages=["Using cached preprocessed reference audio..."],
    )


def test_f5_short_reference_preserves_matching_user_transcript():
    assert not _f5_reference_was_clipped(
        original_duration_seconds=9.0,
        processed_duration_seconds=8.7,
        preprocessing_messages=[],
    )
    assert _select_f5_reference_text(
        "This transcript matches the short reference clip.",
        "",
        duration_seconds=8.7,
    ) == "This transcript matches the short reference clip."
