"""Unit tests for Edge-TTS protocol compatibility and 403 error handling."""

import asyncio
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import desktop_app  # noqa: E402
from app import tts  # noqa: E402


class _FakeHttpError(Exception):
    def __init__(self, status: int, message: str = "error"):
        super().__init__(message)
        self.status = status


def _parse_version(version_str: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version_str.split(".")[:3])


def test_installed_edge_tts_supports_sec_ms_gec_v2():
    import edge_tts
    from edge_tts import constants

    assert _parse_version(edge_tts.__version__) >= (7, 3, 1)
    assert constants.SEC_MS_GEC_VERSION.startswith("2-")


def test_requirements_and_constraints_enforce_edge_tts_fix():
    repo_root = Path(__file__).resolve().parents[2]
    requirements_lines = (
        (repo_root / "backend" / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    constraints_lines = (
        (repo_root / "backend" / "constraints.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert "edge-tts>=7.3.1" in requirements_lines
    assert "edge-tts==7.3.1" in constraints_lines


def test_get_available_voices_edge_tts_maps_fields(monkeypatch):
    async def fake_list_voices():
        return [
            {
                "ShortName": "en-US-AriaNeural",
                "FriendlyName": "Microsoft Aria Online (Natural) - English (United States)",
                "Locale": "en-US",
            }
        ]

    fake_edge_tts = ModuleType("edge_tts")
    fake_edge_tts.__version__ = "7.3.1"
    fake_edge_tts.list_voices = fake_list_voices
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)

    voices = asyncio.run(tts.get_available_voices("edge-tts"))

    assert voices == [
        {
            "id": "en-US-AriaNeural",
            "name": "Microsoft Aria Online (Natural) - English (United States)",
            "locale": "en-US",
        }
    ]


def test_get_available_voices_edge_tts_formats_403_and_preserves_other_errors(monkeypatch):
    async def fail_403():
        raise _FakeHttpError(403, "Invalid response status")

    fake_edge_tts = ModuleType("edge_tts")
    fake_edge_tts.__version__ = "7.2.8"
    fake_edge_tts.list_voices = fail_403
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)

    with pytest.raises(RuntimeError, match="HTTP 403.*7\\.2\\.8.*>=7\\.3\\.1") as exc_info:
        asyncio.run(tts.get_available_voices("edge-tts"))
    assert isinstance(exc_info.value.__cause__, _FakeHttpError)

    async def fail_503():
        raise _FakeHttpError(503, "Service unavailable")

    fake_edge_tts.list_voices = fail_503
    with pytest.raises(_FakeHttpError, match="Service unavailable"):
        asyncio.run(tts.get_available_voices("edge-tts"))


def test_synthesize_speech_edge_tts_calls_communicate_and_handles_403(tmp_path, monkeypatch):
    calls = []
    outcome = {"exc": None}

    class FakeCommunicate:
        def __init__(self, text, voice, rate="+0%"):
            calls.append((text, voice, rate))

        async def save(self, path):
            if outcome["exc"] is not None:
                raise outcome["exc"]
            Path(path).write_bytes(b"mp3-bytes")

    fake_edge_tts = ModuleType("edge_tts")
    fake_edge_tts.__version__ = "7.3.1"
    fake_edge_tts.Communicate = FakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)

    out_path = tmp_path / "preview.mp3"
    asyncio.run(
        tts.synthesize_speech(
            "Main text.[^1]\n\n[^1]: Note.",
            out_path,
            engine="edge-tts",
            voice="en-US-GuyNeural",
            speed=1.25,
        )
    )

    assert calls == [("Main text.", "en-US-GuyNeural", "+25%")]
    assert out_path.read_bytes() == b"mp3-bytes"

    outcome["exc"] = _FakeHttpError(403, "Invalid response status")
    with pytest.raises(RuntimeError, match="Edge-TTS speech synthesis failed with HTTP 403"):
        asyncio.run(
            tts.synthesize_speech("Hello", tmp_path / "fail403.mp3", engine="edge-tts")
        )

    outcome["exc"] = _FakeHttpError(500, "Upstream error")
    with pytest.raises(_FakeHttpError, match="Upstream error"):
        asyncio.run(
            tts.synthesize_speech("Hello", tmp_path / "fail500.mp3", engine="edge-tts")
        )


def test_verify_packaged_tts_imports_rejects_outdated_edge_tts(monkeypatch):
    fake_numpy = ModuleType("numpy")
    fake_numpy.__version__ = "2.4.6"
    fake_edge_tts = ModuleType("edge_tts")
    fake_edge_tts.__version__ = "7.2.8"
    fake_runtime_engines = ModuleType("backend.app.runtime_engines")
    fake_runtime_engines.load_runtime_catalog = lambda: {"profiles": [{"id": "kokoro"}]}
    fake_runtime_engines.runtime_python = lambda: SimpleNamespace(is_file=lambda: True)
    fake_runtime_engines.uv_executable = lambda: SimpleNamespace(is_file=lambda: True)

    monkeypatch.setattr(desktop_app, "_verify_packaged_frontend", lambda: None)
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)
    monkeypatch.setitem(sys.modules, "backend.app.runtime_engines", fake_runtime_engines)

    with pytest.raises(RuntimeError, match="7\\.2\\.8.*>=7\\.3\\.1"):
        desktop_app._verify_packaged_tts_imports()

    fake_edge_tts.__version__ = "7.3.1"
    desktop_app._verify_packaged_tts_imports()
