"""Tests for F5-TTS reference transcript selection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tts import (  # noqa: E402
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