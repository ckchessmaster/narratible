import logging
import sys
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

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
_whisper_model = None
_whisper_processor = None

def unload_tts():
    """Explicitly unload TTS models to free up VRAM."""
    global _kokoro_pipeline, _f5tts_model, _whisper_model, _whisper_processor
    import gc
    freed = False
    if _kokoro_pipeline is not None:
        _kokoro_pipeline = None
        freed = True
    if _f5tts_model is not None:
        _f5tts_model = None
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
    elif engine == "f5-tts":
        # F5-TTS uses uploaded voice samples as the "voice" — return a sentinel
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
    voice_sample_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
):
    """
    Synthesize text to speech using the selected engine.
    All ML engines are imported lazily so the app starts without them.

    voice_sample_path: path to a .wav reference file, required for f5-tts.
    """
    # Strip footnote markers like [^1] and the footnote definitions at the bottom
    import re
    # Remove inline footnote markers
    cleaned_text = re.sub(r'\[\^\d+\]', '', text)
    # Remove footnote definitions at the bottom (e.g. [^1]: ...)
    cleaned_text = re.sub(r'(?m)^\[\^\d+\]:.*$', '', cleaned_text).strip()

    text = cleaned_text

    logger.info(f"Synthesizing with {engine}, voice={voice}, speed={speed}")

    if engine == "edge-tts":
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=_speed_to_edge_rate(speed))
        await communicate.save(str(output_path))

    elif engine == "kokoro":
        global _kokoro_pipeline
        try:
            from kokoro import KPipeline
            import soundfile as sf
            import numpy as np
            import torch
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
            global _f5tts_model
            if _f5tts_model is not None:
                _f5tts_model = None
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
            generator = _kokoro_pipeline(
                text, voice=voice, speed=speed, split_pattern=r"\n+"
            )
            segs = [audio for _, _, audio in generator]
            return segs

        segments = await loop.run_in_executor(None, _infer_kokoro)

        if not segments:
            raise ValueError("Kokoro produced no audio output.")
        final_audio = np.concatenate(segments)
        sf.write(str(output_path), final_audio, 24000)

    elif engine == "f5-tts":
        await _synthesize_f5tts(text, output_path, speed, voice_sample_path, progress_cb)

    else:
        raise NotImplementedError(f"TTS engine '{engine}' is not implemented.")


async def _synthesize_f5tts(
    text: str,
    output_path: Path,
    speed: float = 1.0,
    voice_sample_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
):
    """
    Voice cloning via F5-TTS (https://github.com/SWivid/F5-TTS).
    Downloads the F5-TTS model on first run (~800 MB).
    voice_sample_path: a short (~5-15s) WAV/MP3 reference clip to clone from.
    """
    global _f5tts_model
    try:
        import sys as _sys
        import torch
        import soundfile as sf
        import numpy as np
        # torch.jit.script no-op is now applied in the runtime hook before
        # any ML library loads. The guard here is a belt-and-suspenders
        # fallback for non-frozen (dev) runs where the hook doesn't execute.
        if getattr(_sys, 'frozen', False) and not getattr(torch.jit, '_narratible_noop', False):
            torch.jit.script = lambda fn, *a, **k: fn
            torch.jit._narratible_noop = True
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
        # F5-TTS clips the reference *audio* to ~12s internally but uses
        # whatever ref_text we pass.  If we transcribe a longer clip in full,
        # the text describes far more speech than the clipped audio contains,
        # which breaks alignment and produces garbled output.  So we clip the
        # audio to ~10s ourselves, transcribe exactly that clip, and hand the
        # clipped file to F5-TTS — keeping audio and text in sync.
        #
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
        import tempfile
        import os
        from transformers import WhisperProcessor, WhisperForConditionalGeneration

        MAX_REF_SECONDS = 10

        audio_arr, orig_sr = sf.read(str(voice_sample_path), dtype="float32")
        if audio_arr.ndim > 1:
            audio_arr = audio_arr.mean(axis=1)

        max_samples = int(MAX_REF_SECONDS * orig_sr)
        was_clipped = len(audio_arr) > max_samples
        clipped = audio_arr[:max_samples] if was_clipped else audio_arr

        # Reference file handed to F5-TTS: a temp clip if we trimmed it,
        # otherwise the original file untouched.
        ref_file = str(voice_sample_path)
        tmp_ref = None
        if was_clipped:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_ref = tmp.name
            tmp.close()
            sf.write(tmp_ref, clipped, orig_sr)
            ref_file = tmp_ref

        try:
            # Resample the clip to 16 kHz for Whisper.
            asr_arr = clipped
            if orig_sr != 16000:
                n_out = int(round(len(clipped) * 16000 / orig_sr))
                indices = np.round(
                    np.linspace(0, len(clipped) - 1, n_out)
                ).astype(int)
                asr_arr = clipped[indices]

            ref_text = ""
            try:
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
                ref_text = _whisper_processor.batch_decode(
                    generated_ids, skip_special_tokens=True
                )[0].strip()
                logger.info(
                    f"Pre-transcribed reference "
                    f"({'~' + str(MAX_REF_SECONDS) + 's clip' if was_clipped else 'full'}): "
                    f"{ref_text!r}"
                )
            except Exception as exc:
                ref_text = ""
                logger.warning(f"Reference audio pre-transcription failed ({exc}).")

            # Guard against a missing/too-short transcription: F5-TTS divides
            # the duration estimate by len(ref_text), so a very short ref_text
            # blows up the generated length.  Fall back to a neutral sentence
            # rather than a single character.
            if len(ref_text) < 4:
                ref_text = "This is a reference sample of the speaker's voice."
                logger.warning(
                    "Using neutral fallback ref_text to keep F5-TTS duration sane."
                )

            wav, sr, _ = _f5tts_model.infer(
                ref_file=ref_file,
                ref_text=ref_text,
                gen_text=text,
                speed=speed,
            )
            return wav, sr
        finally:
            if tmp_ref and os.path.exists(tmp_ref):
                try:
                    os.remove(tmp_ref)
                except OSError:
                    pass

    wav, sr = await loop.run_in_executor(None, _infer)

    sf.write(str(output_path), wav, sr)
    logger.info(f"F5-TTS wrote {output_path}")


def _speed_to_edge_rate(speed: float) -> str:
    """Convert a speed multiplier (0.5–2.0) to Edge-TTS rate string like '+20%'."""
    percent = int((speed - 1.0) * 100)
    return f"{percent:+d}%"
