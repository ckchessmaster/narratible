"""Tests for saved voice engine ownership and legacy compatibility."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import voices  # noqa: E402


def _use_library(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_LIBRARY_DIR", tmp_path)
    monkeypatch.setattr(voices, "VOICE_LIBRARY_FILE", tmp_path / "voices.json")
    monkeypatch.setattr(voices, "LEGACY_VOICE_LIBRARY_DIR", tmp_path / "legacy")


def _create_voice(engine="chatterbox"):
    return voices.create_library_voice(
        "Narrator",
        engine,
        "",
        "",
        "",
        1.1,
        0.8,
        0.65,
        0.25,
        "reference.wav",
        io.BytesIO(b"audio"),
    )


def test_new_voice_persists_engine_and_defaults(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)

    created = _create_voice()
    reloaded = voices.get_library_voice(created.id)

    assert reloaded.engine == "chatterbox"
    assert reloaded.engine_configured is True
    assert reloaded.speed == 1.1
    assert reloaded.temperature == 0.8
    assert reloaded.exaggeration == 0.65
    assert reloaded.cfg_weight == 0.25


def test_builtin_voice_persists_provider_voice_without_sample(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)

    created = voices.create_library_voice(
        "Aria audiobook",
        "edge-tts",
        "en-US-AriaNeural",
        "",
        "",
        0.95,
        0.7,
        0.5,
        0.3,
    )

    assert created.provider_voice_id == "en-US-AriaNeural"
    assert created.sample_filename == ""
    assert created.sample_filenames == []
    assert not (tmp_path / created.id).exists()


def test_builtin_voice_requires_provider_voice(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Choose a provider voice"):
        voices.create_library_voice("Missing provider", "kokoro", "", "", "", 1, 0.7, 0.5, 0.3)


def test_clone_voice_requires_reference_audio(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Reference audio is required"):
        voices.create_library_voice("Missing sample", "f5-tts", "", "", "", 1, 0.7, 0.5, 0.3)


def test_legacy_voice_requires_engine_confirmation(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "voices.json").write_text(json.dumps([{
        "id": "legacy",
        "name": "Legacy narrator",
        "sample_filename": "reference.wav",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }]), encoding="utf-8")

    legacy = voices.get_library_voice("legacy")
    assert legacy.engine == "f5-tts"
    assert legacy.engine_configured is False

    confirmed = voices.update_library_voice("legacy", {"engine": "chatterbox"})
    assert confirmed.engine == "chatterbox"
    assert confirmed.engine_configured is True


def test_confirmed_voice_engine_is_immutable(tmp_path, monkeypatch):
    _use_library(tmp_path, monkeypatch)
    created = _create_voice("f5-tts")

    with pytest.raises(ValueError, match="cannot be changed"):
        voices.update_library_voice(created.id, {"engine": "chatterbox"})