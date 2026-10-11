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


def test_build_atempo_filter():
    assert tts._build_atempo_filter(1.0) == "atempo=1.0000"
    assert tts._build_atempo_filter(1.25) == "atempo=1.2500"
    assert tts._build_atempo_filter(2.5) == "atempo=2.0,atempo=1.2500"
    assert tts._build_atempo_filter(0.4) == "atempo=0.5,atempo=0.8000"
    assert tts._build_atempo_filter(0) == "atempo=1.0"


def test_apply_speech_time_stretch_noop_at_unity_speed():
    audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    result = tts._apply_speech_time_stretch(audio, sample_rate=24000, speed=1.0)
    assert np.array_equal(result, audio)


def test_apply_speech_time_stretch_with_ffmpeg(tmp_path, monkeypatch):
    import shutil
    import subprocess
    import soundfile as sf

    fake_ffmpeg = "fake_ffmpeg"
    monkeypatch.setattr(shutil, "which", lambda cmd: fake_ffmpeg if cmd == "ffmpeg" else None)

    cmd_executed = []

    def fake_run(cmd, **kwargs):
        cmd_executed.append(cmd)
        out_path = cmd[-1]
        dummy_audio = np.ones(500, dtype=np.float32) * 0.1
        sf.write(out_path, dummy_audio, 24000)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    in_audio = np.ones(1000, dtype=np.float32) * 0.2
    result = tts._apply_speech_time_stretch(in_audio, sample_rate=24000, speed=1.5)

    assert len(cmd_executed) == 1
    assert "-filter:a" in cmd_executed[0]
    filter_idx = cmd_executed[0].index("-filter:a")
    assert cmd_executed[0][filter_idx + 1] == "atempo=1.5000"
    assert len(result) == 500


def test_apply_speech_time_stretch_fallback_to_librosa(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _cmd: None)

    librosa_called = []
    fake_librosa = ModuleType("librosa")
    fake_effects = ModuleType("librosa.effects")
    fake_effects.time_stretch = lambda audio, rate: librosa_called.append(rate) or audio[: len(audio) // 2]
    fake_librosa.effects = fake_effects
    monkeypatch.setitem(sys.modules, "librosa", fake_librosa)
    monkeypatch.setitem(sys.modules, "librosa.effects", fake_effects)

    in_audio = np.ones(1000, dtype=np.float32)
    result = tts._apply_speech_time_stretch(in_audio, sample_rate=24000, speed=1.25)

    assert librosa_called == [1.25]
    assert len(result) == 500


def test_chatterbox_worker_atempo_filter_and_stretch():
    from app.runtime_worker_scripts import chatterbox_worker

    assert chatterbox_worker._build_atempo_filter(1.5) == "atempo=1.5000"
    assert chatterbox_worker._build_atempo_filter(2.5) == "atempo=2.0,atempo=1.2500"

    audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    res = chatterbox_worker._apply_time_stretch(audio, 24000, 1.0)
    assert np.array_equal(res, audio)

