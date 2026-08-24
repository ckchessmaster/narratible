"""Optional AI cleanup for Voice Library reference clips.

The implementation intentionally imports PyTorch and Resemble Enhance lazily:
the normal Voice Library and TTS paths must keep working when the optional
model is not installed.
"""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger(__name__)


class VoiceEnhancementUnavailableError(RuntimeError):
    """Raised when the optional enhancement runtime is not installed."""


class VoiceEnhancementDeviceError(ValueError):
    """Raised when an explicitly requested accelerator is unavailable."""


def resolve_enhancement_device(requested: str = "auto", cuda_index: int = 0) -> str:
    """Resolve ``auto``, ``cuda``, ``mps``, or ``cpu`` to a torch device.

    ``cuda`` uses narratible's configured GPU index. ``cuda:N`` is accepted by
    the API as well, which makes the helper useful outside the UI.
    """
    try:
        import torch
    except ImportError as exc:
        raise VoiceEnhancementUnavailableError(
            "Voice enhancement needs PyTorch and Resemble Enhance. See the optional setup in README.md."
        ) from exc

    requested = (requested or "auto").strip().lower()
    if requested == "auto":
        if (
            cuda_index >= 0
            and torch.cuda.is_available()
            and cuda_index < torch.cuda.device_count()
        ):
            return f"cuda:{cuda_index}"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        requested = f"cuda:{max(cuda_index, 0)}"
    if requested.startswith("cuda:"):
        if not torch.cuda.is_available():
            raise VoiceEnhancementDeviceError("CUDA was requested, but no CUDA device is available.")
        try:
            index = int(requested.split(":", 1)[1])
        except ValueError as exc:
            raise VoiceEnhancementDeviceError("CUDA device must look like 'cuda' or 'cuda:0'.") from exc
        if index < 0 or index >= torch.cuda.device_count():
            raise VoiceEnhancementDeviceError(f"CUDA device {index} is not available.")
        return f"cuda:{index}"
    if requested == "mps":
        mps = getattr(torch.backends, "mps", None)
        if mps is None or not mps.is_available():
            raise VoiceEnhancementDeviceError("Apple Metal (MPS) was requested, but it is not available.")
        return "mps"
    raise VoiceEnhancementDeviceError("Enhancement device must be auto, cuda, mps, cpu, or cuda:N.")


def _enhance_in_process(
    source_path: Path,
    output_path: Path,
    *,
    device: str = "auto",
    cuda_index: int = 0,
    nfe: int = 32,
) -> str:
    """Denoise and restore a mono reference clip with Resemble Enhance.

    Returns the device actually used. In ``auto`` mode an accelerator runtime
    failure is retried once on CPU, which is particularly useful on MPS where
    model/operator support varies between PyTorch releases.
    """
    if not 1 <= nfe <= 128:
        raise ValueError("Enhancement quality (NFE) must be between 1 and 128.")
    try:
        import soundfile as sf
        import torch
        from resemble_enhance.enhancer.inference import enhance
    except (ImportError, RuntimeError) as exc:
        raise VoiceEnhancementUnavailableError(
            "AI voice enhancement is optional and is not installed. "
            "Install Resemble Enhance as described in README.md, then restart narratible."
        ) from exc

    waveform, sample_rate = sf.read(str(source_path), dtype="float32", always_2d=True)
    if waveform.size == 0:
        raise ValueError("The reference audio is empty.")
    mono = torch.from_numpy(waveform.mean(axis=1))
    resolved = resolve_enhancement_device(device, cuda_index)

    def _run(target: str):
        return enhance(dwav=mono, sr=sample_rate, device=target, nfe=nfe)

    try:
        enhanced, enhanced_rate = _run(resolved)
    except (RuntimeError, NotImplementedError) as exc:
        if device.lower() != "auto" or resolved == "cpu":
            raise
        logger.warning("Voice enhancement failed on %s; retrying on CPU: %s", resolved, exc)
        resolved = "cpu"
        enhanced, enhanced_rate = _run(resolved)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), enhanced.detach().cpu().numpy(), enhanced_rate, subtype="PCM_16")
    logger.info("Enhanced voice reference %s on %s", source_path.name, resolved)
    return resolved


def enhance_reference_audio(
    source_path: Path,
    output_path: Path,
    *,
    device: str = "auto",
    cuda_index: int = 0,
    nfe: int = 32,
) -> str:
    """Run enhancement in an optional, isolated Python environment.

    Resemble Enhance 0.0.1 pins PyTorch 2.1 while narratible's local TTS
    engines may need a newer CUDA build. A subprocess keeps those dependency
    stacks independent. Set ``NARRATIBLE_VOICE_ENHANCER_PYTHON`` to the Python
    executable in the enhancement virtual environment; the current interpreter
    is the convenient default for developers who have compatible dependencies.
    """
    enhancer_python = os.environ.get("NARRATIBLE_VOICE_ENHANCER_PYTHON", sys.executable)
    command = [
        enhancer_python,
        str(Path(__file__).resolve()),
        "--source", str(source_path),
        "--output", str(output_path),
        "--device", device,
        "--cuda-index", str(cuda_index),
        "--nfe", str(nfe),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VoiceEnhancementUnavailableError(
            f"Could not start the configured voice enhancement Python: {enhancer_python}"
        ) from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        detail = message[-1] if message else "The enhancement runtime exited unexpectedly."
        if result.returncode == 3:
            raise VoiceEnhancementDeviceError(detail)
        if result.returncode == 4:
            raise ValueError(detail)
        raise VoiceEnhancementUnavailableError(detail)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])["device"]
    except (IndexError, KeyError, json.JSONDecodeError) as exc:
        raise VoiceEnhancementUnavailableError(
            "The enhancement runtime returned an invalid response."
        ) from exc


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Narratible voice reference enhancement worker")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cuda-index", type=int, default=0)
    parser.add_argument("--nfe", type=int, default=32)
    args = parser.parse_args()
    try:
        used = _enhance_in_process(
            args.source,
            args.output,
            device=args.device,
            cuda_index=args.cuda_index,
            nfe=args.nfe,
        )
    except VoiceEnhancementDeviceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"device": used}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
