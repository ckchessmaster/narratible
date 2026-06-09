import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cached pipeline instances — loaded lazily to avoid startup cost
_kokoro_pipeline = None
_f5tts_model = None

def unload_tts():
    """Explicitly unload TTS models to free up VRAM."""
    global _kokoro_pipeline, _f5tts_model
    import gc
    freed = False
    if _kokoro_pipeline is not None:
        _kokoro_pipeline = None
        freed = True
    if _f5tts_model is not None:
        _f5tts_model = None
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
        except ImportError:
            raise ImportError(
                "Kokoro is not installed. Run: pip install kokoro"
            )

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # Reinitialise if the cached pipeline is on the wrong device
        if _kokoro_pipeline is None or getattr(_kokoro_pipeline, '_device', None) != device:
            # Drop F5-TTS to save VRAM if caching Kokoro
            global _f5tts_model
            if _f5tts_model is not None:
                _f5tts_model = None
                torch.cuda.empty_cache()
            
            logger.info(f"Loading Kokoro pipeline on {device}")
            _kokoro_pipeline = KPipeline(lang_code="a", device=device)
            _kokoro_pipeline._device = device  # tag for mismatch detection

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
        await _synthesize_f5tts(text, output_path, speed, voice_sample_path)

    else:
        raise NotImplementedError(f"TTS engine '{engine}' is not implemented.")


async def _synthesize_f5tts(
    text: str,
    output_path: Path,
    speed: float = 1.0,
    voice_sample_path: Optional[Path] = None,
):
    """
    Voice cloning via F5-TTS (https://github.com/SWivid/F5-TTS).
    Downloads the F5-TTS model on first run (~800 MB).
    voice_sample_path: a short (~5-15s) WAV/MP3 reference clip to clone from.
    """
    global _f5tts_model
    try:
        import torch
        import soundfile as sf
        import numpy as np
        from f5_tts.api import F5TTS
    except ImportError:
        raise ImportError(
            "F5-TTS is not installed. Run: pip install f5-tts"
        )

    if voice_sample_path is None or not voice_sample_path.exists():
        raise ValueError(
            "F5-TTS requires a voice sample. Upload a .wav file in Step 3 first."
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"F5-TTS device: {device}")

    # Reinitialise if the cached model is on the wrong device (e.g. first run was CPU)
    cached_device = getattr(_f5tts_model, '_echo_device', None)
    if _f5tts_model is None or cached_device != device:
        # Drop Kokoro to save VRAM if caching F5-TTS
        global _kokoro_pipeline
        if _kokoro_pipeline is not None:
            _kokoro_pipeline = None
            torch.cuda.empty_cache()

        logger.info(f"Loading F5-TTS model on {device} (first run downloads ~800 MB)…")
        _f5tts_model = F5TTS(device=device)
        _f5tts_model._echo_device = device  # tag for mismatch detection
        logger.info(f"F5-TTS loaded on {device}")

    logger.info(f"F5-TTS cloning from {voice_sample_path}")

    # F5-TTS inference — runs in a thread to avoid blocking the event loop
    import asyncio
    loop = asyncio.get_event_loop()

    def _infer():
        wav, sr, _ = _f5tts_model.infer(
            ref_file=str(voice_sample_path),
            ref_text="",        # auto-transcribe reference
            gen_text=text,
            speed=speed,
        )
        return wav, sr

    wav, sr = await loop.run_in_executor(None, _infer)

    sf.write(str(output_path), wav, sr)
    logger.info(f"F5-TTS wrote {output_path}")


def _speed_to_edge_rate(speed: float) -> str:
    """Convert a speed multiplier (0.5–2.0) to Edge-TTS rate string like '+20%'."""
    percent = int((speed - 1.0) * 100)
    return f"{percent:+d}%"
