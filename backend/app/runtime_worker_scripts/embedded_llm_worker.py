"""Persistent Embedded LLM inference worker for the managed CUDA runtime."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
from typing import Any

# Disable symbolic links on Windows to avoid WinError 448 (untrusted mount point traversal)
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

_pipeline = None
_pipeline_key: tuple[str, str, bool, str | None] | None = None


def _materialize_symlinks_in_cache(model_name: str) -> None:
    """On Windows, symbolic links in the Hugging Face cache trigger
    [WinError 448] (The path cannot be traversed because it contains an untrusted mount point)
    when accessed from windowed desktop apps subject to ProcessReparsePointTraversalPolicy.
    Replace any reparse points in the model cache with hard links (or copies).
    """
    if os.name != "nt":
        return
    import shutil
    try:
        import huggingface_hub.constants as constants
        from huggingface_hub.file_download import repo_folder_name

        cache_dir = os.environ.get("HF_HUB_CACHE") or constants.HF_HUB_CACHE
        repo_cache = os.path.join(cache_dir, repo_folder_name(repo_id=model_name, repo_type="model"))
        if not os.path.isdir(repo_cache):
            return

        snapshots_dir = os.path.join(repo_cache, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return

        for root, _dirs, files in os.walk(snapshots_dir):
            for f in files:
                path = os.path.join(root, f)
                try:
                    if os.path.islink(path):
                        raw_target = os.readlink(path)
                        abs_target = os.path.normpath(os.path.join(os.path.dirname(path), raw_target))
                        if os.path.isfile(abs_target):
                            os.unlink(path)
                            try:
                                os.link(abs_target, path)
                            except OSError:
                                shutil.copy2(abs_target, path)
                except Exception:
                    pass
    except Exception:
        pass


def _emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _progress(request_id: str, message: str, progress: int) -> None:
    _emit({"request_id": request_id, "type": "progress", "message": message, "progress": progress})


def _unload_pipeline() -> None:
    global _pipeline, _pipeline_key
    if _pipeline is not None:
        try:
            if hasattr(_pipeline, "model"):
                del _pipeline.model
            if hasattr(_pipeline, "tokenizer"):
                del _pipeline.tokenizer
        except Exception:
            pass
        del _pipeline
        _pipeline = None
        _pipeline_key = None
    try:
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _get_pipeline(
    request_id: str,
    model_name: str,
    device: str,
    use_4bit_quantization: bool = False,
    hf_token: str | None = None,
):
    global _pipeline, _pipeline_key
    key = (model_name, device, use_4bit_quantization, hf_token)
    if _pipeline is not None and _pipeline_key == key:
        return _pipeline

    _unload_pipeline()

    import torch
    from transformers import pipeline

    if not torch.version.cuda or not torch.cuda.is_available():
        raise RuntimeError("The embedded LLM requires a CUDA-capable GPU runtime.")

    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    short_name = model_name.split("/")[-1]
    _progress(request_id, f"Loading model '{short_name}' into GPU VRAM...", 20)

    pipe_kwargs: dict[str, Any] = {
        "task": "text-generation",
        "model": model_name,
        "dtype": torch.float16,
        "token": hf_token or None,
    }

    if use_4bit_quantization:
        _progress(request_id, f"Configuring 4-bit quantization for '{short_name}'...", 22)
        from transformers import BitsAndBytesConfig

        pipe_kwargs["model_kwargs"] = {
            "quantization_config": BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                llm_int8_enable_fp32_cpu_offload=True,
            ),
            "offload_buffers": True,
        }
        pipe_kwargs["device_map"] = "auto"
    else:
        pipe_kwargs["device"] = device

    _materialize_symlinks_in_cache(model_name)

    try:
        _pipeline = pipeline(**pipe_kwargs)
    except Exception as exc:
        _materialize_symlinks_in_cache(model_name)
        try:
            _pipeline = pipeline(**pipe_kwargs)
        except Exception as retry_exc:
            exc_str = str(retry_exc)
            if "model_type" in exc_str:
                raise RuntimeError(
                    f"Failed to load configuration for model '{model_name}'. "
                    "This usually occurs if the Hugging Face download was interrupted, rate-limited, "
                    "or required authentication. Set a Hugging Face token in Settings -> Active Local Model "
                    f"or check your internet connection. (Details: {exc_str})"
                ) from retry_exc
            raise RuntimeError(f"Failed to load model '{model_name}': {exc_str}") from retry_exc

    _pipeline_key = key
    _progress(request_id, f"Model '{short_name}' ready.", 25)
    return _pipeline


def _generate(request: dict) -> None:
    request_id = request["request_id"]
    model_name = request["model_name"]
    device = request.get("device", "cuda:0")
    use_4bit = bool(request.get("use_4bit_quantization", False))
    hf_token = request.get("hf_token") or None
    messages = request["messages"]
    max_new_tokens = int(request.get("max_new_tokens", 4096))
    temperature = float(request.get("temperature", 0.1))
    repetition_penalty = float(request.get("repetition_penalty", 1.15))
    do_sample = bool(request.get("do_sample", temperature > 0.0))

    pipe = _get_pipeline(
        request_id,
        model_name,
        device,
        use_4bit_quantization=use_4bit,
        hf_token=hf_token,
    )

    from transformers.generation.streamers import BaseStreamer

    class _WorkerStreamer(BaseStreamer):
        def __init__(self, tokenizer):
            self.tokenizer = tokenizer
            self.is_first = True
            self.count = 0

        def put(self, value):
            if self.is_first:
                self.is_first = False
                return
            n = value.numel() if hasattr(value, "numel") else len(value)
            self.count += n
            text = self.tokenizer.decode(value, skip_special_tokens=False)
            if text:
                _emit({
                    "request_id": request_id,
                    "type": "token",
                    "text": text,
                    "count": self.count,
                })

        def end(self):
            pass

    streamer = _WorkerStreamer(pipe.tokenizer)

    sampling_kwargs: dict[str, Any] = {}
    if temperature > 0.0 and do_sample:
        sampling_kwargs = {"do_sample": True, "temperature": temperature}
    else:
        sampling_kwargs = {"do_sample": False}

    result = pipe(
        messages,
        max_new_tokens=max_new_tokens,
        repetition_penalty=repetition_penalty,
        streamer=streamer,
        **sampling_kwargs,
    )

    out = result[0]["generated_text"]
    raw_out = out[-1]["content"].strip() if isinstance(out, list) else str(out).strip()

    del streamer
    del result
    del messages
    try:
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

    _emit({
        "request_id": request_id,
        "type": "result",
        "generated_text": raw_out,
    })


def main() -> int:
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            line_str = line.strip()
            if not line_str:
                continue
            request = json.loads(line_str)
            action = request.get("action")
            if action == "shutdown":
                _unload_pipeline()
                return 0
            if action == "unload":
                _unload_pipeline()
                _emit({"request_id": request.get("request_id"), "type": "result", "status": "unloaded"})
                continue
            if action == "generate":
                _generate(request)
                continue
            raise ValueError(f"Unknown worker action: {action}")
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            _emit({
                "request_id": request.get("request_id") if "request" in locals() else None,
                "type": "error",
                "message": str(exc),
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
