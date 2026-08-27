"""Persistent Kokoro synthesis worker for the managed CUDA runtime."""

from __future__ import annotations

import json
from pathlib import Path
import sys

_pipeline = None
_pipeline_device = None


def _emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _progress(request_id: str, message: str, progress: int) -> None:
    _emit({"request_id": request_id, "type": "progress", "message": message, "progress": progress})


def _load_pipeline(request_id: str, device: str):
    global _pipeline, _pipeline_device
    import torch
    from kokoro import KPipeline

    if not torch.version.cuda or not torch.cuda.is_available():
        raise RuntimeError("Kokoro requires a working CUDA-enabled PyTorch runtime.")
    if not device.startswith("cuda"):
        raise RuntimeError("Kokoro does not support CPU fallback in narratible.")
    if _pipeline is not None and _pipeline_device == device:
        return _pipeline
    _progress(request_id, "Loading Kokoro model into GPU...", 10)
    _pipeline = KPipeline(lang_code="a", device=device, trf=False)
    _pipeline_device = device
    return _pipeline


def _synthesize(request: dict) -> None:
    import numpy as np
    import soundfile as sf

    request_id = request["request_id"]
    pipeline = _load_pipeline(request_id, request["device"])
    audio_segments = []
    segments = request.get("segments") or [{"text": request["text"], "pause_after_ms": 0}]
    for index, segment in enumerate(segments, start=1):
        _progress(request_id, f"Synthesizing segment {index} of {len(segments)}...", 10 + int(80 * index / len(segments)))
        generator = pipeline(
            segment["text"],
            voice=request["voice"],
            speed=float(request["speed"]),
            split_pattern=r"\n+",
        )
        audio_segments.extend(audio for _, _, audio in generator)
        pause_after_ms = int(segment.get("pause_after_ms", 0))
        if pause_after_ms:
            audio_segments.append(np.zeros(int(24000 * pause_after_ms / 1000), dtype=np.float32))
    if not audio_segments:
        raise ValueError("Kokoro produced no audio output.")
    output_path = Path(request["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), np.concatenate(audio_segments), 24000)
    _emit({"request_id": request_id, "type": "result", "output_path": str(output_path)})


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("action") == "shutdown":
                return 0
            if request.get("action") != "synthesize":
                raise ValueError(f"Unknown worker action: {request.get('action')}")
            _synthesize(request)
        except Exception as exc:
            _emit(
                {
                    "request_id": request.get("request_id") if "request" in locals() else None,
                    "type": "error",
                    "message": str(exc),
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())