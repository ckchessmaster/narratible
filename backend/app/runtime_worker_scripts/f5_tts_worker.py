"""Persistent F5-TTS synthesis worker for the managed CUDA runtime."""

from __future__ import annotations

import json
from pathlib import Path
import sys

_model = None
_model_device = None


def _emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _progress(request_id: str, message: str, progress: int) -> None:
    _emit({"request_id": request_id, "type": "progress", "message": message, "progress": progress})


def _install_torchaudio_shim() -> None:
    import soundfile as sf
    import torch
    import torchaudio

    def load(filepath, *_args, **_kwargs):
        data, sample_rate = sf.read(str(filepath), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), sample_rate

    def save(filepath, source, sample_rate, *_args, **_kwargs):
        if hasattr(source, "detach"):
            source = source.detach().cpu().numpy()
        sf.write(str(filepath), source.T, int(sample_rate))

    torchaudio.load = load
    torchaudio.save = save


def _load_model(request_id: str, device: str):
    global _model, _model_device
    import torch

    if not torch.version.cuda or not torch.cuda.is_available() or not device.startswith("cuda"):
        raise RuntimeError("F5-TTS requires a working CUDA-enabled PyTorch runtime.")
    if _model is not None and _model_device == device:
        return _model
    _install_torchaudio_shim()
    from f5_tts.api import F5TTS

    _progress(request_id, "Loading F5-TTS model into GPU...", 10)
    _model = F5TTS(device=device)
    _model_device = device
    return _model


def _synthesize(request: dict) -> None:
    import numpy as np
    import soundfile as sf

    request_id = request["request_id"]
    model = _load_model(request_id, request["device"])
    reference_path = Path(request["reference_path"])
    if not reference_path.is_file():
        raise ValueError("F5-TTS requires an existing voice reference file.")
    reference_text = (request.get("reference_text") or "").strip()
    segments = request["segments"]
    generated = []
    sample_rate = None
    for index, segment in enumerate(segments, start=1):
        _progress(request_id, f"F5-TTS segment {index} of {len(segments)}...", 10 + int(80 * index / len(segments)))
        waveform, sample_rate, _spectrogram = model.infer(
            ref_file=str(reference_path),
            ref_text=reference_text,
            gen_text=segment["text"],
            speed=float(request.get("speed", 1.0)),
        )
        waveform = np.asarray(waveform)
        generated.append(waveform)
        pause_after_ms = int(segment.get("pause_after_ms", 0))
        if pause_after_ms:
            generated.append(np.zeros(int(sample_rate * pause_after_ms / 1000), dtype=waveform.dtype))
    if not generated or sample_rate is None:
        raise ValueError("F5-TTS produced no audio output.")
    output_path = Path(request["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), np.concatenate(generated), sample_rate)
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