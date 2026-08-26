import logging
import re
import sys
from pathlib import Path
from typing import Optional, Callable

from .tts_text import prepare_text_for_tts, segment_text_for_tts

logger = logging.getLogger(__name__)


def _prepare_frozen_torch(torch_module) -> None:
    """Disable source-based TorchScript compilation in the frozen app."""
    if getattr(sys, "frozen", False) and not getattr(
        torch_module.jit, "_narratible_noop", False
    ):
        torch_module.jit.script = lambda fn, *args, **kwargs: fn
        torch_module.jit._narratible_noop = True


def _prepare_qwen3_transformers() -> None:
    """Bridge Qwen 0.1.1 config/decorator assumptions to newer Transformers."""
    import inspect
    from transformers.utils import generic

    decorator = generic.check_model_inputs
    if getattr(decorator, "_narratible_compatible", False):
        return
    if tuple(inspect.signature(decorator).parameters) != ("func",):
        return

    def _compatible_check_model_inputs(func=None):
        return decorator if func is None else decorator(func)

    _compatible_check_model_inputs._narratible_compatible = True
    generic.check_model_inputs = _compatible_check_model_inputs


def _prepare_qwen3_config() -> None:
    """Preserve Qwen config kwargs and padding aliases under Transformers 5."""
    from qwen_tts.core.models.configuration_qwen3_tts import (
        Qwen3TTSTalkerCodePredictorConfig,
        Qwen3TTSTalkerConfig,
    )

    legacy_fields_by_class = {
        Qwen3TTSTalkerConfig: {
            "head_dim",
            "pad_token_id",
            "position_id_per_seconds",
            "text_vocab_size",
        },
        Qwen3TTSTalkerCodePredictorConfig: {"pad_token_id"},
    }
    for config_class, preserved_fields in legacy_fields_by_class.items():
        if getattr(config_class, "_narratible_compatible", False):
            continue

        original_init = config_class.__init__

        def _compatible_init(
            self,
            *args,
            _original_init=original_init,
            _preserved_fields=preserved_fields,
            **kwargs,
        ):
            legacy_fields = {
                name: value for name, value in kwargs.items() if name in _preserved_fields
            }
            _original_init(self, *args, **kwargs)
            for name, value in legacy_fields.items():
                if not hasattr(self, name):
                    setattr(self, name, value)
            if not hasattr(self, "pad_token_id"):
                self.pad_token_id = getattr(self, "codec_pad_id", None)

        _compatible_init._narratible_compatible = True
        config_class.__init__ = _compatible_init
        config_class._narratible_compatible = True


def _prepare_qwen3_rope() -> None:
    """Restore the default RoPE registry entry removed from Transformers 5."""
    import torch
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS

    if "default" in ROPE_INIT_FUNCTIONS:
        return

    def _default_rope(config, device=None, **_kwargs):
        head_dim = getattr(config, "head_dim", None) or (
            config.hidden_size // config.num_attention_heads
        )
        partial_rotary_factor = getattr(config, "partial_rotary_factor", 1.0)
        dimension = int(head_dim * partial_rotary_factor)
        inverse_frequency = 1.0 / (
            config.rope_theta
            ** (
                torch.arange(0, dimension, 2, dtype=torch.int64)
                .to(device=device, dtype=torch.float)
                / dimension
            )
        )
        return inverse_frequency, 1.0

    ROPE_INIT_FUNCTIONS["default"] = _default_rope


def _prepare_qwen3_masking() -> None:
    """Translate Qwen's Transformers 4 masking calls to Transformers 5."""
    from transformers import masking_utils
    from qwen_tts.core.models import modeling_qwen3_tts
    from qwen_tts.core.tokenizer_12hz import modeling_qwen3_tts_tokenizer_v2

    if getattr(masking_utils.create_causal_mask, "_narratible_compatible", False):
        return

    def _compatible_mask(mask_function):
        def _wrapper(*args, **kwargs):
            if "input_embeds" in kwargs and "inputs_embeds" not in kwargs:
                kwargs["inputs_embeds"] = kwargs.pop("input_embeds")
            kwargs.pop("cache_position", None)
            return mask_function(*args, **kwargs)

        _wrapper._narratible_compatible = True
        return _wrapper

    causal_mask = _compatible_mask(masking_utils.create_causal_mask)
    sliding_mask = _compatible_mask(masking_utils.create_sliding_window_causal_mask)
    masking_utils.create_causal_mask = causal_mask
    masking_utils.create_sliding_window_causal_mask = sliding_mask
    modeling_qwen3_tts.create_causal_mask = causal_mask
    modeling_qwen3_tts.create_sliding_window_causal_mask = sliding_mask
    modeling_qwen3_tts_tokenizer_v2.create_causal_mask = causal_mask
    modeling_qwen3_tts_tokenizer_v2.create_sliding_window_causal_mask = sliding_mask


def _prepare_qwen3_positions() -> None:
    """Keep cached decode position IDs aligned with Qwen's current input."""
    from functools import wraps
    from qwen_tts.core.models.modeling_qwen3_tts import Qwen3TTSTalkerModel

    if getattr(Qwen3TTSTalkerModel.forward, "_narratible_compatible", False):
        return

    original_forward = Qwen3TTSTalkerModel.forward

    @wraps(original_forward)
    def _compatible_forward(self, *args, **kwargs):
        inputs_embeds = kwargs.get("inputs_embeds")
        position_ids = kwargs.get("position_ids")
        if (
            inputs_embeds is not None
            and position_ids is not None
            and position_ids.shape[-1] != inputs_embeds.shape[1]
        ):
            kwargs["position_ids"] = position_ids[..., -inputs_embeds.shape[1]:]
        return original_forward(self, *args, **kwargs)

    _compatible_forward._narratible_compatible = True
    Qwen3TTSTalkerModel.forward = _compatible_forward


def compose_tts_text(title: str, body: str, read_headings: bool = True) -> str:
    """Combine a chapter heading with its body text for synthesis.

    When ``read_headings`` is True the chapter ``title`` is spoken before the
    body. To avoid reading the heading twice, the title is only prepended when
    the body doesn't already start with it (compared case-insensitively and
    ignoring whitespace differences). A blank line separates the heading from
    the body so engines insert a natural pause, and sentence-ending punctuation
    is added to the heading when missing.
    """
    body = body or ""
    title = (title or "").strip()
    if not read_headings or not title:
        return body

    def _normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().casefold()

    norm_title = _normalize(title)
    norm_body_start = _normalize(body)[: len(norm_title)]
    if norm_title and norm_body_start == norm_title:
        return body

    heading = title if title[-1] in ".!?:" else f"{title}."
    if not body.strip():
        return heading
    return f"{heading}\n\n{body}"

_torchaudio_shim_installed = False


def _install_torchaudio_soundfile_shim():
    """Replace torchaudio.load/save with soundfile-backed implementations.

    torchaudio >= 2.9 dropped its built-in I/O backends and dispatches all
    file decoding to ``torchcodec``, which needs FFmpeg "full-shared" DLLs
    that aren't present in the frozen Windows build.  F5-TTS calls
    ``torchaudio.load(ref_audio)`` internally, so without a backend it raises
    a RuntimeError and the request 500s.

    ``soundfile`` (libsndfile) is already bundled and reads the PCM WAV that
    F5-TTS produces during reference preprocessing, so we route torchaudio I/O
    through it and bypass torchcodec entirely.  torchaudio resolves ``load``/
    ``save`` as module attributes at call time, so patching them here takes
    effect for the F5-TTS code path.
    """
    global _torchaudio_shim_installed
    if _torchaudio_shim_installed:
        return
    try:
        import torchaudio
        import soundfile as sf
        import torch
    except ImportError:
        return

    def _sf_load(filepath, *args, **kwargs):  # noqa: ANN001
        # soundfile returns float64 frames shaped (frames,) or (frames, channels).
        data, sample_rate = sf.read(str(filepath), dtype="float32", always_2d=True)
        # torchaudio.load contract: tensor shaped [channels, frames].
        waveform = torch.from_numpy(data.T.copy())
        return waveform, sample_rate

    def _sf_save(filepath, src, sample_rate, *args, **kwargs):  # noqa: ANN001
        # torchaudio.save passes a tensor shaped [channels, frames].
        if hasattr(src, "detach"):
            src = src.detach().cpu().numpy()
        sf.write(str(filepath), src.T, int(sample_rate))

    torchaudio.load = _sf_load
    torchaudio.save = _sf_save
    _torchaudio_shim_installed = True
    logger.info("Installed torchaudio→soundfile I/O shim (bypasses torchcodec).")

# Cached pipeline instances — loaded lazily to avoid startup cost
_kokoro_pipeline = None
_f5tts_model = None
_chatterbox_model = None
_chatterbox_model_device = None
_qwen3_tts_model = None
_qwen3_tts_model_device = None
_whisper_model = None
_whisper_processor = None

_QWEN3_TTS_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

_F5_REFERENCE_PLACEHOLDER_TEXT = "This is only used while preparing the reference audio."
_MIN_F5_REFERENCE_CHARS_PER_SECOND = 2.0
_MAX_F5_REFERENCE_CHARS_PER_SECOND = 18.0


def _normalize_f5_reference_text(text: Optional[str]) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if cleaned and cleaned[-1] not in ".!?。！？":
        cleaned += "."
    return cleaned


def _is_plausible_f5_reference_text(text: str, duration_seconds: float) -> bool:
    cleaned = _normalize_f5_reference_text(text)
    if len(cleaned) < 4 or duration_seconds <= 0:
        return False
    chars_per_second = len(cleaned.encode("utf-8")) / duration_seconds
    return _MIN_F5_REFERENCE_CHARS_PER_SECOND <= chars_per_second <= _MAX_F5_REFERENCE_CHARS_PER_SECOND


def _select_f5_reference_text(
    provided_text: Optional[str],
    transcribed_text: Optional[str],
    duration_seconds: float,
    reference_was_clipped: bool = False,
) -> str:
    provided = _normalize_f5_reference_text(provided_text)
    if not reference_was_clipped and _is_plausible_f5_reference_text(
        provided, duration_seconds
    ):
        return provided

    transcribed = _normalize_f5_reference_text(transcribed_text)
    if transcribed and len(transcribed) >= 4:
        if provided:
            logger.warning(
                "Ignoring supplied F5-TTS reference transcript because its length "
                "does not match the preprocessed reference clip."
            )
        return transcribed

    if provided:
        if reference_was_clipped:
            raise ValueError(
                "F5-TTS clipped the reference audio, but could not transcribe the "
                "processed clip. Shorten the reference to 6-12 seconds and provide "
                "its exact transcript."
            )
        raise ValueError(
            "The F5-TTS reference transcript does not appear to match the usable "
            "reference audio after preprocessing. Use a shorter reference clip or "
            "provide the exact transcript for the first 6-12 seconds of speech."
        )

    raise ValueError(
        "F5-TTS could not transcribe the reference audio. Provide an exact "
        "reference transcript for the first 6-12 seconds of speech."
    )


def _f5_reference_was_clipped(
    original_duration_seconds: Optional[float],
    processed_duration_seconds: float,
    preprocessing_messages: list[str],
) -> bool:
    """Detect F5's 12-second reference clipping, including its cache path."""
    if any("clipping short" in message.casefold() for message in preprocessing_messages):
        return True
    if original_duration_seconds is None:
        return False
    return (
        original_duration_seconds > 12.0
        and processed_duration_seconds + 0.1 < original_duration_seconds
    )


def unload_tts():
    """Explicitly unload TTS models to free up VRAM."""
    global _kokoro_pipeline, _f5tts_model, _chatterbox_model, _chatterbox_model_device, _qwen3_tts_model, _qwen3_tts_model_device, _whisper_model, _whisper_processor
    import gc
    freed = False
    if _kokoro_pipeline is not None:
        _kokoro_pipeline = None
        freed = True
    if _f5tts_model is not None:
        _f5tts_model = None
        freed = True
    if _chatterbox_model is not None:
        _chatterbox_model = None
        _chatterbox_model_device = None
        freed = True
    if _qwen3_tts_model is not None:
        _qwen3_tts_model = None
        _qwen3_tts_model_device = None
        freed = True
    if _whisper_model is not None:
        _whisper_model = None
        _whisper_processor = None
        freed = True
    if freed:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        gc.collect()
        logger.info("Unloaded TTS models to free VRAM.")


async def get_available_voices(engine: str = "edge-tts") -> list[dict]:
    """Return a list of available voices for the given engine."""
    if engine == "edge-tts":
        import edge_tts
        voices = await edge_tts.list_voices()
        return [
            {"id": v["ShortName"], "name": v["FriendlyName"], "locale": v["Locale"]}
            for v in voices
        ]
    elif engine == "kokoro":
        # Kokoro built-in voice IDs (af = American Female, am = American Male, etc.)
        return [
            {"id": "af_heart", "name": "Heart (American Female)", "locale": "en-US"},
            {"id": "af_bella", "name": "Bella (American Female)", "locale": "en-US"},
            {"id": "af_nicole", "name": "Nicole (American Female)", "locale": "en-US"},
            {"id": "am_adam", "name": "Adam (American Male)", "locale": "en-US"},
            {"id": "am_michael", "name": "Michael (American Male)", "locale": "en-US"},
            {"id": "bf_emma", "name": "Emma (British Female)", "locale": "en-GB"},
            {"id": "bm_george", "name": "George (British Male)", "locale": "en-GB"},
        ]
    elif engine in {"f5-tts", "chatterbox", "qwen3-tts"}:
        # Clone engines use uploaded voice samples as the "voice".
        return [
            {"id": "__uploaded__", "name": "Use uploaded voice sample", "locale": "en-US"},
        ]
    else:
        return []


async def synthesize_speech(
    text: str,
    output_path: Path,
    engine: str = "edge-tts",
    voice: str = "en-US-AriaNeural",
    speed: float = 1.0,
    temperature: float = 0.7,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.3,
    voice_sample_path: Optional[Path] = None,
    voice_reference_text: Optional[str] = None,
    voice_samples_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    enabled_modules: Optional[list[str]] = None,
):
    """
    Synthesize text to speech using the selected engine.
    All ML engines are imported lazily so the app starts without them.

    voice_sample_path: path to a reference file, required for clone engines.
    voice_reference_text: transcript matching the F5-TTS reference clip.
    voice_samples_dir: directory containing multiple voice samples for clone engines; auto-selects best one.
    """
    global _kokoro_pipeline, _f5tts_model, _chatterbox_model, _qwen3_tts_model
    text = prepare_text_for_tts(text, engine, enabled_modules=enabled_modules)

    logger.info(f"Synthesizing with {engine}, voice={voice}, speed={speed}")

    if engine == "edge-tts":
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=_speed_to_edge_rate(speed))
        await communicate.save(str(output_path))

    elif engine == "kokoro":
        try:
            import soundfile as sf
            import numpy as np
            import torch
            _prepare_frozen_torch(torch)
            from kokoro import KPipeline
        except ImportError as e:
            import sys
            if getattr(sys, 'frozen', False):
                raise ImportError(
                    "Kokoro TTS is not available in this build. "
                    "Please use Edge TTS, or download a GPU-enabled build from GitHub."
                ) from e
            raise ImportError(
                f"Kokoro or a dependency failed to load ({e}). Run: pip install kokoro"
            ) from e

        if not torch.cuda.is_available():
            raise RuntimeError(
                "Kokoro TTS requires a CUDA-capable GPU. "
                "No GPU was detected on this system."
            )

        if _kokoro_pipeline is None:
            # Drop F5-TTS to save VRAM before loading Kokoro
            if _f5tts_model is not None:
                _f5tts_model = None
                torch.cuda.empty_cache()
            if _chatterbox_model is not None:
                _chatterbox_model = None
                torch.cuda.empty_cache()
            if _qwen3_tts_model is not None:
                _qwen3_tts_model = None
                torch.cuda.empty_cache()

            from .config import get_device_string
            device = get_device_string()
            # Check if this looks like a first-time download by inspecting HF cache
            try:
                import os
                hf_cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
                kokoro_cache = hf_cache / "hub" / "models--hexgrad--Kokoro-82M"
                is_first_run = not kokoro_cache.exists()
            except Exception:
                is_first_run = False
            if progress_cb:
                progress_cb("Downloading Kokoro model (first run, ~300 MB)…" if is_first_run else "Loading Kokoro model into GPU…", 0)

            logger.info(f"Loading Kokoro pipeline on {device}")
            # trf=False: use en_core_web_sm (smaller) instead of en_core_web_trf.
            # In a frozen build spacy.util.is_package() can return False for
            # bundled models because importlib.metadata doesn't enumerate frozen
            # packages reliably. Patch it so the download is never triggered.
            try:
                import sys as _sys
                if getattr(_sys, 'frozen', False):
                    import spacy.util as _spacy_util
                    _real_is_package = _spacy_util.is_package
                    _spacy_util.is_package = (
                        lambda name: True
                        if name in ('en_core_web_sm', 'en_core_web_trf')
                        else _real_is_package(name)
                    )
            except Exception:
                pass
            try:
                _kokoro_pipeline = KPipeline(lang_code="a", device=device, trf=False)
            except SystemExit as e:
                raise RuntimeError(
                    "Kokoro failed to load: the spaCy language model (en_core_web_sm) "
                    "could not be found or downloaded. "
                    f"(SystemExit {e})"
                ) from e

        import asyncio
        loop = asyncio.get_event_loop()

        def _infer_kokoro():
            global _kokoro_pipeline
            audio_segments = []
            for segment in segment_text_for_tts(text, engine="kokoro"):
                generator = _kokoro_pipeline(
                    segment.text, voice=voice, speed=speed, split_pattern=r"\n+"
                )
                audio_segments.extend(audio for _, _, audio in generator)
                if segment.pause_after_ms:
                    pause_samples = int(24000 * segment.pause_after_ms / 1000)
                    audio_segments.append(np.zeros(pause_samples, dtype=np.float32))
            return audio_segments

        segments = await loop.run_in_executor(None, _infer_kokoro)

        if not segments:
            raise ValueError("Kokoro produced no audio output.")
        final_audio = np.concatenate(segments)
        sf.write(str(output_path), final_audio, 24000)

    elif engine == "f5-tts":
        await _synthesize_f5tts(text, output_path, speed, temperature, voice_sample_path, voice_reference_text, voice_samples_dir, progress_cb)

    elif engine == "chatterbox":
        await _synthesize_chatterbox(
            text,
            output_path,
            speed,
            temperature,
            exaggeration,
            cfg_weight,
            voice_sample_path,
            voice_samples_dir,
            progress_cb,
        )

    elif engine == "qwen3-tts":
        await _synthesize_qwen3_tts(
            text,
            output_path,
            speed,
            temperature,
            voice_sample_path,
            voice_reference_text,
            voice_samples_dir,
            progress_cb,
        )

    else:
        raise NotImplementedError(f"TTS engine '{engine}' is not implemented.")


async def _synthesize_qwen3_tts(
    text: str,
    output_path: Path,
    speed: float = 1.0,
    temperature: float = 0.7,
    voice_sample_path: Optional[Path] = None,
    voice_reference_text: Optional[str] = None,
    voice_samples_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
):
    """Clone a reference voice with the Qwen3-TTS Base model."""
    global _qwen3_tts_model, _qwen3_tts_model_device, _kokoro_pipeline, _f5tts_model, _chatterbox_model, _chatterbox_model_device

    try:
        import numpy as np
        import soundfile as sf
        import torch
        _prepare_frozen_torch(torch)
        _prepare_qwen3_transformers()
        from qwen_tts import Qwen3TTSModel
        _prepare_qwen3_config()
        _prepare_qwen3_rope()
        _prepare_qwen3_masking()
        _prepare_qwen3_positions()
    except (ImportError, RuntimeError) as exc:
        raise ImportError(
            f"Qwen3-TTS or a dependency failed to load ({exc}). "
            "Install backend/requirements-qwen3-tts.txt, then install the "
            "PyTorch build recommended for your hardware."
        ) from exc

    if voice_samples_dir and voice_samples_dir.exists() and (
        voice_sample_path is None or not voice_sample_path.exists()
    ):
        candidates = sorted(
            path
            for path in voice_samples_dir.iterdir()
            if path.is_file() and path.suffix.lower() in (".wav", ".mp3", ".flac")
        )
        if candidates:
            voice_sample_path = max(candidates, key=lambda path: path.stat().st_size)

    if voice_sample_path is None or not voice_sample_path.exists():
        raise ValueError(
            "Qwen3-TTS requires a voice sample. Create or select a Voice Library voice first."
        )
    if not 0.5 <= speed <= 2.0:
        raise ValueError("Qwen3-TTS speed must be between 0.5 and 2.0.")
    if not 0.0 <= temperature <= 1.5:
        raise ValueError("Qwen3-TTS temperature must be between 0.0 and 1.5.")

    device = _select_chatterbox_device(torch)
    if _qwen3_tts_model is not None and _qwen3_tts_model_device != device:
        logger.info(
            "Qwen3-TTS device changed from %s to %s; reloading the model.",
            _qwen3_tts_model_device,
            device,
        )
        _qwen3_tts_model = None
        _qwen3_tts_model_device = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if _qwen3_tts_model is None:
        _kokoro_pipeline = None
        _f5tts_model = None
        _chatterbox_model = None
        _chatterbox_model_device = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if progress_cb:
            progress_cb("Loading Qwen3-TTS model (first run downloads ~4 GB)...", 0)
        supports_bfloat16 = getattr(torch.cuda, "is_bf16_supported", lambda: False)
        if device.startswith("cuda"):
            dtype = torch.bfloat16 if supports_bfloat16() else torch.float16
        else:
            dtype = torch.float32
        logger.info("Loading Qwen3-TTS model %s on %s", _QWEN3_TTS_MODEL_ID, device)
        _qwen3_tts_model = Qwen3TTSModel.from_pretrained(
            _QWEN3_TTS_MODEL_ID,
            device_map=device,
            dtype=dtype,
        )
        _qwen3_tts_model_device = device

    import asyncio

    loop = asyncio.get_event_loop()

    def _infer():
        reference_text = re.sub(r"\s+", " ", voice_reference_text or "").strip()
        prompt = _qwen3_tts_model.create_voice_clone_prompt(
            ref_audio=str(voice_sample_path),
            ref_text=reference_text or None,
            x_vector_only_mode=not bool(reference_text),
        )
        segments = segment_text_for_tts(text, engine="qwen3-tts")
        generated = []
        sample_rate = None
        for index, segment in enumerate(segments, 1):
            logger.info(
                "Qwen3-TTS synthesizing segment %d/%d (%d chars).",
                index,
                len(segments),
                len(segment.text),
            )
            generation_options = {}
            if temperature > 0:
                generation_options["temperature"] = temperature
            waveforms, segment_sample_rate = _qwen3_tts_model.generate_voice_clone(
                text=segment.text,
                language="Auto",
                voice_clone_prompt=prompt,
                **generation_options,
            )
            if not waveforms:
                continue
            waveform = np.asarray(waveforms[0], dtype=np.float32).squeeze()
            generated.append(waveform)
            sample_rate = int(segment_sample_rate)
            if segment.pause_after_ms:
                generated.append(
                    np.zeros(
                        round(sample_rate * segment.pause_after_ms / 1000),
                        dtype=np.float32,
                    )
                )
            if progress_cb:
                progress_cb(
                    f"Qwen3-TTS segment {index}/{len(segments)}",
                    round(index * 100 / len(segments)),
                )

        if not generated or sample_rate is None:
            raise ValueError("Qwen3-TTS produced no audio output.")
        combined = np.concatenate(generated).astype(np.float32, copy=False)
        if abs(speed - 1.0) > 0.001:
            import librosa

            combined = librosa.effects.time_stretch(combined, rate=float(speed))
        peak = float(np.max(np.abs(combined)))
        if peak > 0.98:
            combined *= 0.98 / peak
        return combined, sample_rate

    audio, sample_rate = await loop.run_in_executor(None, _infer)
    sf.write(str(output_path), audio, sample_rate)
    logger.info("Qwen3-TTS wrote %s", output_path)


def _select_chatterbox_device(torch_module) -> str:
    """Choose the configured accelerator, with portable MPS/CPU fallbacks."""
    from .config import load_config

    selected_gpu = load_config().selected_gpu_index
    if selected_gpu < 0:
        return "cpu"
    if torch_module.cuda.is_available():
        if selected_gpu >= torch_module.cuda.device_count():
            raise RuntimeError(
                f"CUDA device {selected_gpu} was selected, but only "
                f"{torch_module.cuda.device_count()} CUDA device(s) are available."
            )
        return f"cuda:{selected_gpu}"
    mps = getattr(getattr(torch_module, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _trim_chatterbox_edges(audio, sample_rate: int):
    """Remove generated dead air while retaining a small natural boundary."""
    import numpy as np

    mono = np.asarray(audio, dtype=np.float32).squeeze()
    active = np.flatnonzero(np.abs(mono) >= 10 ** (-48 / 20))
    if not len(active):
        return mono
    padding = int(0.06 * sample_rate)
    start = max(0, int(active[0]) - padding)
    end = min(len(mono), int(active[-1]) + padding + 1)
    return mono[start:end]


async def _synthesize_chatterbox(
    text: str,
    output_path: Path,
    speed: float = 1.0,
    temperature: float = 0.7,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.3,
    voice_sample_path: Optional[Path] = None,
    voice_samples_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
):
    """Clone a voice with Chatterbox using narration-tuned pacing defaults."""
    global _chatterbox_model, _chatterbox_model_device, _kokoro_pipeline, _f5tts_model, _qwen3_tts_model, _qwen3_tts_model_device

    try:
        import numpy as np
        import soundfile as sf
        import torch
        _prepare_frozen_torch(torch)
        from chatterbox.tts import ChatterboxTTS
    except (ImportError, RuntimeError) as exc:
        raise ImportError(
            f"Chatterbox or a dependency failed to load ({exc}). "
            "Install backend/requirements-chatterbox.txt, then install the "
            "PyTorch build recommended for your hardware."
        ) from exc

    if voice_samples_dir and voice_samples_dir.exists() and (
        voice_sample_path is None or not voice_sample_path.exists()
    ):
        candidates = sorted(
            path
            for path in voice_samples_dir.iterdir()
            if path.is_file() and path.suffix.lower() in (".wav", ".mp3", ".flac")
        )
        if candidates:
            voice_sample_path = max(candidates, key=lambda path: path.stat().st_size)

    if voice_sample_path is None or not voice_sample_path.exists():
        raise ValueError(
            "Chatterbox requires a voice sample. Create or select a Voice Library voice first."
        )
    if not 0.5 <= speed <= 2.0:
        raise ValueError("Chatterbox speed must be between 0.5 and 2.0.")
    if not 0.0 <= exaggeration <= 2.0:
        raise ValueError("Chatterbox exaggeration must be between 0.0 and 2.0.")
    if not 0.0 <= cfg_weight <= 1.0:
        raise ValueError("Chatterbox CFG weight must be between 0.0 and 1.0.")
    if not 0.05 <= temperature <= 2.0:
        raise ValueError("Chatterbox temperature must be between 0.05 and 2.0.")

    device = _select_chatterbox_device(torch)
    if _chatterbox_model is not None and _chatterbox_model_device != device:
        logger.info(
            "Chatterbox device changed from %s to %s; reloading the model.",
            _chatterbox_model_device,
            device,
        )
        _chatterbox_model = None
        _chatterbox_model_device = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    if _chatterbox_model is None:
        if _kokoro_pipeline is not None:
            _kokoro_pipeline = None
        if _f5tts_model is not None:
            _f5tts_model = None
        if _qwen3_tts_model is not None:
            _qwen3_tts_model = None
            _qwen3_tts_model_device = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if progress_cb:
            progress_cb("Loading Chatterbox model (first run downloads ~3 GB)…", 0)
        logger.info("Loading Chatterbox on %s", device)
        _chatterbox_model = ChatterboxTTS.from_pretrained(device=device)
        _chatterbox_model_device = device

    import asyncio

    loop = asyncio.get_event_loop()

    def _infer():
        # Resemble recommends cfg_weight=0.3 when the reference speaker is
        # fast; in testing this retained identity while improving narration
        # pacing. The neutral exaggeration default avoids over-acting prose.
        _chatterbox_model.prepare_conditionals(
            str(voice_sample_path), exaggeration=exaggeration
        )
        segments = segment_text_for_tts(text, engine="chatterbox")
        generated = []
        for index, segment in enumerate(segments, 1):
            logger.info(
                "Chatterbox synthesizing segment %d/%d (%d chars).",
                index,
                len(segments),
                len(segment.text),
            )
            waveform = _chatterbox_model.generate(
                segment.text,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
            )
            audio = _trim_chatterbox_edges(
                waveform.detach().cpu().numpy(), _chatterbox_model.sr
            )
            generated.append(audio)
            if segment.pause_after_ms:
                generated.append(
                    np.zeros(
                        round(_chatterbox_model.sr * segment.pause_after_ms / 1000),
                        dtype=np.float32,
                    )
                )
            if progress_cb:
                progress_cb(
                    f"Chatterbox segment {index}/{len(segments)}",
                    round(index * 100 / len(segments)),
                )

        if not generated:
            raise ValueError("Chatterbox produced no audio output.")
        combined = np.concatenate(generated).astype(np.float32, copy=False)
        if abs(speed - 1.0) > 0.001:
            import librosa

            combined = librosa.effects.time_stretch(combined, rate=float(speed))
        peak = float(np.max(np.abs(combined)))
        if peak > 0.98:
            combined *= 0.98 / peak
        return combined, _chatterbox_model.sr

    audio, sample_rate = await loop.run_in_executor(None, _infer)
    sf.write(str(output_path), audio, sample_rate)
    logger.info("Chatterbox wrote %s", output_path)


async def _synthesize_f5tts(
    text: str,
    output_path: Path,
    speed: float = 1.0,
    temperature: float = 0.7,
    voice_sample_path: Optional[Path] = None,
    voice_reference_text: Optional[str] = None,
    voice_samples_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
):
    """
    Voice cloning via F5-TTS (https://github.com/SWivid/F5-TTS).
    Downloads the F5-TTS model on first run (~800 MB).
    voice_sample_path: WAV/MP3/FLAC reference clip to clone from.
    voice_reference_text: optional transcript matching that reference clip.
    voice_samples_dir: directory containing multiple voice samples; auto-selects best one.
    """
    global _f5tts_model, _chatterbox_model, _qwen3_tts_model, _qwen3_tts_model_device
    try:
        import torch
        import soundfile as sf
        import numpy as np
        _prepare_frozen_torch(torch)
        # F5-TTS calls torchaudio.load internally, which dispatches to
        # torchcodec on torchaudio >= 2.9.  torchcodec needs FFmpeg DLLs that
        # the frozen build lacks, so route torchaudio I/O through soundfile
        # before importing F5-TTS.
        _install_torchaudio_soundfile_shim()
        from f5_tts.api import F5TTS
    except (ImportError, RuntimeError) as e:
        import sys
        if getattr(sys, 'frozen', False):
            raise ImportError(
                "F5-TTS (voice cloning) is not available in this build. "
                "Please use Edge TTS, or download a GPU-enabled build from GitHub."
            ) from e
        raise ImportError(
            f"F5-TTS or a dependency failed to load ({e}). Run: pip install f5-tts"
        ) from e

    # Auto-select best sample from directory if provided
    if voice_samples_dir and voice_samples_dir.exists() and (voice_sample_path is None or not voice_sample_path.exists()):
        candidates = sorted(
            p for p in voice_samples_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".wav", ".mp3", ".flac")
        )
        if candidates:
            # Pick longest sample (proxy for highest quality/clarity)
            voice_sample_path = max(candidates, key=lambda p: p.stat().st_size)
            logger.info(f"Auto-selected voice sample: {voice_sample_path.name}")
    
    if voice_sample_path is None or not voice_sample_path.exists():
        raise ValueError(
            "F5-TTS requires a voice sample. Upload a .wav file in Step 3 first."
        )

    if not torch.cuda.is_available():
        raise RuntimeError(
            "F5-TTS (voice cloning) requires a CUDA-capable GPU. "
            "No GPU was detected on this system."
        )

    if _f5tts_model is None:
        # Drop Kokoro to save VRAM before loading F5-TTS
        global _kokoro_pipeline
        if _kokoro_pipeline is not None:
            _kokoro_pipeline = None
            torch.cuda.empty_cache()
        if _chatterbox_model is not None:
            _chatterbox_model = None
            torch.cuda.empty_cache()
        if _qwen3_tts_model is not None:
            _qwen3_tts_model = None
            _qwen3_tts_model_device = None
            torch.cuda.empty_cache()

        from .config import get_device_string
        device = get_device_string()
        # Detect first-run download
        try:
            import os
            hf_cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
            f5_cache = hf_cache / "hub" / "models--SWivid--F5-TTS"
            is_first_run = not f5_cache.exists()
        except Exception:
            is_first_run = False
        if progress_cb:
            progress_cb("Downloading F5-TTS model (first run, ~800 MB)…" if is_first_run else "Loading F5-TTS model into GPU…", 0)

        logger.info(f"Loading F5-TTS model on {device} (first run downloads ~800 MB)…")
        _f5tts_model = F5TTS(device=device)
        logger.info(f"F5-TTS loaded on {device}")

    logger.info(f"F5-TTS cloning from {voice_sample_path}")

    # F5-TTS inference — runs in a thread to avoid blocking the event loop
    import asyncio
    loop = asyncio.get_event_loop()

    def _infer():
        # Transcription is done with Whisper's processor + model on a numpy
        # array (NOT the transformers pipeline), which never touches
        # torchcodec-backed file loading.  An accurate ref_text is also
        # required, not just cosmetic: F5-TTS estimates generated duration as
        #   ref_audio_len / len(ref_text) * len(gen_text)
        # so a missing/one-char ref_text makes the duration explode past the
        # model's positional limit and crashes inference.
        global _whisper_model, _whisper_processor
        import soundfile as sf
        import numpy as np
        import torch
        import inspect
        from f5_tts.infer.utils_infer import preprocess_ref_audio_text

        reference_text_override = _normalize_f5_reference_text(voice_reference_text)
        preprocess_text = reference_text_override or _F5_REFERENCE_PLACEHOLDER_TEXT
        try:
            source_info = sf.info(str(voice_sample_path))
            source_duration_seconds = (
                source_info.frames / float(source_info.samplerate)
                if source_info.samplerate
                else None
            )
        except Exception:
            source_duration_seconds = None

        preprocessing_messages = []

        def _log_preprocessing(message):
            preprocessing_messages.append(str(message))
            logger.info(message)

        ref_file, _ = preprocess_ref_audio_text(
            str(voice_sample_path),
            preprocess_text,
            show_info=_log_preprocessing,
        )

        audio_arr, orig_sr = sf.read(ref_file, dtype="float32")
        if audio_arr.ndim > 1:
            audio_arr = audio_arr.mean(axis=1)
        reference_duration_seconds = len(audio_arr) / float(orig_sr) if orig_sr else 0.0
        reference_was_clipped = _f5_reference_was_clipped(
            source_duration_seconds,
            reference_duration_seconds,
            preprocessing_messages,
        )
        if reference_was_clipped:
            logger.info(
                "F5-TTS clipped the reference audio; transcribing the exact processed "
                "clip instead of reusing the full source transcript."
            )

        # Resample the full reference clip to 16 kHz for Whisper when the user
        # did not provide a usable transcript. The clip has already gone
        # through F5's reference preprocessing, so ASR and ref_text describe
        # the same audio that conditions the model.
        asr_arr = audio_arr
        if orig_sr != 16000:
            n_out = int(round(len(audio_arr) * 16000 / orig_sr))
            indices = np.round(
                np.linspace(0, len(audio_arr) - 1, n_out)
            ).astype(int)
            asr_arr = audio_arr[indices]

        transcribed_ref_text = ""
        if (
            reference_text_override
            and not reference_was_clipped
            and _is_plausible_f5_reference_text(
                reference_text_override,
                reference_duration_seconds,
            )
        ):
            logger.info("Using saved F5-TTS reference transcript.")
        else:
            try:
                from transformers import WhisperProcessor, WhisperForConditionalGeneration

                if _whisper_processor is None or _whisper_model is None:
                    _whisper_processor = WhisperProcessor.from_pretrained(
                        "openai/whisper-base"
                    )
                    _whisper_model = WhisperForConditionalGeneration.from_pretrained(
                        "openai/whisper-base"
                    )
                    if torch.cuda.is_available():
                        _whisper_model = _whisper_model.to("cuda")

                inputs = _whisper_processor(
                    asr_arr, sampling_rate=16000, return_tensors="pt"
                )
                input_features = inputs.input_features
                if torch.cuda.is_available():
                    input_features = input_features.to("cuda")
                with torch.no_grad():
                    generated_ids = _whisper_model.generate(input_features)
                transcribed_ref_text = _whisper_processor.batch_decode(
                    generated_ids, skip_special_tokens=True
                )[0].strip()
                logger.info(f"Pre-transcribed F5 reference clip: {transcribed_ref_text!r}")
            except Exception as exc:
                transcribed_ref_text = ""
                logger.warning(f"Reference audio pre-transcription failed ({exc}).")

        ref_text = _select_f5_reference_text(
            reference_text_override,
            transcribed_ref_text,
            reference_duration_seconds,
            reference_was_clipped=reference_was_clipped,
        )

        generated = []
        sample_rate = None
        segments = segment_text_for_tts(text, engine="f5-tts")
        for idx, segment in enumerate(segments):
            logger.info(
                f"F5-TTS synthesizing segment {idx + 1}/{len(segments)} "
                f"({len(segment.text)} chars)."
            )
            infer_kwargs = {
                "ref_file": ref_file,
                "ref_text": ref_text,
                "gen_text": segment.text,
                "speed": speed,
            }
            if "temperature" in inspect.signature(_f5tts_model.infer).parameters:
                infer_kwargs["temperature"] = temperature
            wav, sr, _ = _f5tts_model.infer(**infer_kwargs)
            sample_rate = sr
            wav_arr = np.asarray(wav)
            generated.append(wav_arr)
            if segment.pause_after_ms:
                pause_samples = int(sr * segment.pause_after_ms / 1000)
                generated.append(np.zeros(pause_samples, dtype=wav_arr.dtype))

        if not generated or sample_rate is None:
            raise ValueError("F5-TTS produced no audio output.")
        return np.concatenate(generated), sample_rate

    wav, sr = await loop.run_in_executor(None, _infer)

    import soundfile as sf
    sf.write(str(output_path), wav, sr)
    logger.info(f"F5-TTS wrote {output_path}")


def _speed_to_edge_rate(speed: float) -> str:
    """Convert a speed multiplier (0.5–2.0) to Edge-TTS rate string like '+20%'."""
    percent = int((speed - 1.0) * 100)
    return f"{percent:+d}%"
