"""Persistent Chatterbox synthesis worker for the managed CUDA runtime."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

_model = None
_model_device = None


def _emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _progress(request_id: str, message: str, progress: int) -> None:
    _emit({"request_id": request_id, "type": "progress", "message": message, "progress": progress})


def _trim_edges(audio, sample_rate: int):
    import numpy as np

    mono = np.asarray(audio, dtype=np.float32).squeeze()
    active = np.flatnonzero(np.abs(mono) >= 10 ** (-48 / 20))
    if not len(active):
        return mono
    padding = int(0.06 * sample_rate)
    return mono[max(0, int(active[0]) - padding):min(len(mono), int(active[-1]) + padding + 1)]


def _load_model(request_id: str, device: str):
    global _model, _model_device
    import torch
    from chatterbox.tts import ChatterboxTTS

    if not torch.version.cuda or not torch.cuda.is_available() or not device.startswith("cuda"):
        raise RuntimeError("Chatterbox requires a working CUDA-enabled PyTorch runtime.")
    if _model is not None and _model_device == device:
        return _model
    _progress(request_id, "Loading Chatterbox model into GPU...", 10)
    _model = ChatterboxTTS.from_pretrained(device=device)
    _model_device = device
    return _model


def _build_atempo_filter(speed: float) -> str:
    """Chain atempo filters so any speed multiplier (even <0.5 or >2.0) works cleanly."""
    speed = float(speed)
    if speed <= 0:
        return "atempo=1.0"
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def _apply_time_stretch(audio, sample_rate: int, speed: float):
    import numpy as np

    speed = float(speed)
    if abs(speed - 1.0) <= 0.001:
        return audio

    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe is not None:
        try:
            import tempfile
            import soundfile as sf

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                in_wav = tmp_path / "in.wav"
                out_wav = tmp_path / "out.wav"
                sf.write(str(in_wav), audio, sample_rate)

                filter_chain = _build_atempo_filter(speed)
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

                cmd = [
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-i", str(in_wav),
                    "-filter:a", filter_chain,
                    str(out_wav),
                ]
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    **kwargs,
                )
                if proc.returncode == 0 and out_wav.is_file():
                    stretched, _ = sf.read(str(out_wav), dtype="float32")
                    return np.asarray(stretched, dtype=np.float32).squeeze()
                sys.stderr.write(
                    f"FFmpeg atempo warning: code={proc.returncode}, stderr={proc.stderr}\n"
                )
        except Exception as exc:
            sys.stderr.write(f"FFmpeg atempo failed, falling back to librosa: {exc}\n")

    try:
        import librosa

        return librosa.effects.time_stretch(audio, rate=speed)
    except Exception as exc:
        sys.stderr.write(f"Librosa time_stretch fallback failed: {exc}\n")
        return audio


def _synthesize(request: dict) -> None:
    import numpy as np
    import soundfile as sf

    request_id = request["request_id"]
    model = _load_model(request_id, request["device"])
    reference_path = Path(request["reference_path"])
    if not reference_path.is_file():
        raise ValueError("Chatterbox requires an existing voice reference file.")
    exaggeration = float(request.get("exaggeration", 0.5))
    cfg_weight = float(request.get("cfg_weight", 0.3))
    temperature = float(request.get("temperature", 0.7))
    speed = float(request.get("speed", 1.0))
    model.prepare_conditionals(str(reference_path), exaggeration=exaggeration)
    segments = request["segments"]
    generated = []
    for index, segment in enumerate(segments, start=1):
        _progress(request_id, f"Chatterbox segment {index} of {len(segments)}...", 10 + int(80 * index / len(segments)))
        waveform = model.generate(
            segment["text"],
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
        )
        generated.append(_trim_edges(waveform.detach().cpu().numpy(), model.sr))
        pause_after_ms = int(segment.get("pause_after_ms", 0))
        if pause_after_ms:
            generated.append(np.zeros(round(model.sr * pause_after_ms / 1000), dtype=np.float32))
    if not generated:
        raise ValueError("Chatterbox produced no audio output.")
    combined = np.concatenate(generated).astype(np.float32, copy=False)
    combined = _apply_time_stretch(combined, model.sr, speed)
    peak = float(np.max(np.abs(combined)))
    if peak > 0.98:
        combined *= 0.98 / peak
    output_path = Path(request["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), combined, model.sr)
    _emit({"request_id": request_id, "type": "result", "output_path": str(output_path)})


def main() -> int:
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if request.get("action") == "shutdown":
                return 0
            if request.get("action") != "synthesize":
                raise ValueError(f"Unknown worker action: {request.get('action')}")
            _synthesize(request)
        except Exception as exc:
            _emit({"request_id": request.get("request_id"), "type": "error", "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())