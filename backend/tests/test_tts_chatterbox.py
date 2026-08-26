"""Unit coverage for the optional Chatterbox integration."""

import asyncio
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, tts  # noqa: E402


class _FakeCuda:
    def __init__(self, available=False, count=0):
        self._available = available
        self._count = count

    def is_available(self):
        return self._available

    def device_count(self):
        return self._count

    def empty_cache(self):
        return None


def test_chatterbox_device_prefers_selected_cuda(monkeypatch):
    monkeypatch.setattr(
        config, "load_config", lambda: SimpleNamespace(selected_gpu_index=1)
    )
    torch_module = SimpleNamespace(
        cuda=_FakeCuda(available=True, count=2),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
    )

    assert tts._select_chatterbox_device(torch_module) == "cuda:1"


def test_chatterbox_device_uses_mps_then_cpu(monkeypatch):
    monkeypatch.setattr(
        config, "load_config", lambda: SimpleNamespace(selected_gpu_index=0)
    )
    mps_torch = SimpleNamespace(
        cuda=_FakeCuda(),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
    )
    assert tts._select_chatterbox_device(mps_torch) == "mps"

    monkeypatch.setattr(
        config, "load_config", lambda: SimpleNamespace(selected_gpu_index=-1)
    )
    assert tts._select_chatterbox_device(mps_torch) == "cpu"


def test_trim_chatterbox_edges_retains_sixty_ms_boundary():
    audio = np.concatenate(
        [np.zeros(200), np.ones(100, dtype=np.float32) * 0.2, np.zeros(200)]
    )

    trimmed = tts._trim_chatterbox_edges(audio, sample_rate=1000)

    assert len(trimmed) == 220
    assert np.count_nonzero(trimmed) == 100


def test_chatterbox_uses_smooth_defaults_and_voice_sample(tmp_path, monkeypatch):
    calls = {"generated": []}

    class FakeWaveform:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([[0.0, 0.2, 0.0]], dtype=np.float32)

    class FakeModel:
        sr = 24000

        @classmethod
        def from_pretrained(cls, device):
            calls["device"] = device
            return cls()

        def prepare_conditionals(self, path, exaggeration):
            calls["reference"] = (path, exaggeration)

        def generate(self, text, **kwargs):
            calls["generated"].append((text, kwargs))
            return FakeWaveform()

    fake_torch = ModuleType("torch")
    fake_torch.cuda = _FakeCuda()
    fake_chatterbox = ModuleType("chatterbox")
    fake_chatterbox_tts = ModuleType("chatterbox.tts")
    fake_chatterbox_tts.ChatterboxTTS = FakeModel
    fake_soundfile = ModuleType("soundfile")
    fake_soundfile.write = lambda path, audio, sample_rate: calls.update(
        output=(path, audio.copy(), sample_rate)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", fake_chatterbox_tts)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)
    monkeypatch.setattr(tts, "_select_chatterbox_device", lambda _torch: "cpu")
    monkeypatch.setattr(tts, "_chatterbox_model", None)
    monkeypatch.setattr(tts, "_chatterbox_model_device", None)

    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")
    output = tmp_path / "chapter.wav"
    asyncio.run(
        tts._synthesize_chatterbox(
            "First sentence. Second sentence.",
            output,
            speed=1.0,
            temperature=0.75,
            exaggeration=0.6,
            cfg_weight=0.25,
            voice_sample_path=reference,
        )
    )

    assert calls["device"] == "cpu"
    assert calls["reference"] == (str(reference), 0.6)
    assert len(calls["generated"]) == 1
    assert calls["generated"][0][1] == {
        "exaggeration": 0.6,
        "cfg_weight": 0.25,
        "temperature": 0.75,
    }
    assert calls["output"][0] == str(output)
    assert calls["output"][2] == 24000


def test_chatterbox_reloads_after_device_selection_changes(tmp_path, monkeypatch):
    loaded_devices = []

    class FakeWaveform:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([[0.0, 0.2, 0.0]], dtype=np.float32)

    class FakeModel:
        sr = 24000

        @classmethod
        def from_pretrained(cls, device):
            loaded_devices.append(device)
            return cls()

        def prepare_conditionals(self, _path, exaggeration):
            return None

        def generate(self, _text, **_kwargs):
            return FakeWaveform()

    fake_torch = ModuleType("torch")
    fake_torch.cuda = _FakeCuda()
    fake_chatterbox = ModuleType("chatterbox")
    fake_chatterbox_tts = ModuleType("chatterbox.tts")
    fake_chatterbox_tts.ChatterboxTTS = FakeModel
    fake_soundfile = ModuleType("soundfile")
    fake_soundfile.write = lambda *_args: None
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", fake_chatterbox_tts)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)
    devices = iter(("cpu", "mps"))
    monkeypatch.setattr(tts, "_select_chatterbox_device", lambda _torch: next(devices))
    monkeypatch.setattr(tts, "_chatterbox_model", None)
    monkeypatch.setattr(tts, "_chatterbox_model_device", None)

    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")
    for index in range(2):
        asyncio.run(
            tts._synthesize_chatterbox(
                "A short test.",
                tmp_path / f"output-{index}.wav",
                voice_sample_path=reference,
            )
        )

    assert loaded_devices == ["cpu", "mps"]
