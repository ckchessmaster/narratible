"""Tests for optional Voice Library reference enhancement."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app.voice_enhancement import (  # noqa: E402
    VoiceEnhancementDeviceError,
    VoiceEnhancementUnavailableError,
    enhance_reference_audio,
    resolve_enhancement_device,
)


def _fake_torch(*, cuda=False, count=0, mps=False):
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda, device_count=lambda: count),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )


def test_auto_device_prefers_configured_cuda(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, count=2, mps=True))
    assert resolve_enhancement_device("auto", cuda_index=1) == "cuda:1"


def test_auto_device_uses_mps_then_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(mps=True))
    assert resolve_enhancement_device("auto", cuda_index=0) == "mps"
    monkeypatch.setitem(sys.modules, "torch", _fake_torch())
    assert resolve_enhancement_device("auto", cuda_index=0) == "cpu"


def test_auto_device_ignores_stale_cuda_index(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, count=1, mps=True))
    assert resolve_enhancement_device("auto", cuda_index=3) == "mps"


def test_explicit_unavailable_accelerator_is_clear(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch())
    with pytest.raises(VoiceEnhancementDeviceError, match="CUDA was requested"):
        resolve_enhancement_device("cuda")
    with pytest.raises(VoiceEnhancementDeviceError, match="Apple Metal"):
        resolve_enhancement_device("mps")


def test_enhancement_worker_uses_configured_python_and_parses_device(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    output = tmp_path / "enhanced.wav"
    source.write_bytes(b"audio")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps({"device": "cpu"}), stderr="")

    monkeypatch.setenv("NARRATIBLE_VOICE_ENHANCER_PYTHON", "/opt/enhancer/bin/python")
    monkeypatch.setattr("app.voice_enhancement.subprocess.run", fake_run)

    assert enhance_reference_audio(source, output, device="auto", nfe=16) == "cpu"
    assert captured["command"][0] == "/opt/enhancer/bin/python"
    assert captured["command"][-1] == "16"


def test_enhancement_worker_reports_missing_runtime(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="No module named resemble_enhance\n")

    monkeypatch.setattr("app.voice_enhancement.subprocess.run", fake_run)
    with pytest.raises(VoiceEnhancementUnavailableError, match="resemble_enhance"):
        enhance_reference_audio(tmp_path / "source.wav", tmp_path / "output.wav")


def test_voice_library_enhancement_adds_copy_and_activates(tmp_path, monkeypatch):
    source = tmp_path / "reference.wav"
    source.write_bytes(b"original")
    recorded = {}

    monkeypatch.setattr(main, "get_library_voice", lambda _id: SimpleNamespace(sample_filename="reference.wav"))
    monkeypatch.setattr(main, "get_library_voice_sample_path", lambda _id: source)
    monkeypatch.setattr(main, "load_config", lambda: SimpleNamespace(selected_gpu_index=0))

    def fake_enhance(_source, output, **kwargs):
        output.write_bytes(b"enhanced")
        return "cuda:0"

    def fake_add(voice_id, filename, fileobj, activate):
        recorded.update(voice_id=voice_id, filename=filename, data=fileobj.read(), activate=activate)
        return {"id": voice_id, "sample_filename": filename}

    monkeypatch.setattr(main, "enhance_reference_audio", fake_enhance)
    monkeypatch.setattr(main, "add_library_voice_sample", fake_add)
    response = asyncio.run(main.api_enhance_voice_library_sample(
        "voice-1", main.VoiceLibraryEnhancementRequest(device="auto")
    ))

    assert response["device"] == "cuda:0"
    assert recorded == {
        "voice_id": "voice-1",
        "filename": "reference-enhanced.wav",
        "data": b"enhanced",
        "activate": True,
    }


def test_voice_library_enhancement_returns_503_when_optional_runtime_missing(tmp_path, monkeypatch):
    source = tmp_path / "reference.wav"
    source.write_bytes(b"original")
    monkeypatch.setattr(main, "get_library_voice", lambda _id: SimpleNamespace(sample_filename="reference.wav"))
    monkeypatch.setattr(main, "get_library_voice_sample_path", lambda _id: source)
    monkeypatch.setattr(main, "load_config", lambda: SimpleNamespace(selected_gpu_index=0))
    monkeypatch.setattr(
        main,
        "enhance_reference_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(VoiceEnhancementUnavailableError("not installed")),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.api_enhance_voice_library_sample(
            "voice-1", main.VoiceLibraryEnhancementRequest()
        ))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "not installed"
