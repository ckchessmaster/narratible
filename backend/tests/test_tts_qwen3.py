"""Unit coverage for the optional Qwen3-TTS integration."""

import asyncio
import inspect
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, tts  # noqa: E402


class _FakeCuda:
    def is_available(self):
        return False

    def empty_cache(self):
        return None


def test_qwen3_transformers_adapter_supports_decorator_factory(monkeypatch):
    calls = []

    def check_model_inputs(func):
        calls.append(func)
        return func

    generic = SimpleNamespace(check_model_inputs=check_model_inputs)
    fake_transformers_utils = ModuleType("transformers.utils")
    fake_transformers_utils.generic = generic
    monkeypatch.setitem(sys.modules, "transformers.utils", fake_transformers_utils)

    tts._prepare_qwen3_transformers()

    decorator = generic.check_model_inputs()
    assert inspect.isfunction(decorator)
    assert decorator(lambda: None) is calls[0]


def test_qwen3_config_adapter_restores_talker_pad_token(monkeypatch):
    class FakeTalkerConfig:
        def __init__(self, codec_pad_id=4196, **_kwargs):
            self.codec_pad_id = codec_pad_id

    class FakeCodePredictorConfig:
        def __init__(self, **_kwargs):
            pass

    fake_config = ModuleType("qwen_tts.core.models.configuration_qwen3_tts")
    fake_config.Qwen3TTSTalkerConfig = FakeTalkerConfig
    fake_config.Qwen3TTSTalkerCodePredictorConfig = FakeCodePredictorConfig
    monkeypatch.setitem(
        sys.modules,
        "qwen_tts.core.models.configuration_qwen3_tts",
        fake_config,
    )

    tts._prepare_qwen3_config()
    config = FakeTalkerConfig(
        codec_pad_id=1234,
        text_vocab_size=151936,
        max_length=20,
    )
    predictor_config = FakeCodePredictorConfig(pad_token_id=2048, top_k=50)

    assert config.pad_token_id == 1234
    assert config.text_vocab_size == 151936
    assert not hasattr(config, "max_length")
    assert predictor_config.pad_token_id == 2048
    assert not hasattr(predictor_config, "top_k")


def test_qwen3_rope_adapter_restores_default_initializer(monkeypatch):
    fake_rope = ModuleType("transformers.modeling_rope_utils")
    fake_rope.ROPE_INIT_FUNCTIONS = {}
    monkeypatch.setitem(sys.modules, "transformers.modeling_rope_utils", fake_rope)

    tts._prepare_qwen3_rope()
    inverse_frequency, scaling = fake_rope.ROPE_INIT_FUNCTIONS["default"](
        SimpleNamespace(
            head_dim=8,
            hidden_size=16,
            num_attention_heads=2,
            partial_rotary_factor=1.0,
            rope_theta=10000.0,
        )
    )

    assert inverse_frequency.shape == (4,)
    assert scaling == 1.0


def test_qwen3_masking_adapter_translates_legacy_keywords(monkeypatch):
    calls = []

    def fake_mask(**kwargs):
        calls.append(kwargs)
        return "mask"

    fake_masking = ModuleType("transformers.masking_utils")
    fake_masking.create_causal_mask = fake_mask
    fake_masking.create_sliding_window_causal_mask = fake_mask
    fake_modeling = ModuleType("qwen_tts.core.models.modeling_qwen3_tts")
    fake_tokenizer = ModuleType(
        "qwen_tts.core.tokenizer_12hz.modeling_qwen3_tts_tokenizer_v2"
    )
    fake_models = ModuleType("qwen_tts.core.models")
    fake_models.modeling_qwen3_tts = fake_modeling
    fake_tokenizer_package = ModuleType("qwen_tts.core.tokenizer_12hz")
    fake_tokenizer_package.modeling_qwen3_tts_tokenizer_v2 = fake_tokenizer
    monkeypatch.setitem(sys.modules, "transformers.masking_utils", fake_masking)
    monkeypatch.setitem(sys.modules, "qwen_tts.core.models", fake_models)
    monkeypatch.setitem(sys.modules, "qwen_tts.core.tokenizer_12hz", fake_tokenizer_package)

    tts._prepare_qwen3_masking()
    result = fake_modeling.create_causal_mask(
        config="config",
        input_embeds="embeds",
        attention_mask=None,
        cache_position="legacy-position",
        past_key_values=None,
    )

    assert result == "mask"
    assert calls == [{
        "config": "config",
        "inputs_embeds": "embeds",
        "attention_mask": None,
        "past_key_values": None,
    }]
    assert fake_tokenizer.create_causal_mask is fake_modeling.create_causal_mask


def test_qwen3_position_adapter_slices_cached_decode_positions(monkeypatch):
    calls = []

    class FakeTalkerModel:
        def forward(self, *args, **kwargs):
            calls.append(kwargs)
            return "output"

    fake_modeling = ModuleType("qwen_tts.core.models.modeling_qwen3_tts")
    fake_modeling.Qwen3TTSTalkerModel = FakeTalkerModel
    monkeypatch.setitem(
        sys.modules,
        "qwen_tts.core.models.modeling_qwen3_tts",
        fake_modeling,
    )

    tts._prepare_qwen3_positions()
    result = FakeTalkerModel().forward(
        inputs_embeds=torch.zeros((1, 1, 8)),
        position_ids=torch.arange(11).view(1, 1, 11).expand(3, -1, -1),
    )

    assert result == "output"
    assert calls[0]["position_ids"].shape == (3, 1, 1)
    assert calls[0]["position_ids"][0, 0, 0].item() == 10


def _install_fake_qwen(monkeypatch, calls):
    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls["load"] = (model_id, kwargs)
            return cls()

        def create_voice_clone_prompt(self, **kwargs):
            calls.setdefault("prompts", []).append(kwargs)
            return "cached-prompt"

        def generate_voice_clone(self, **kwargs):
            calls.setdefault("generated", []).append(kwargs)
            return [np.array([0.0, 0.2, 0.0], dtype=np.float32)], 24000

    fake_torch = ModuleType("torch")
    fake_torch.cuda = _FakeCuda()
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float32 = "float32"
    fake_qwen = ModuleType("qwen_tts")
    fake_qwen.Qwen3TTSModel = FakeModel
    fake_soundfile = ModuleType("soundfile")
    fake_soundfile.write = lambda path, audio, sample_rate: calls.update(
        output=(path, audio.copy(), sample_rate)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", fake_qwen)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)
    monkeypatch.setattr(tts, "_prepare_frozen_torch", lambda _torch: None)
    monkeypatch.setattr(tts, "_prepare_qwen3_transformers", lambda: None)
    monkeypatch.setattr(tts, "_prepare_qwen3_config", lambda: None)
    monkeypatch.setattr(tts, "_prepare_qwen3_rope", lambda: None)
    monkeypatch.setattr(tts, "_prepare_qwen3_masking", lambda: None)
    monkeypatch.setattr(tts, "_prepare_qwen3_positions", lambda: None)
    monkeypatch.setattr(tts, "_select_chatterbox_device", lambda _torch: "cpu")
    monkeypatch.setattr(tts, "_qwen3_tts_model", None)
    monkeypatch.setattr(tts, "_qwen3_tts_model_device", None)


def test_qwen3_reuses_reference_prompt_for_all_segments(tmp_path, monkeypatch):
    calls = {}
    _install_fake_qwen(monkeypatch, calls)
    monkeypatch.setattr(
        tts,
        "segment_text_for_tts",
        lambda _text, engine: [
            SimpleNamespace(text="First sentence.", pause_after_ms=100),
            SimpleNamespace(text="Second sentence.", pause_after_ms=0),
        ],
    )
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")
    output = tmp_path / "chapter.wav"

    asyncio.run(
        tts._synthesize_qwen3_tts(
            "First sentence. Second sentence.",
            output,
            temperature=0.65,
            voice_sample_path=reference,
            voice_reference_text="Exact reference transcript.",
        )
    )

    assert calls["load"] == (
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        {"device_map": "cpu", "dtype": "float32"},
    )
    assert calls["prompts"] == [{
        "ref_audio": str(reference),
        "ref_text": "Exact reference transcript.",
        "x_vector_only_mode": False,
    }]
    assert [call["text"] for call in calls["generated"]] == [
        "First sentence.",
        "Second sentence.",
    ]
    assert all(call["voice_clone_prompt"] == "cached-prompt" for call in calls["generated"])
    assert calls["output"][0] == str(output)
    assert calls["output"][2] == 24000
    assert len(calls["output"][1]) == 2406


def test_qwen3_uses_embedding_only_when_transcript_is_missing(tmp_path, monkeypatch):
    calls = {}
    _install_fake_qwen(monkeypatch, calls)
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")

    asyncio.run(
        tts._synthesize_qwen3_tts(
            "A short test.",
            tmp_path / "preview.wav",
            voice_sample_path=reference,
        )
    )

    assert calls["prompts"][0]["ref_text"] is None
    assert calls["prompts"][0]["x_vector_only_mode"] is True


def test_qwen3_applies_pitch_preserving_speed_control(tmp_path, monkeypatch):
    calls = {}
    _install_fake_qwen(monkeypatch, calls)
    fake_librosa = ModuleType("librosa")
    fake_librosa.effects = SimpleNamespace(
        time_stretch=lambda audio, rate: calls.update(speed_rate=rate) or audio[:2]
    )
    monkeypatch.setitem(sys.modules, "librosa", fake_librosa)
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")

    asyncio.run(
        tts._synthesize_qwen3_tts(
            "A short test.",
            tmp_path / "preview.wav",
            speed=1.25,
            voice_sample_path=reference,
        )
    )

    assert calls["speed_rate"] == 1.25
    assert len(calls["output"][1]) == 2


def test_qwen3_requires_reference_audio(tmp_path, monkeypatch):
    calls = {}
    _install_fake_qwen(monkeypatch, calls)

    with pytest.raises(ValueError, match="requires a voice sample"):
        asyncio.run(
            tts._synthesize_qwen3_tts(
                "A short test.",
                tmp_path / "preview.wav",
            )
        )


def test_qwen3_library_voice_resolves_saved_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_library_voice",
        lambda _voice_id: SimpleNamespace(
            name="Narrator",
            engine="qwen3-tts",
            engine_configured=True,
            reference_text="Saved transcript.",
            temperature=0.8,
        ),
    )
    monkeypatch.setattr(
        main,
        "get_library_voice_sample_path",
        lambda _voice_id: tmp_path / "reference.wav",
    )

    sample_path, samples_dir, reference_text, temperature = main._resolve_clone_voice_reference(
        "project-1", "qwen3-tts", "voice-1"
    )

    assert sample_path == tmp_path / "reference.wav"
    assert samples_dir is None
    assert reference_text == "Saved transcript."
    assert temperature == 0.8