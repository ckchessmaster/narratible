import logging
import shutil
import os
import sys
import tempfile
import uuid
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import psutil
from typing import Literal, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Query, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

from .config import AppConfig, load_config, save_config, get_device_string
from .custom_instructions import list_custom_prompt_templates, validate_prompt_overrides
from .logging_config import configure_logging
from .mcp_server import create_mcp_server
from .projects import (
    PROJECTS_DIR,
    ProjectMetadata,
    list_projects,
    get_project,
    create_project,
    update_project,
    delete_project,
    load_chapters,
    save_chapters,
    update_chapter,
    source_pdf_path,
    artifact_dir,
    audio_dir,
    project_file,
    tts_settings_hash,
    chapter_audio_current,
    load_cleaning_eval,
    save_cleaning_eval,
    load_modernization_eval,
    save_modernization_eval,
    _project_path,
)
from .parser import extract_structured_from_pdf, extract_pdf_metadata, extract_pdf_cover
from .cleaner import regex_clean_text, llm_clean_text, llm_review_chapters, llm_extract_book_metadata, list_cleaning_profiles, get_cleaning_profile
from .parsing_modules import MODERNIZATION_MODULE_ID, list_modules, apply_modules, normalize_module_ids
from .parsing_modules.modernizer import list_modernization_profiles, llm_modernize_text
from .notes import EXTENDED_NOTE_DETECTION_MODULE_ID, normalize_chapter_notes, notes_from_text
from .tts import synthesize_speech, get_available_voices, compose_tts_text
from .tts_text import prepare_text_for_tts, segment_text_for_tts
from .epub import build_epub
from .uploader import AudiobookshelfUploader
from .voices import (
    add_library_voice_sample,
    create_library_voice,
    delete_library_voice,
    delete_library_voice_sample,
    get_library_voice,
    get_library_voice_preview_path,
    get_library_voice_sample_path,
    list_library_voices,
    set_library_voice_sample,
    update_library_voice,
)
from .runtime_state import save_task_snapshot

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="narratible API", version="0.1.0")
VOICE_SAMPLE_SUFFIXES = {".wav", ".mp3", ".flac"}
CLOUD_LLM_CONFIG_ERROR = (
    "Cloud LLM cleanup requires a configured Gemini or OpenAI API key. "
    "Add a key in Settings, then choose LLM again."
)


def _resolve_cloud_llm_provider(cfg: AppConfig) -> str | None:
    provider_keys = {
        "gemini": cfg.gemini_api_key.strip(),
        "openai": cfg.openai_api_key.strip(),
    }
    selected_provider = cfg.llm_provider
    if selected_provider in provider_keys and provider_keys[selected_provider]:
        return selected_provider
    for provider, api_key in provider_keys.items():
        if api_key:
            return provider
    return None


def _require_cloud_llm_provider(cfg: AppConfig) -> str:
    provider = _resolve_cloud_llm_provider(cfg)
    if provider is None:
        raise RuntimeError(CLOUD_LLM_CONFIG_ERROR)
    return provider

# In packaged mode, allow all origins so the local static frontend can fetch from the backend
cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if getattr(sys, 'frozen', False):
    cors_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if not getattr(sys, 'frozen', False) else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory task status store ──────────────────────────────────────────────
# Maps task_id -> {"status": "running"|"waiting_input"|"done"|"error"|"cancelled", "stage": str, "message": str, "progress": 0-100, "is_cancelled": bool, "llm_output": str}
# "stage" is the coarse phase shown as the primary status line (e.g. "Extracting
# text", "Cleaning text"); "message" carries the finer detail shown beneath it.
_tasks: dict[str, dict] = {}


def _set_task(task_id: str, status: str, message: str = None, progress: int = None, is_cancelled: bool = False, append_output: str = None, stage: str = None):
    existing = _tasks.get(task_id, {})
    _is_cancelled = existing.get("is_cancelled", False) if not is_cancelled else is_cancelled
    _llm_output = existing.get("llm_output", "")
    if append_output:
        _llm_output += append_output
    # Preserve prior stage/message/progress when a caller only updates a subset
    # (e.g. streaming llm_output) so the displayed line never blanks out.
    _stage = existing.get("stage", "") if stage is None else stage
    _message = existing.get("message", "") if message is None else message
    _progress = existing.get("progress", 0) if progress is None else progress
    base_task = {
        "status": status,
        "stage": _stage,
        "message": _message,
        "progress": _progress,
        "is_cancelled": _is_cancelled,
        "llm_output": _llm_output
    }
    # Preserve any auxiliary state fields (e.g. pending decision prompts).
    extra = {k: v for k, v in existing.items() if k not in base_task}
    _tasks[task_id] = {**base_task, **extra}
    save_task_snapshot(_tasks)

def _get_task(task_id: str):
    return _tasks.get(task_id)

@app.post("/api/projects/{project_id}/cancel")
async def api_cancel_task(project_id: str):
    task_id = f"parse-{project_id}"
    task = _get_task(task_id)
    if task:
        task["is_cancelled"] = True
        save_task_snapshot(_tasks)
    
    # Also attempt to cancel TTS tasks if they are running under tts-{project_id}
    tts_task_id = f"tts-{project_id}"
    tts_task = _get_task(tts_task_id)
    if tts_task:
        tts_task["is_cancelled"] = True
        save_task_snapshot(_tasks)

    modernize_task_id = f"modernize-{project_id}"
    modernize_task = _get_task(modernize_task_id)
    if modernize_task:
        modernize_task["is_cancelled"] = True
        save_task_snapshot(_tasks)

    return {"message": "Task cancelled"}



# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


def _nvidia_smi_gpus() -> list[dict]:
    """Fallback: query nvidia-smi for NVIDIA GPUs when torch CUDA is unavailable."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                try:
                    gpus.append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "vram_mb": int(parts[2]),
                        "cuda": False,  # torch CUDA unavailable; GPU is present but PyTorch can't reach it
                        "cuda_unavailable_reason": "GPU detected but CUDA is unavailable. Ensure your NVIDIA drivers are up to date.",
                    })
                except ValueError:
                    pass
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


@app.get("/api/system/info")
async def system_info():
    """Returns GPU/CUDA availability and a list of all detected GPUs."""
    info: dict = {"cuda_available": False, "gpu_name": None, "torch_version": None, "vram_total_mb": 0, "gpus": []}
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        gpus: list[dict] = []
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["vram_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 2)
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                gpus.append({
                    "index": i,
                    "name": torch.cuda.get_device_name(i),
                    "vram_mb": round(props.total_memory / 1024 ** 2),
                    "cuda": True,
                })
        else:
            # PyTorch CUDA unavailable — fall back to nvidia-smi so the GPU still appears
            gpus = _nvidia_smi_gpus()
        gpus.append({"index": -1, "name": "CPU (No GPU)", "vram_mb": 0, "cuda": False})
        info["gpus"] = gpus
    except ImportError:
        info["torch_version"] = "not installed"
        # torch not installed at all — still try nvidia-smi
        gpus = _nvidia_smi_gpus()
        gpus.append({"index": -1, "name": "CPU (No GPU)", "vram_mb": 0, "cuda": False})
        info["gpus"] = gpus
    return info


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings", response_model=AppConfig)
async def get_settings():
    return load_config()


@app.put("/api/settings", response_model=AppConfig)
async def update_settings(config: AppConfig):
    try:
        validate_prompt_overrides(config.custom_prompt_overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    save_config(config)
    return config


@app.get("/api/custom-instructions/prompts")
async def get_custom_instruction_prompts():
    return {
        "enabled": load_config().custom_instructions_enabled,
        "prompts": list_custom_prompt_templates(),
    }


# ── Key Validation ────────────────────────────────────────────────────────────

class ValidateKeyRequest(BaseModel):
    api_key: str


@app.post("/api/validate/gemini-key")
async def validate_gemini_key(req: ValidateKeyRequest):
    """Validate a Gemini API key by listing models."""
    try:
        from google import genai
        client = genai.Client(api_key=req.api_key)
        list(client.models.list())
        return {"valid": True, "error": None}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.post("/api/validate/openai-key")
async def validate_openai_key(req: ValidateKeyRequest):
    """Validate an OpenAI API key by listing models."""
    try:
        from openai import AsyncOpenAI, AuthenticationError
        client = AsyncOpenAI(api_key=req.api_key)
        await client.models.list()
        return {"valid": True, "error": None}
    except Exception as e:
        # Extract a readable error message from openai errors
        msg = getattr(e, "message", None) or str(e)
        return {"valid": False, "error": msg}


@app.post("/api/validate/huggingface-token")
async def validate_huggingface_token(req: ValidateKeyRequest):
    """Validate a HuggingFace token via the whoami endpoint."""
    import asyncio
    import requests as _requests

    def _check():
        try:
            r = _requests.get(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {req.api_key}"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                return {"valid": True, "username": data.get("name", ""), "error": None}
            return {"valid": False, "username": None, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"valid": False, "username": None, "error": str(e)}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _check)


# ── LLM Models ────────────────────────────────────────────────────────────────

class LLMVariant(BaseModel):
    id: str
    name: str
    min_vram_mb: int
    base_vram_mb: int
    recommended: bool
    gated: bool = False

class LLMFamily(BaseModel):
    name: str
    description: str
    variants: list[LLMVariant]


class RedoCleaningRequest(BaseModel):
    cleaning_profile: str = "balanced"
    provider: str | None = None


class ApplyVariantRequest(BaseModel):
    variant_id: str
    apply_to_chapter_text: bool = False


class SelectVariantRequest(BaseModel):
    variant_id: str


class BatchRedoChunkRequest(BaseModel):
    chapter_index: int
    chunk_id: int


class BatchRedoCleaningRequest(BaseModel):
    chunks: list[BatchRedoChunkRequest]
    cleaning_profile: str = "balanced"
    provider: str | None = None


class ModernizationRequest(BaseModel):
    modernization_profile: str = "standard_modern"
    provider: str | None = None


class RedoModernizationRequest(BaseModel):
    modernization_profile: str = "standard_modern"
    provider: str | None = None
    redo_mode: str = "try_again"
    instruction: str | None = None


class ChapterPatchRequest(BaseModel):
    title: str | None = None
    text: str | None = None
    order: int | None = None


class TaskDecisionRequest(BaseModel):
    action: Literal["retry", "heuristic"]


@app.get("/api/gemini/models")
async def list_gemini_models(api_key: str = None):
    """Return Gemini models that support generateContent, using the provided or configured API key."""
    cfg = load_config()
    key = api_key or cfg.gemini_api_key
    if not key:
        raise HTTPException(status_code=400, detail="No Gemini API key configured.")
    try:
        from google import genai
        client = genai.Client(api_key=key)
        models = [
            {"id": m.name.removeprefix("models/"), "display_name": m.display_name}
            for m in client.models.list()
            if "generateContent" in (m.supported_actions or [])
        ]
        models.sort(key=lambda m: m["id"])
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/llm/model-info")
async def get_model_info(model_id: str, token: str = None):
    """Dynamic fallback. Returns real model info directly from the Hugging Face API."""
    cfg = load_config()
    hf_token = token or cfg.huggingface_token
    
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import RepositoryNotFoundError, GatedRepoError, HfHubHTTPError
        
        # Initialize api with or without a token
        api = HfApi(token=hf_token if hf_token else None)
        try:
            info = api.model_info(model_id, files_metadata=True)
        except GatedRepoError:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Gated model. Ensure you have accepted the EULA on HuggingFace and your token has access.")
        except RepositoryNotFoundError:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Model not found on HuggingFace.")
        except HfHubHTTPError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"HuggingFace API error: {str(e)}")
        except Exception as e:
             from fastapi import HTTPException
             raise HTTPException(status_code=500, detail=f"Failed to fetch model info: {str(e)}")
        
        size_bytes = 0
        if info.siblings:
            # Estimate size from .safetensors (or .bin)
            sizes = [f.size for f in info.siblings if f.size and f.rfilename.endswith('.safetensors')]
            if not sizes:
               sizes = [f.size for f in info.siblings if f.size and f.rfilename.endswith('.bin')]
            size_bytes = sum(sizes)
        
        vram_mb = 0
        try:
            import torch
            if torch.cuda.is_available():
                vram_mb = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 2)
        except Exception:
            pass
            
        return {
            "id": info.modelId,
            "author": getattr(info, "author", "Unknown"),
            "tags": getattr(info, "tags", []),
            "gated": getattr(info, 'gated', None) not in [False, None, 'false'],
            "size_mb": round(size_bytes / 1024**2) if size_bytes else 0,
            "system_vram_mb": vram_mb
        }
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="huggingface_hub package is not installed.")


# ── Projects ──────────────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    title: str
    author: str = ""


@app.get("/api/projects", response_model=list[ProjectMetadata])
async def api_list_projects():
    return list_projects()


@app.post("/api/projects", response_model=ProjectMetadata, status_code=201)
async def api_create_project(req: CreateProjectRequest):
    return create_project(req.title, req.author)


@app.get("/api/projects/{project_id}", response_model=ProjectMetadata)
async def api_get_project(project_id: str):
    try:
        return get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/api/projects/{project_id}", response_model=ProjectMetadata)
async def api_update_project(project_id: str, updates: dict):
    try:
        return update_project(project_id, updates)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/projects/{project_id}", status_code=204)
async def api_delete_project(project_id: str):
    try:
        delete_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── PDF Upload & Parsing ──────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/upload-pdf")
async def upload_pdf(project_id: str, file: UploadFile = File(...)):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    dest = source_pdf_path(project_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    update_project(project_id, {
        "source_pdf": {
            "filename": file.filename,
            "stored_path": "source/original.pdf",
        },
        "current_step": "upload",
    })
    return {"message": "PDF uploaded successfully.", "path": str(dest)}


def _modernization_provider_for_cleaner(cleaner: str, cfg: AppConfig) -> str:
    if cleaner == "embedded":
        return "embedded"
    if cleaner == "llm":
        return _require_cloud_llm_provider(cfg)
    raise RuntimeError("Text Modernization requires a configured cloud or local LLM in Settings.")


def _normalize_query_modules(modules: list[str] | Any | None) -> list[str]:
    return normalize_module_ids(modules if isinstance(modules, list) else [])


def _run_parse(project_id: str, task_id: str, cleaner: str, modules: list[str] | None = None, cleaning_profile: str = "safe", modernization_profile: str = "standard_modern"):
    modules = _normalize_query_modules(modules)
    profile = get_cleaning_profile(cleaning_profile)
    parse_started_at = datetime.now(timezone.utc).isoformat()
    parse_started_monotonic = time.perf_counter()

    def _persist_parse_status(status: str, stage: str, message: str, progress: int, error: str | None = None, extra: dict[str, Any] | None = None):
        payload: dict[str, Any] = {
            "status": status,
            "stage": stage,
            "message": message,
            "progress": progress,
            "started_at": parse_started_at,
        }
        if status in ("done", "error", "cancelled"):
            payload["completed_at"] = datetime.now(timezone.utc).isoformat()
            payload["duration_seconds"] = round(max(0.0, time.perf_counter() - parse_started_monotonic), 2)
        if error:
            payload["error"] = error
        if extra:
            payload.update(extra)
        try:
            update_project(project_id, {"last_parse_status": payload})
        except Exception:
            logger.exception("Failed to persist parse status for project %s", project_id)

    try:
        meta = update_project(project_id, {"enabled_modules": modules})
        _set_task(task_id, "running", "Reading PDF…", 10, stage="Extracting text")
        _persist_parse_status("running", "Extracting text", "Reading PDF…", 10)
        pdf_path = source_pdf_path(project_id)
        legacy_pdf_path = _project_path(project_id) / "book.pdf"
        if not pdf_path.exists() and legacy_pdf_path.exists():
            pdf_path = legacy_pdf_path
        if not pdf_path.exists():
            raise FileNotFoundError("book.pdf not found. Upload a PDF first.")

        def _extract_progress(msg: str, frac: float):
            # Map extraction fraction (0..1) into the 10-28 progress band.
            pct = 10 + int(max(0.0, min(1.0, frac)) * 18)
            _set_task(task_id, "running", msg, pct, stage="Extracting text")

        pdf_data = extract_structured_from_pdf(
            pdf_path,
            progress_callback=_extract_progress,
            extended_note_detection=EXTENDED_NOTE_DETECTION_MODULE_ID in modules,
        )
        raw_text = pdf_data["raw_text"]
        raw_chapters = pdf_data["chapters"]

        _set_task(task_id, "running", "Extracting metadata…", 29, stage="Extracting metadata")

        def _metadata_progress(msg: str):
            _set_task(task_id, "running", msg, 29, stage="Extracting metadata")

        front_matter_seed = "\n\n".join(
            (chapter.get("raw_text") or "")
            for chapter in raw_chapters[:2]
            if chapter.get("raw_text")
        ).strip() or raw_text[:12000]
        heuristic_meta, front_matter_text = extract_pdf_metadata(
            pdf_path,
            front_matter_text=front_matter_seed,
            progress_callback=_metadata_progress,
        )
        llm_meta: dict[str, str] = {}
        cloud_provider = _resolve_cloud_llm_provider(load_config())
        if cloud_provider and front_matter_text:
            _set_task(task_id, "running", "Refining metadata with configured LLM…", 29, stage="Extracting metadata")
            llm_meta = llm_extract_book_metadata(
                front_matter_text,
                heuristics=heuristic_meta,
                provider=cloud_provider,
            )

        metadata_updates: dict[str, Any] = {}
        for field_name in ("title", "author", "language", "description", "publisher", "subject", "isbn", "series"):
            current_val = (getattr(meta, field_name, "") or "").strip()
            candidate = (llm_meta.get(field_name) or heuristic_meta.get(field_name) or "").strip()
            if candidate and not current_val:
                metadata_updates[field_name] = candidate

        if not (meta.cover_image or ""):
            cover_dest = _project_path(project_id) / "cover.jpg"
            if extract_pdf_cover(pdf_path, cover_dest):
                metadata_updates["cover_image"] = cover_dest.name

        if metadata_updates:
            meta = update_project(project_id, metadata_updates)

        artifacts = artifact_dir(project_id)
        artifacts.mkdir(exist_ok=True)
        raw_path = artifacts / "raw_text.txt"
        raw_path.write_text(raw_text, encoding="utf-8")

        # Hybrid chapter review: refine layout-heuristic boundaries with LLM before cleaning.
        # llm_chapters_only* bypass the TOC check so debug mode always runs the review.
        _debug_cleaners = ("llm_chapters_only", "llm_chapters_only_embedded")
        if cleaner in ("llm", "embedded") + _debug_cleaners and (
            pdf_data.get("method") != "toc" or cleaner in _debug_cleaners
        ):
            review_provider: str = "gemini"
            if cleaner == "embedded" or cleaner == "llm_chapters_only_embedded":
                review_provider = "embedded"
            else:
                review_provider = _require_cloud_llm_provider(load_config())
            # Save lightweight heuristic snapshot for debug comparison (before LLM review)
            if cleaner in _debug_cleaners:
                debug_snapshot = [
                    {
                        "title": ch["title"],
                        "confidence": ch.get("confidence", 1.0),
                        "warnings": ch.get("warnings", []),
                        "char_count": len(ch.get("raw_text", "")),
                        "snippet": ch.get("raw_text", "")[:300].replace("\n", " ").strip(),
                    }
                    for ch in raw_chapters
                ]
                debug_file = _project_path(project_id) / "chapters_debug_comparison.json"
                import json as _json
                debug_file.write_text(
                    _json.dumps({"method": pdf_data.get("method"), "chapters": debug_snapshot}, indent=2),
                    encoding="utf-8",
                )

            def _review_cancel_check():
                t = _get_task(task_id)
                return t and t.get("is_cancelled", False)

            def _review_progress(msg: str, pct: int):
                _set_task(task_id, "running", msg, pct, stage="Reviewing chapters")

            if cleaner in _debug_cleaners and pdf_data.get("method") == "toc":
                _set_task(task_id, "running",
                    "PDF has an embedded table of contents - normally chapter review "
                    "would be skipped. Running it anyway…", 15, stage="Reviewing chapters")

            raw_chapters = llm_review_chapters(
                raw_chapters,
                provider=review_provider,
                cancel_check=_review_cancel_check,
                progress_callback=_review_progress,
                prompt_save_path=(
                    _project_path(project_id) / "chapters_debug_prompt.json"
                    if cleaner in _debug_cleaners else None
                ),
            )

        _set_task(task_id, "running", "Cleaning text…", 30, stage="Cleaning text")

        cleaned_chapters = []
        full_cleaned_text = ""
        cleaning_eval = {
            "version": 1,
            "project_id": project_id,
            "cleaner": cleaner,
            "profile": profile.id if cleaner in ("llm", "embedded") else "heuristic",
            "provider": None,
            "modules": modules,
            "chapters": [],
        }

        if cleaner in ("llm", "embedded"):
            if cleaner == "embedded":
                provider = "embedded"
            else:
                provider = _require_cloud_llm_provider(load_config())
            cleaning_eval["provider"] = provider

            def _cancel_check():
                t = _get_task(task_id)
                return t and t.get("is_cancelled", False)

            try:
                for i, ch in enumerate(raw_chapters):
                    if _cancel_check():
                        break

                    ch_title = ch["title"]
                    current_overall_progress = 30 + int((i / len(raw_chapters)) * 50)

                    def _progress_cb(msg: str, pct: int):
                        nonlocal current_overall_progress
                        # Localize progress over total chapters
                        base_prog = 30 + int((i / len(raw_chapters)) * 50)
                        overall_prog = base_prog + int((pct / 100) * (50 / len(raw_chapters)))
                        current_overall_progress = overall_prog
                        _set_task(task_id, "running", f"Cleaning '{ch_title}' - {msg}", overall_prog, stage="Cleaning text")

                    def _output_cb(chunk_text: str):
                        # We just append whatever token/text we received directly
                        _set_task(task_id, "running", append_output=chunk_text)

                    def _gemini_retry_decision_cb(context: dict) -> str:
                        decision_id = str(uuid.uuid4())
                        pending = {
                            "id": decision_id,
                            "type": "gemini_retry_exhausted",
                            "chapter_index": i,
                            "chapter_title": ch_title,
                            "chunk_index": context.get("chunk_index", 0),
                            "chunk_count": context.get("chunk_count", 1),
                            "choices": ["retry", "heuristic"],
                            "message": (
                                "Gemini is unavailable after 5 retries. "
                                "Choose Retry to attempt another 5 retries for this chunk, "
                                "or Heuristic to keep processing with regex fallback."
                            ),
                            "error": context.get("error", ""),
                        }
                        current = _get_task(task_id) or {}
                        current["pending_decision"] = pending
                        current["decision_response"] = None
                        current["status"] = "waiting_input"
                        current["stage"] = "Waiting for input"
                        current["message"] = (
                            f"Gemini unavailable while cleaning '{ch_title}'. Waiting for your choice…"
                        )
                        current["progress"] = current_overall_progress
                        _tasks[task_id] = current
                        save_task_snapshot(_tasks)

                        while True:
                            t = _get_task(task_id) or {}
                            if t.get("is_cancelled"):
                                raise InterruptedError("User cancelled.")
                            action = t.get("decision_response")
                            if action in ("retry", "heuristic"):
                                # Clear prompt state and resume running updates.
                                t.pop("pending_decision", None)
                                t.pop("decision_response", None)
                                t["status"] = "running"
                                t["stage"] = "Cleaning text"
                                t["message"] = (
                                    "Retrying Gemini for this chunk…"
                                    if action == "retry"
                                    else "Using heuristic fallback for this chunk…"
                                )
                                t["progress"] = current_overall_progress
                                _tasks[task_id] = t
                                save_task_snapshot(_tasks)
                                return action
                            time.sleep(0.5)

                    cleaned_result = llm_clean_text(
                        ch["raw_text"],
                        provider=provider,
                        progress_callback=_progress_cb,
                        cancel_check=_cancel_check,
                        output_callback=_output_cb,
                        retry_decision_callback=_gemini_retry_decision_cb if provider == "gemini" else None,
                        known_titles=[meta.title, ch_title],
                        cleaning_profile=profile.id,
                        return_evaluation=True,
                    )
                    cleaned_ch_text, chapter_eval = cleaned_result
                    chapter_eval = {
                        "chapter_index": i,
                        "title": ch_title,
                        **chapter_eval,
                    }
                    cleaning_eval["chapters"].append(chapter_eval)
                    chapter_notes = [
                        *normalize_chapter_notes(ch.get("notes", [])),
                        *[
                            note
                            for chunk_eval in chapter_eval.get("chunks", [])
                            for note in notes_from_text(
                                chunk_eval.get("notes_text", ""),
                                source="llm_cleanup",
                            )
                        ],
                    ]

                    warnings = list(ch.get("warnings", []))
                    fallback_count = chapter_eval.get("fallback_count", 0)
                    if fallback_count:
                        warnings.append(f"{fallback_count} LLM cleaning chunk(s) fell back to heuristic text")
                    review_count = sum(
                        1
                        for chunk_eval in chapter_eval.get("chunks", [])
                        if chunk_eval.get("recommended_action") == "review" or chunk_eval.get("risk_level") == "high"
                    )
                    if review_count and review_count != fallback_count:
                        warnings.append(f"{review_count} cleaning chunk(s) need review")

                    cleaned_chapters.append({
                        "title": ch_title,
                        "text": cleaned_ch_text,
                        "notes": chapter_notes,
                        "audio_path": None,
                        "confidence": ch.get("confidence", 1.0),
                        "warnings": warnings,
                    })
                    full_cleaned_text += cleaned_ch_text + "\n\n"
            except InterruptedError:
                # User aborted mid-generation. Fall through so the model is
                # unloaded from VRAM and the task is marked cancelled below.
                logger.info("Embedded LLM cleaning interrupted by user cancel.")
        else:
            total_ch = len(raw_chapters) or 1
            for i, ch in enumerate(raw_chapters):
                ch_title = ch["title"]
                # Map regex cleaning across the 30-88 band so the bar keeps moving.
                overall_prog = 30 + int((i / total_ch) * 58)
                _set_task(task_id, "running",
                    f"Cleaning chapter {i+1} of {total_ch}: '{ch_title}'…",
                    overall_prog, stage="Cleaning text")
                cleaned_txt = regex_clean_text(
                    ch["raw_text"],
                    known_titles=[meta.title, ch_title],
                )
                cleaned_chapters.append({
                    "title": ch["title"],
                    "text": cleaned_txt,
                    "notes": normalize_chapter_notes(ch.get("notes", [])),
                    "audio_path": None,
                    "confidence": ch.get("confidence", 1.0),
                    "warnings": ch.get("warnings", [])
                })
                full_cleaned_text += cleaned_txt + "\n\n"

        save_cleaning_eval(project_id, cleaning_eval)

        # Unload the LLM from VRAM *after* all chapters are done parsing.
        # Covers any path that may have loaded the embedded model — full embedded
        # cleaning as well as the embedded chapter-review debug cleaner.
        if cleaner in ("embedded", "llm_chapters_only_embedded"):
            from app.cleaner import unload_llm
            unload_llm()

        t = _get_task(task_id)
        if t and t.get("is_cancelled"):
            _set_task(task_id, "cancelled", "Processing cancelled.", t.get("progress", 0), stage="Cancelled")
            _persist_parse_status("cancelled", "Cancelled", "Processing cancelled.", int(t.get("progress", 0)))
            return

        # Apply optional parsing modules (deterministic, offline text transforms)
        # to each cleaned chapter, then rebuild the full text from the result.
        if modules:
            _set_task(task_id, "running", "Applying parsing modules…", 89, stage="Parsing modules")
            full_cleaned_text = ""
            for ch in cleaned_chapters:
                ch["text"] = apply_modules(ch["text"], modules)
                full_cleaned_text += ch["text"] + "\n\n"

        cleaned_path = artifacts / "cleaned_text.txt"
        cleaned_path.write_text(full_cleaned_text.strip(), encoding="utf-8")

        # We no longer need to auto-split because we split natively!
        _set_task(task_id, "running", "Saving chapters…", 90, stage="Saving")

        chapters = cleaned_chapters
        save_chapters(project_id, chapters)
        update_project(project_id, {"current_step": "edit"})
        _set_task(task_id, "done", f"Parsed {len(chapters)} chapter(s) via {pdf_data.get('method', 'unknown')}.", 100, stage="Done")
        _persist_parse_status(
            "done",
            "Done",
            f"Parsed {len(chapters)} chapter(s) via {pdf_data.get('method', 'unknown')}.",
            100,
            extra={"chapter_count": len(chapters), "method": pdf_data.get("method", "unknown")},
        )
    except Exception as e:
        logger.exception("Parse task failed")
        _set_task(task_id, "error", str(e), 0, stage="Error")
        _persist_parse_status("error", "Error", str(e), 0, error=str(e))


@app.post("/api/projects/{project_id}/parse")
async def parse_pdf(
    project_id: str,
    background_tasks: BackgroundTasks,
    cleaner: str = "regex",
    modules: list[str] = Query(default=[]),
    cleaning_profile: str = "safe",
    modernization_profile: str = "standard_modern",
):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    requested_modules = _normalize_query_modules(modules)

    if cleaner in ("llm", "llm_chapters_only"):
        try:
            _require_cloud_llm_provider(load_config())
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    task_id = f"parse-{project_id}"
    _set_task(task_id, "running", "Queued…", 0, stage="Queued")
    background_tasks.add_task(_run_parse, project_id, task_id, cleaner, requested_modules, cleaning_profile, modernization_profile)
    return {"task_id": task_id}


@app.get("/api/cleaning-profiles")
async def get_cleaning_profiles():
    return list_cleaning_profiles()


@app.get("/api/modernization-profiles")
async def get_modernization_profiles():
    return list_modernization_profiles()


@app.get("/api/parsing-modules")
async def get_parsing_modules():
    return list_modules()


@app.get("/api/projects/{project_id}/debug-chapters")
async def get_debug_chapters(project_id: str):
    debug_file = _project_path(project_id) / "chapters_debug_comparison.json"
    if not debug_file.exists():
        return None
    import json as _json
    with open(debug_file, "r", encoding="utf-8") as f:
        return _json.load(f)


@app.get("/api/projects/{project_id}/debug-prompt")
async def get_debug_prompt(project_id: str):
    prompt_file = _project_path(project_id) / "chapters_debug_prompt.json"
    if not prompt_file.exists():
        return None
    import json as _json
    with open(prompt_file, "r", encoding="utf-8") as f:
        return _json.load(f)


@app.get("/api/projects/{project_id}/cleaning-eval")
async def get_project_cleaning_eval(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return load_cleaning_eval(project_id)


@app.put("/api/projects/{project_id}/cleaning-eval")
async def update_project_cleaning_eval(project_id: str, evaluation: dict):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation["project_id"] = project_id
    save_cleaning_eval(project_id, evaluation)
    return evaluation


@app.get("/api/projects/{project_id}/modernization-eval")
async def get_project_modernization_eval(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if evaluation:
        save_modernization_eval(project_id, evaluation)
    return evaluation


@app.put("/api/projects/{project_id}/modernization-eval")
async def update_project_modernization_eval(project_id: str, evaluation: dict):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation["project_id"] = project_id
    _ensure_modernization_sessions(evaluation)
    save_modernization_eval(project_id, evaluation)
    return evaluation


def _find_eval_chunk(evaluation: dict, chapter_index: int, chunk_id: int) -> tuple[dict, dict]:
    chapters_eval = evaluation.get("chapters") or []
    chapter_eval = next((ch for ch in chapters_eval if ch.get("chapter_index") == chapter_index), None)
    if chapter_eval is None:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this chapter.")

    chunks = chapter_eval.get("chunks") or []
    chunk_eval = next((chunk for chunk in chunks if chunk.get("chunk_id") == chunk_id), None)
    if chunk_eval is None:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this chunk.")
    return chapter_eval, chunk_eval


def _find_modernization_eval_chunk(evaluation: dict, chapter_index: int, chunk_id: int) -> tuple[dict, dict]:
    chapters_eval = evaluation.get("chapters") or []
    chapter_eval = next((ch for ch in chapters_eval if ch.get("chapter_index") == chapter_index), None)
    if chapter_eval is None:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this chapter.")

    chunks = chapter_eval.get("chunks") or []
    chunk_eval = next((chunk for chunk in chunks if chunk.get("chunk_id") == chunk_id), None)
    if chunk_eval is None:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this chunk.")
    return chapter_eval, chunk_eval


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _normalize_modernization_chunk(chunk_eval: dict) -> dict:
    source_text = chunk_eval.get("source_text") or ""
    variants = chunk_eval.setdefault("variants", [])
    if not variants and (chunk_eval.get("candidate_text") or chunk_eval.get("accepted_text")):
        candidate_text = chunk_eval.get("candidate_text") or chunk_eval.get("accepted_text") or ""
        if candidate_text.strip() and candidate_text != source_text:
            variants.append({
                "variant_id": f"{chunk_eval.get('chunk_id', 0)}-1",
                "provider": chunk_eval.get("provider"),
                "profile": chunk_eval.get("profile"),
                "status": chunk_eval.get("status", "candidate"),
                "candidate_text": candidate_text,
                "accepted_text": candidate_text,
                "integrity_issues": chunk_eval.get("integrity_issues", []),
                "metrics": chunk_eval.get("metrics", {}),
                "risk_level": chunk_eval.get("risk_level", "medium"),
                "risk_reasons": chunk_eval.get("risk_reasons", []),
                "recommended_action": chunk_eval.get("recommended_action", "review"),
            })

    selected_variant_id = chunk_eval.get("selected_variant_id") or chunk_eval.get("applied_variant_id")
    if selected_variant_id:
        chunk_eval["selected_variant_id"] = selected_variant_id
        chunk_eval["status"] = "selected"
    elif chunk_eval.get("status") not in {"skipped", "unselected", "selected"}:
        chunk_eval["status"] = "unselected"

    for variant in variants:
        is_selected = variant.get("variant_id") == chunk_eval.get("selected_variant_id")
        variant["is_selected"] = is_selected
        variant["is_applied"] = is_selected
    return chunk_eval


def _legacy_session_id(chapter_index: int) -> str:
    return f"legacy-modernization-{chapter_index}"


def _ensure_modernization_session(chapter_eval: dict, evaluation: dict | None = None) -> dict:
    sessions = chapter_eval.setdefault("sessions", [])
    if sessions:
        active_session_id = chapter_eval.get("active_session_id")
        session = next((item for item in sessions if item.get("session_id") == active_session_id), None)
        if session is None and active_session_id:
            session = sessions[-1]
        if session is None:
            session = next((item for item in reversed(sessions) if item.get("status") != "superseded"), None)
        if session is None:
            chapter_eval["active_session_id"] = None
            chapter_eval["status"] = "superseded"
            chapter_eval["chunks"] = []
            chapter_eval["last_commit"] = None
            return sessions[-1]
        chapter_eval["active_session_id"] = session.get("session_id")
        for chunk in session.get("chunks") or []:
            _normalize_modernization_chunk(chunk)
        chapter_eval["chunks"] = session.get("chunks", [])
        for key in ("status", "source_text", "source_text_hash", "last_commit", "created_at", "committed_at", "superseded_at"):
            if key in session:
                chapter_eval[key] = session.get(key)
        return session

    source_text = chapter_eval.get("source_text")
    if source_text is None:
        source_text = "\n\n".join((chunk.get("source_text") or "") for chunk in chapter_eval.get("chunks") or [])
    status = chapter_eval.get("status") or "reviewing"
    session = {
        "session_id": chapter_eval.get("active_session_id") or _legacy_session_id(chapter_eval.get("chapter_index", 0)),
        "status": status,
        "created_at": chapter_eval.get("created_at") or _utc_iso(),
        "committed_at": chapter_eval.get("committed_at"),
        "superseded_at": chapter_eval.get("superseded_at"),
        "source_text": source_text or "",
        "source_text_hash": chapter_eval.get("source_text_hash") or _text_hash(source_text or ""),
        "chunks": chapter_eval.get("chunks") or [],
        "last_commit": chapter_eval.get("last_commit"),
    }
    for chunk in session["chunks"]:
        _normalize_modernization_chunk(chunk)
    sessions.append(session)
    chapter_eval["active_session_id"] = session["session_id"]
    chapter_eval["chunks"] = session["chunks"]
    chapter_eval["status"] = session["status"]
    chapter_eval["source_text"] = session["source_text"]
    chapter_eval["source_text_hash"] = session["source_text_hash"]
    chapter_eval["last_commit"] = session["last_commit"]
    if evaluation is not None:
        evaluation["version"] = max(int(evaluation.get("version") or 1), 2)
    return session


def _ensure_modernization_sessions(evaluation: dict | None) -> dict | None:
    if not evaluation:
        return evaluation
    for chapter_eval in evaluation.get("chapters") or []:
        _ensure_modernization_session(chapter_eval, evaluation)
    evaluation["version"] = max(int(evaluation.get("version") or 1), 2)
    return evaluation


def _set_active_modernization_session(chapter_eval: dict, session: dict):
    chapter_eval["active_session_id"] = session["session_id"]
    chapter_eval["status"] = session.get("status", "reviewing")
    chapter_eval["source_text"] = session.get("source_text", "")
    chapter_eval["source_text_hash"] = session.get("source_text_hash") or _text_hash(session.get("source_text", ""))
    chapter_eval["chunks"] = session.get("chunks", [])
    chapter_eval["last_commit"] = session.get("last_commit")
    chapter_eval["committed_at"] = session.get("committed_at")
    chapter_eval["superseded_at"] = session.get("superseded_at")


def _find_modernization_variant(chunk_eval: dict, variant_id: str) -> dict:
    variant = next((item for item in chunk_eval.get("variants") or [] if item.get("variant_id") == variant_id), None)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found for this chunk.")
    replacement_text = variant.get("accepted_text") or variant.get("candidate_text") or ""
    if not replacement_text.strip():
        raise HTTPException(status_code=400, detail="Variant has no text to select.")
    return variant


def _select_modernization_variant(evaluation: dict, chapter_index: int, chunk_id: int, variant_id: str) -> tuple[dict, dict, dict]:
    chapter_eval, chunk_eval = _find_modernization_eval_chunk(evaluation, chapter_index, chunk_id)
    session = _ensure_modernization_session(chapter_eval, evaluation)
    chunk_eval = next((chunk for chunk in session.get("chunks") or [] if chunk.get("chunk_id") == chunk_id), chunk_eval)
    variant = _find_modernization_variant(chunk_eval, variant_id)
    selected_at = _utc_iso()
    for item in chunk_eval.get("variants") or []:
        item["is_selected"] = item.get("variant_id") == variant_id
        item["is_applied"] = item["is_selected"]
        if item["is_selected"]:
            item["selected_at"] = selected_at
            item["applied_at"] = selected_at
        else:
            item.pop("selected_at", None)
            item.pop("applied_at", None)
    chunk_eval["selected_variant_id"] = variant_id
    chunk_eval["applied_variant_id"] = variant_id
    chunk_eval["status"] = "selected"
    chunk_eval["selected_at"] = selected_at
    chunk_eval["applied_at"] = selected_at
    chunk_eval["accepted_text"] = chunk_eval.get("source_text") or ""
    _set_active_modernization_session(chapter_eval, session)
    return chapter_eval, chunk_eval, variant


def _clear_modernization_chunk_selection(evaluation: dict, chapter_index: int, chunk_id: int, status: str = "unselected") -> tuple[dict, dict]:
    chapter_eval, chunk_eval = _find_modernization_eval_chunk(evaluation, chapter_index, chunk_id)
    session = _ensure_modernization_session(chapter_eval, evaluation)
    chunk_eval = next((chunk for chunk in session.get("chunks") or [] if chunk.get("chunk_id") == chunk_id), chunk_eval)
    for item in chunk_eval.get("variants") or []:
        item["is_selected"] = False
        item["is_applied"] = False
        item.pop("selected_at", None)
        item.pop("applied_at", None)
    chunk_eval["status"] = status
    chunk_eval["accepted_text"] = chunk_eval.get("source_text") or chunk_eval.get("accepted_text") or ""
    chunk_eval.pop("selected_variant_id", None)
    chunk_eval.pop("applied_variant_id", None)
    chunk_eval.pop("selected_at", None)
    chunk_eval.pop("applied_at", None)
    _set_active_modernization_session(chapter_eval, session)
    return chapter_eval, chunk_eval


def _build_modernization_commit_text(session: dict) -> tuple[str, list[str]]:
    selected_variant_ids: list[str] = []
    parts: list[str] = []
    for chunk in sorted(session.get("chunks") or [], key=lambda item: item.get("chunk_id", 0)):
        selected_variant_id = chunk.get("selected_variant_id")
        selected_variant = None
        if selected_variant_id:
            selected_variant = next((variant for variant in chunk.get("variants") or [] if variant.get("variant_id") == selected_variant_id), None)
        if selected_variant:
            parts.append(selected_variant.get("accepted_text") or selected_variant.get("candidate_text") or chunk.get("source_text") or "")
            selected_variant_ids.append(selected_variant_id)
        else:
            parts.append(chunk.get("source_text") or "")
    return "\n\n".join(part.strip() for part in parts if part is not None).strip(), selected_variant_ids


def _resolve_modernization_provider(provider: str | None = None) -> str:
    if provider == "embedded":
        return "embedded"
    if provider in ("gemini", "openai"):
        return provider
    cfg = load_config()
    if cfg.llm_provider == "local":
        return "embedded"
    return _require_cloud_llm_provider(cfg)


def _upsert_modernization_chapter_eval(evaluation: dict, chapter_eval: dict):
    chapter_index = chapter_eval.get("chapter_index")
    chapters_eval = evaluation.setdefault("chapters", [])
    for index, item in enumerate(chapters_eval):
        if item.get("chapter_index") == chapter_index:
            chapters_eval[index] = chapter_eval
            return
    chapters_eval.append(chapter_eval)
    chapters_eval.sort(key=lambda item: item.get("chapter_index", 0))


def _modernize_saved_chapter(project_id: str, chapter_index: int, modernization_profile: str, provider: str | None = None, progress_callback=None, cancel_check=None, output_callback=None, retry_decision_callback=None) -> dict:
    meta = get_project(project_id)
    chapters = load_chapters(project_id)
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found.")
    resolved_provider = _resolve_modernization_provider(provider)
    chapter = chapters[chapter_index]
    now = _utc_iso()
    source_text = chapter.get("text", "")
    _, chapter_eval = llm_modernize_text(
        source_text,
        provider=resolved_provider,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        output_callback=output_callback,
        retry_decision_callback=retry_decision_callback,
        modernization_profile=modernization_profile,
    )
    for chunk in chapter_eval.get("chunks") or []:
        chunk["status"] = "unselected"
        chunk["selected_variant_id"] = None
        chunk.pop("applied_variant_id", None)
        for variant in chunk.get("variants") or []:
            variant["is_selected"] = False
            variant["is_applied"] = False

    session = {
        "session_id": str(uuid.uuid4()),
        "status": "reviewing",
        "created_at": now,
        "committed_at": None,
        "superseded_at": None,
        "source_text": source_text,
        "source_text_hash": _text_hash(source_text),
        "chunks": chapter_eval.get("chunks", []),
        "last_commit": None,
    }
    chapter_eval = {
        "chapter_index": chapter_index,
        "title": chapter.get("title") or f"Chapter {chapter_index + 1}",
        "active_session_id": session["session_id"],
        "sessions": [session],
        "status": session["status"],
        "created_at": now,
        "committed_at": None,
        "superseded_at": None,
        "source_text": source_text,
        "source_text_hash": session["source_text_hash"],
        "last_commit": None,
        **chapter_eval,
    }
    evaluation = load_modernization_eval(project_id) or {
        "version": 2,
        "project_id": project_id,
        "profile": modernization_profile,
        "provider": resolved_provider,
        "modules": meta.enabled_modules,
        "source_language": meta.language or "same",
        "target_style": "modern readable prose",
        "chapters": [],
    }
    evaluation.update({
        "version": 2,
        "project_id": project_id,
        "profile": modernization_profile,
        "provider": resolved_provider,
        "modules": meta.enabled_modules,
        "source_language": meta.language or "same",
    })
    _ensure_modernization_sessions(evaluation)
    existing = next((item for item in evaluation.get("chapters") or [] if item.get("chapter_index") == chapter_index), None)
    if existing:
        existing_session = _ensure_modernization_session(existing, evaluation)
        if existing_session.get("status") == "reviewing":
            existing_session["status"] = "superseded"
            existing_session["superseded_at"] = now
            _set_active_modernization_session(existing, existing_session)
        chapter_eval["sessions"] = (existing.get("sessions") or []) + [session]
    _upsert_modernization_chapter_eval(evaluation, chapter_eval)
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chapter": chapter_eval}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernize")
async def modernize_chapter(project_id: str, chapter_index: int, req: ModernizationRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _modernize_saved_chapter(project_id, chapter_index, req.modernization_profile, req.provider)


def _run_modernize_project(project_id: str, task_id: str, modernization_profile: str, provider: str | None = None):
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        chapters = load_chapters(project_id)
        total = len(chapters) or 1
        resolved_provider = _resolve_modernization_provider(provider)

        def _cancel_check():
            t = _get_task(task_id)
            return t and t.get("is_cancelled", False)

        for index, chapter in enumerate(chapters):
            if _cancel_check():
                _set_task(task_id, "cancelled", "Text modernization cancelled.", _get_task(task_id).get("progress", 0), stage="Cancelled")
                return
            title = chapter.get("title") or f"Chapter {index + 1}"
            current_progress = int((index / total) * 100)

            def _progress_cb(msg: str, pct: int):
                nonlocal current_progress
                current_progress = int((index / total) * 100 + (pct / 100) * (100 / total))
                _set_task(task_id, "running", f"Modernizing '{title}' - {msg}", current_progress, stage="Modernizing text")

            def _output_cb(chunk_text: str):
                _set_task(task_id, "running", append_output=chunk_text)

            _modernize_saved_chapter(
                project_id,
                index,
                modernization_profile,
                resolved_provider,
                progress_callback=_progress_cb,
                cancel_check=_cancel_check,
                output_callback=_output_cb,
            )

        _set_task(task_id, "done", f"Modernized {len(chapters)} chapter(s).", 100, stage="Done")
        task = _get_task(task_id) or {}
        task["started_at"] = started_at
        task["completed_at"] = datetime.now(timezone.utc).isoformat()
        _tasks[task_id] = task
        save_task_snapshot(_tasks)
    except Exception as e:
        logger.exception("Modernization task failed")
        _set_task(task_id, "error", str(e), 0, stage="Error")


@app.post("/api/projects/{project_id}/modernize")
async def modernize_project(project_id: str, background_tasks: BackgroundTasks, req: ModernizationRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        _resolve_modernization_provider(req.provider)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    task_id = f"modernize-{project_id}"
    _set_task(task_id, "running", "Queued…", 0, stage="Queued")
    background_tasks.add_task(_run_modernize_project, project_id, task_id, req.modernization_profile, req.provider)
    return {"task_id": task_id}


def _run_modernization_chunk_redo(evaluation: dict, chapter_index: int, chunk_id: int, modernization_profile: str, provider: str | None = None, redo_mode: str = "try_again", instruction: str | None = None) -> dict:
    chapter_eval, chunk_eval = _find_modernization_eval_chunk(evaluation, chapter_index, chunk_id)
    session = _ensure_modernization_session(chapter_eval, evaluation)
    chunk_eval = next((chunk for chunk in session.get("chunks") or [] if chunk.get("chunk_id") == chunk_id), chunk_eval)
    retry_provider = _resolve_modernization_provider(provider or chapter_eval.get("provider") or evaluation.get("provider"))
    source_text = chunk_eval.get("source_text") or chunk_eval.get("accepted_text") or ""
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="This chunk has no source text to modernize.")

    _, retry_eval = llm_modernize_text(
        source_text,
        provider=retry_provider,
        modernization_profile=modernization_profile,
        redo_context={
            "previous_candidates": [
                variant.get("accepted_text") or variant.get("candidate_text") or ""
                for variant in chunk_eval.get("variants") or []
            ],
            "integrity_issues": chunk_eval.get("integrity_issues") or [],
            "redo_mode": redo_mode,
            "instruction": instruction,
        },
    )
    retry_chunks = retry_eval.get("chunks") or []
    if not retry_chunks:
        raise HTTPException(status_code=400, detail="Modernization retry did not return a candidate.")
    retry_chunk = retry_chunks[0]
    variant_text = retry_chunk.get("candidate_text") or retry_chunk.get("variants", [{}])[0].get("candidate_text", "")
    variant = {
        "variant_id": f"{chunk_id}-{len(chunk_eval.get('variants') or []) + 1}",
        "created_at": _utc_iso(),
        "provider": retry_provider,
        "profile": retry_eval.get("profile"),
        "redo_mode": redo_mode,
        "redo_instruction": instruction,
        "similarity_to_previous": retry_chunk.get("similarity_to_previous"),
        "status": retry_chunk.get("status"),
        "candidate_text": variant_text,
        "accepted_text": variant_text,
        "integrity_issues": retry_chunk.get("integrity_issues", []),
        "metrics": retry_chunk.get("metrics", {}),
        "risk_level": retry_chunk.get("risk_level", "medium"),
        "risk_reasons": retry_chunk.get("risk_reasons", []),
        "recommended_action": retry_chunk.get("recommended_action", "review"),
    }
    chunk_eval.setdefault("variants", []).append(variant)
    _set_active_modernization_session(chapter_eval, session)
    return {"chapter": chapter_eval, "chunk": chunk_eval, "variant": variant}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization-chunks/{chunk_id}/redo")
async def redo_modernization_chunk(project_id: str, chapter_index: int, chunk_id: int, req: RedoModernizationRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = load_modernization_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    _ensure_modernization_sessions(evaluation)
    result = _run_modernization_chunk_redo(evaluation, chapter_index, chunk_id, req.modernization_profile, req.provider, req.redo_mode, req.instruction)
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chunk": result["chunk"], "variant": result["variant"]}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization-chunks/{chunk_id}/select-variant")
async def select_modernization_variant(project_id: str, chapter_index: int, chunk_id: int, req: SelectVariantRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    _, chunk_eval, variant = _select_modernization_variant(evaluation, chapter_index, chunk_id, req.variant_id)
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chunk": chunk_eval, "variant": variant}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization-chunks/{chunk_id}/skip")
async def skip_modernization_chunk(project_id: str, chapter_index: int, chunk_id: int):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    _, chunk_eval = _clear_modernization_chunk_selection(evaluation, chapter_index, chunk_id, "skipped")
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chunk": chunk_eval}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization-chunks/{chunk_id}/clear-selection")
async def clear_modernization_selection(project_id: str, chapter_index: int, chunk_id: int):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    _, chunk_eval = _clear_modernization_chunk_selection(evaluation, chapter_index, chunk_id, "unselected")
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chunk": chunk_eval}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization/commit")
async def commit_modernization_session(project_id: str, chapter_index: int):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    chapters = load_chapters(project_id)
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found.")
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    chapter_eval = next((ch for ch in evaluation.get("chapters") or [] if ch.get("chapter_index") == chapter_index), None)
    if not chapter_eval:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this chapter.")
    session = _ensure_modernization_session(chapter_eval, evaluation)
    after_text, selected_variant_ids = _build_modernization_commit_text(session)
    if not after_text and session.get("source_text"):
        after_text = session["source_text"]
    before_text = chapters[chapter_index].get("text", "")
    committed_at = _utc_iso()
    chapters[chapter_index]["text"] = after_text
    save_chapters(project_id, chapters)
    last_commit = {
        "committed_at": committed_at,
        "before_text": before_text,
        "after_text": after_text,
        "selected_variant_ids": selected_variant_ids,
    }
    session["status"] = "committed"
    session["committed_at"] = committed_at
    session["last_commit"] = last_commit
    _set_active_modernization_session(chapter_eval, session)
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chapter": load_chapters(project_id)[chapter_index], "last_commit": last_commit}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization/undo-last-commit")
async def undo_last_modernization_commit(project_id: str, chapter_index: int):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    chapters = load_chapters(project_id)
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found.")
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    chapter_eval = next((ch for ch in evaluation.get("chapters") or [] if ch.get("chapter_index") == chapter_index), None)
    if not chapter_eval:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this chapter.")
    session = _ensure_modernization_session(chapter_eval, evaluation)
    last_commit = session.get("last_commit") or {}
    before_text = last_commit.get("before_text")
    if before_text is None:
        raise HTTPException(status_code=400, detail="No modernization commit is available to undo.")
    chapters[chapter_index]["text"] = before_text
    save_chapters(project_id, chapters)
    session["status"] = "commit_undone"
    session["commit_undone_at"] = _utc_iso()
    _set_active_modernization_session(chapter_eval, session)
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chapter": load_chapters(project_id)[chapter_index], "last_commit": last_commit}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization/discard")
async def discard_modernization_session(project_id: str, chapter_index: int):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = _ensure_modernization_sessions(load_modernization_eval(project_id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    chapter_eval = next((ch for ch in evaluation.get("chapters") or [] if ch.get("chapter_index") == chapter_index), None)
    if not chapter_eval:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this chapter.")
    session = _ensure_modernization_session(chapter_eval, evaluation)
    if session.get("status") == "committed":
        raise HTTPException(status_code=400, detail="Undo the committed modernization before discarding this session.")
    session["status"] = "superseded"
    session["superseded_at"] = _utc_iso()
    reviewing = [item for item in chapter_eval.get("sessions") or [] if item is not session and item.get("status") in {"reviewing", "commit_undone"}]
    if reviewing:
        _set_active_modernization_session(chapter_eval, reviewing[-1])
    else:
        chapter_eval["active_session_id"] = None
        chapter_eval["status"] = "superseded"
        chapter_eval["chunks"] = []
        chapter_eval["last_commit"] = None
    save_modernization_eval(project_id, evaluation)
    return {"evaluation": evaluation, "chapter": chapter_eval}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/modernization-chunks/{chunk_id}/apply-variant")
async def apply_modernization_variant(project_id: str, chapter_index: int, chunk_id: int, req: ApplyVariantRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evaluation = load_modernization_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No modernization evaluation is available for this project.")
    _ensure_modernization_sessions(evaluation)

    _, chunk_eval, variant = _select_modernization_variant(evaluation, chapter_index, chunk_id, req.variant_id)
    replacement_text = variant.get("accepted_text") or variant.get("candidate_text") or ""
    previous_text = chunk_eval.get("source_text") or ""

    chapter_text_updated = False
    if req.apply_to_chapter_text:
        chapters = load_chapters(project_id)
        if chapter_index >= len(chapters):
            raise HTTPException(status_code=404, detail="Chapter not found.")
        current_chapter_text = chapters[chapter_index].get("text", "")
        source_text = chunk_eval.get("source_text") or ""
        if previous_text and previous_text in current_chapter_text:
            chapters[chapter_index]["text"] = current_chapter_text.replace(previous_text, replacement_text, 1)
            save_chapters(project_id, chapters)
            chapter_text_updated = True
        elif source_text and source_text in current_chapter_text:
            chapters[chapter_index]["text"] = current_chapter_text.replace(source_text, replacement_text, 1)
            save_chapters(project_id, chapters)
            chapter_text_updated = True
        else:
            raise HTTPException(status_code=409, detail="Could not find the original chunk text in the chapter. Apply it in the editor instead.")

    save_modernization_eval(project_id, evaluation)
    return {
        "evaluation": evaluation,
        "chunk": chunk_eval,
        "variant": variant,
        "replacement_text": replacement_text,
        "previous_text": previous_text,
        "chapter_text_updated": chapter_text_updated,
    }


def _run_chunk_redo(evaluation: dict, chapter_index: int, chunk_id: int, cleaning_profile: str, provider: str | None = None) -> dict:
    chapter_eval, chunk_eval = _find_eval_chunk(evaluation, chapter_index, chunk_id)
    retry_provider = provider or chapter_eval.get("provider") or evaluation.get("provider")
    if not retry_provider:
        raise HTTPException(status_code=400, detail="No LLM provider is available for this cleaning run.")

    source_text = chunk_eval.get("source_text") or chunk_eval.get("accepted_text") or ""
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="This chunk has no source text to retry.")

    cleaned_text, retry_eval = llm_clean_text(
        source_text,
        provider=retry_provider,
        cleaning_profile=cleaning_profile,
        known_titles=[chapter_eval.get("title", "")],
        return_evaluation=True,
    )
    retry_chunks = retry_eval.get("chunks") or []
    if not retry_chunks:
        raise HTTPException(status_code=400, detail="Retry used heuristic fallback because the provider is not configured.")

    retry_chunk = retry_chunks[0]
    variant = {
        "variant_id": f"{chunk_id}-{len(chunk_eval.get('variants') or []) + 1}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": retry_provider,
        "profile": retry_eval.get("profile"),
        "status": retry_chunk.get("status"),
        "candidate_text": retry_chunk.get("candidate_text", ""),
        "accepted_text": cleaned_text,
        "notes_text": retry_chunk.get("notes_text", ""),
        "integrity_issues": retry_chunk.get("integrity_issues", []),
        "metrics": retry_chunk.get("metrics", {}),
        "risk_level": retry_chunk.get("risk_level", "medium"),
        "risk_reasons": retry_chunk.get("risk_reasons", []),
        "recommended_action": retry_chunk.get("recommended_action", "review"),
    }
    chunk_eval.setdefault("variants", []).append(variant)
    return {"chapter": chapter_eval, "chunk": chunk_eval, "variant": variant}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/chunks/{chunk_id}/redo-cleaning")
async def redo_cleaning_chunk(project_id: str, chapter_index: int, chunk_id: int, req: RedoCleaningRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation = load_cleaning_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this project.")

    result = _run_chunk_redo(evaluation, chapter_index, chunk_id, req.cleaning_profile, req.provider)
    save_cleaning_eval(project_id, evaluation)

    return {"evaluation": evaluation, "chunk": result["chunk"], "variant": result["variant"]}


@app.post("/api/projects/{project_id}/chapters/{chapter_index}/chunks/{chunk_id}/apply-variant")
async def apply_cleaning_variant(project_id: str, chapter_index: int, chunk_id: int, req: ApplyVariantRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation = load_cleaning_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this project.")

    _, chunk_eval = _find_eval_chunk(evaluation, chapter_index, chunk_id)
    variants = chunk_eval.get("variants") or []
    variant = next((item for item in variants if item.get("variant_id") == req.variant_id), None)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found for this chunk.")

    replacement_text = variant.get("accepted_text") or variant.get("candidate_text") or ""
    if not replacement_text.strip():
        raise HTTPException(status_code=400, detail="Variant has no text to apply.")

    previous_text = chunk_eval.get("accepted_text") or chunk_eval.get("source_text") or ""
    source_text = chunk_eval.get("source_text") or ""
    applied_at = datetime.now(timezone.utc).isoformat()
    for item in variants:
        item["is_applied"] = item.get("variant_id") == req.variant_id
        if not item["is_applied"]:
            item.pop("applied_at", None)
    variant["applied_at"] = applied_at
    chunk_eval["applied_variant_id"] = req.variant_id
    chunk_eval["applied_at"] = applied_at
    chunk_eval["accepted_text"] = replacement_text
    variant_notes = notes_from_text(
        variant.get("notes_text") or chunk_eval.get("notes_text", ""),
        source="llm_cleanup_variant",
    )

    chapter_text_updated = False
    if req.apply_to_chapter_text:
        chapters = load_chapters(project_id)
        if chapter_index >= len(chapters):
            raise HTTPException(status_code=404, detail="Chapter not found.")
        current_chapter_text = chapters[chapter_index].get("text", "")
        if previous_text and previous_text in current_chapter_text:
            chapters[chapter_index]["text"] = current_chapter_text.replace(previous_text, replacement_text, 1)
            if variant_notes:
                chapters[chapter_index]["notes"] = [
                    *normalize_chapter_notes(chapters[chapter_index].get("notes", [])),
                    *variant_notes,
                ]
            save_chapters(project_id, chapters)
            chapter_text_updated = True
        elif source_text and source_text in current_chapter_text:
            chapters[chapter_index]["text"] = current_chapter_text.replace(source_text, replacement_text, 1)
            if variant_notes:
                chapters[chapter_index]["notes"] = [
                    *normalize_chapter_notes(chapters[chapter_index].get("notes", [])),
                    *variant_notes,
                ]
            save_chapters(project_id, chapters)
            chapter_text_updated = True
        else:
            raise HTTPException(status_code=409, detail="Could not find the original chunk text in the chapter. Apply it in the editor instead.")

    save_cleaning_eval(project_id, evaluation)

    return {
        "evaluation": evaluation,
        "chunk": chunk_eval,
        "variant": variant,
        "replacement_text": replacement_text,
        "previous_text": previous_text,
        "chapter_text_updated": chapter_text_updated,
    }


@app.post("/api/projects/{project_id}/batch-redo-cleaning")
async def batch_redo_cleaning(project_id: str, req: BatchRedoCleaningRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation = load_cleaning_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this project.")

    results = []
    for item in req.chunks:
        try:
            redo = _run_chunk_redo(evaluation, item.chapter_index, item.chunk_id, req.cleaning_profile, req.provider)
            results.append({
                "chapter_index": item.chapter_index,
                "chunk_id": item.chunk_id,
                "ok": True,
                "variant": redo["variant"],
            })
        except HTTPException as exc:
            results.append({
                "chapter_index": item.chapter_index,
                "chunk_id": item.chunk_id,
                "ok": False,
                "error": exc.detail,
            })

    save_cleaning_eval(project_id, evaluation)
    return {"evaluation": evaluation, "results": results}


@app.get("/api/projects/{project_id}/cleaning-report")
async def get_cleaning_report(project_id: str):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    evaluation = load_cleaning_eval(project_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="No cleaning evaluation is available for this project.")

    chapter_summaries = []
    total_chunks = 0
    total_fallbacks = 0
    risk_counts = {"low": 0, "medium": 0, "high": 0}
    applied_variants = 0
    top_warnings = []

    for chapter in evaluation.get("chapters") or []:
        chunks = chapter.get("chunks") or []
        total_chunks += len(chunks)
        total_fallbacks += chapter.get("fallback_count", 0) or 0
        chapter_risk_counts = {"low": 0, "medium": 0, "high": 0}
        for chunk in chunks:
            risk = chunk.get("risk_level", "medium")
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
            chapter_risk_counts[risk] = chapter_risk_counts.get(risk, 0) + 1
            for variant in chunk.get("variants") or []:
                if variant.get("is_applied"):
                    applied_variants += 1
            if chunk.get("integrity_issues"):
                top_warnings.append({
                    "chapter_index": chapter.get("chapter_index"),
                    "chunk_id": chunk.get("chunk_id"),
                    "issues": chunk.get("integrity_issues"),
                })
        chapter_summaries.append({
            "chapter_index": chapter.get("chapter_index"),
            "title": chapter.get("title"),
            "chunk_count": len(chunks),
            "fallback_count": chapter.get("fallback_count", 0),
            "accepted_count": chapter.get("accepted_count", 0),
            "risk_counts": chapter_risk_counts,
        })

    return {
        "project": {"id": meta.id, "title": meta.title, "author": meta.author},
        "profile": evaluation.get("profile"),
        "provider": evaluation.get("provider"),
        "cleaner": evaluation.get("cleaner"),
        "total_chunks": total_chunks,
        "total_fallbacks": total_fallbacks,
        "fallback_rate": total_fallbacks / total_chunks if total_chunks else 0,
        "risk_counts": risk_counts,
        "applied_variants": applied_variants,
        "chapters": chapter_summaries,
        "top_warnings": top_warnings[:10],
    }


# ── Chapters ──────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/chapters")
async def api_get_chapters(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return load_chapters(project_id)


@app.put("/api/projects/{project_id}/chapters")
async def api_save_chapters(project_id: str, chapters: list[dict]):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    save_chapters(project_id, chapters)
    update_project(project_id, {"current_step": "edit"})
    return {"message": f"Saved {len(chapters)} chapter(s)."}


@app.patch("/api/projects/{project_id}/chapters/{chapter_id}")
async def api_update_chapter(project_id: str, chapter_id: str, req: ChapterPatchRequest):
    try:
        get_project(project_id)
        return update_chapter(
            project_id,
            chapter_id,
            {key: value for key, value in req.model_dump().items() if value is not None},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Cover Image Upload ────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/cover")
async def get_cover(project_id: str):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    cover_path = project_file(project_id, meta.cover_image)
    if not cover_path:
        raise HTTPException(status_code=404, detail="No cover image uploaded.")

    project_root = _project_path(project_id).resolve()
    cover_path = cover_path.resolve()
    try:
        cover_path.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cover image path.")

    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    media_type = media_types.get(cover_path.suffix.lower())
    if not media_type or not cover_path.exists() or not cover_path.is_file():
        raise HTTPException(status_code=404, detail="Cover image not found.")

    return FileResponse(cover_path, media_type=media_type)


@app.post("/api/projects/{project_id}/upload-cover")
async def upload_cover(project_id: str, file: UploadFile = File(...)):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    suffix = Path(file.filename).suffix.lower() if file.filename else ".jpg"
    if suffix not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(status_code=400, detail="Cover must be a JPG or PNG.")

    dest = _project_path(project_id) / f"cover{suffix}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    update_project(project_id, {"cover_image": dest.name})
    return {"message": "Cover uploaded.", "cover_image": dest.name}


# ── TTS ───────────────────────────────────────────────────────────────────────

@app.get("/api/tts/voices")
async def api_get_voices(engine: str = "edge-tts"):
    try:
        voices = await get_available_voices(engine)
        return {"voices": voices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PreviewRequest(BaseModel):
    text: str
    engine: str = "edge-tts"
    voice: str = "en-US-AriaNeural"
    speed: float = 1.0
    temperature: float | None = None


class VoiceLibraryUpdateRequest(BaseModel):
    name: str | None = None
    reference_text: str | None = None
    notes: str | None = None
    speed: float | None = None
    temperature: float | None = None


class VoiceLibraryTestRequest(BaseModel):
    text: str
    reference_text: str | None = None
    speed: float | None = None
    temperature: float | None = None


class VoiceLibrarySampleRequest(BaseModel):
    sample_filename: str


def _resolve_f5_voice_reference(project_id: str, voice: str):
    if voice and voice != "__uploaded__":
        library_voice = get_library_voice(voice)
        return get_library_voice_sample_path(voice), None, None, library_voice.temperature
    return None, _voices_dir(project_id), None, None


@app.post("/api/projects/{project_id}/tts/preview")
async def tts_preview(project_id: str, req: PreviewRequest):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    preview_path = _project_path(project_id) / "preview.mp3"
    try:
        voice_sample_path = None
        voice_reference_text = None
        voice_samples_dir = None
        voice_temperature = req.temperature
        if req.engine == "f5-tts":
            voice_sample_path, voice_samples_dir, voice_reference_text, saved_temperature = _resolve_f5_voice_reference(project_id, req.voice)
            voice_temperature = voice_temperature if voice_temperature is not None else saved_temperature
        await synthesize_speech(
            text=req.text[:500],
            output_path=preview_path,
            engine=req.engine,
            voice=req.voice,
            speed=req.speed,
            temperature=voice_temperature if voice_temperature is not None else 0.7,
            voice_sample_path=voice_sample_path,
            voice_reference_text=voice_reference_text,
            voice_samples_dir=voice_samples_dir,
            enabled_modules=meta.enabled_modules,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("TTS preview failed")
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(preview_path, media_type="audio/mpeg", filename="preview.mp3")


@app.post("/api/projects/{project_id}/tts/debug-text")
async def tts_debug_text(project_id: str, req: PreviewRequest):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    source_text = req.text[:500]
    prepared_text = prepare_text_for_tts(
        source_text,
        req.engine,
        enabled_modules=meta.enabled_modules,
    )
    segments = segment_text_for_tts(prepared_text, req.engine)
    return {
        "engine": req.engine,
        "enabled_modules": meta.enabled_modules,
        "source_text": source_text,
        "prepared_text": prepared_text,
        "segments": [
            {
                "index": idx + 1,
                "text": segment.text,
                "char_count": len(segment.text),
                "pause_after_ms": segment.pause_after_ms,
            }
            for idx, segment in enumerate(segments)
        ],
    }


# ── Voice Library ────────────────────────────────────────────────────────────

@app.get("/api/voice-library")
async def api_list_voice_library():
    return {"voices": list_library_voices()}


@app.post("/api/voice-library")
async def api_create_voice_library_item(
    name: str = Form(...),
    reference_text: str = Form(""),
    notes: str = Form(""),
    speed: float = Form(1.0),
    temperature: float = Form(0.7),
    file: UploadFile = File(...),
):
    try:
        voice = create_library_voice(name, reference_text, notes, speed, temperature, file.filename or "reference.wav", file.file)
        return voice
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/voice-library/{voice_id}")
async def api_update_voice_library_item(voice_id: str, req: VoiceLibraryUpdateRequest):
    try:
        return update_library_voice(voice_id, req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/voice-library/{voice_id}")
async def api_delete_voice_library_item(voice_id: str):
    try:
        delete_library_voice(voice_id)
        return {"message": "Voice removed.", "id": voice_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/voice-library/{voice_id}/samples")
async def api_add_voice_library_sample(
    voice_id: str,
    activate: bool = Form(True),
    file: UploadFile = File(...),
):
    try:
        return add_library_voice_sample(voice_id, file.filename or "reference.wav", file.file, activate)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/voice-library/{voice_id}/samples/active")
async def api_set_voice_library_sample(voice_id: str, req: VoiceLibrarySampleRequest):
    try:
        return set_library_voice_sample(voice_id, req.sample_filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/voice-library/{voice_id}/samples/{sample_filename}")
async def api_delete_voice_library_sample(voice_id: str, sample_filename: str):
    try:
        return delete_library_voice_sample(voice_id, sample_filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/voice-library/test-draft")
async def api_test_voice_library_draft(
    text: str = Form(...),
    reference_text: str = Form(""),
    speed: float = Form(1.0),
    temperature: float = Form(0.7),
    file: UploadFile = File(...),
):
    suffix = Path(file.filename).suffix.lower() if file.filename else ".wav"
    if suffix not in VOICE_SAMPLE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Reference audio must be WAV, MP3, or FLAC.")

    temp_dir = Path(tempfile.mkdtemp(prefix="narratible_voice_test_"))
    sample_path = temp_dir / f"reference{suffix}"
    preview_path = temp_dir / "voice-preview.mp3"
    try:
        with open(sample_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        await synthesize_speech(
            text=text[:500],
            output_path=preview_path,
            engine="f5-tts",
            voice="draft",
            speed=speed,
            temperature=temperature,
            voice_sample_path=sample_path,
            voice_reference_text=None,
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Draft voice library test failed")
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(
        preview_path,
        media_type="audio/mpeg",
        filename="voice-preview.mp3",
        background=BackgroundTask(lambda: shutil.rmtree(temp_dir, ignore_errors=True)),
    )


@app.post("/api/voice-library/{voice_id}/test")
async def api_test_voice_library_item(voice_id: str, req: VoiceLibraryTestRequest):
    try:
        voice = get_library_voice(voice_id)
        preview_path = get_library_voice_preview_path(voice_id)
        await synthesize_speech(
            text=req.text[:500],
            output_path=preview_path,
            engine="f5-tts",
            voice=voice.id,
            speed=req.speed if req.speed is not None else voice.speed,
            temperature=req.temperature if req.temperature is not None else voice.temperature,
            voice_sample_path=get_library_voice_sample_path(voice_id),
            voice_reference_text=None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Voice library test failed")
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(preview_path, media_type="audio/mpeg", filename="voice-preview.mp3")


def _sanitize_filename(name: str, fallback: str) -> str:
    """Return a filesystem-safe version of *name*.

    Spaces are replaced with underscores, characters that are not alphanumeric,
    underscores, or hyphens are removed, consecutive underscores are collapsed,
    and leading/trailing underscores/hyphens are stripped.  Falls back to
    *fallback* when the result would be empty.
    """
    s = name.replace(" ", "_")
    s = "".join(c for c in s if c.isalnum() or c in "_-")
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_-")
    return s or fallback


def _preferred_epub_stem(meta: ProjectMetadata) -> str:
    title_candidate = (meta.title or "").strip()
    author_candidate = (meta.author or "").strip()
    if title_candidate and author_candidate:
        return _sanitize_filename(f"{title_candidate} - {author_candidate}", "book")
    if title_candidate:
        return _sanitize_filename(title_candidate, "book")
    return "book"


def resolve_merge_format(audio_format: str):
    """Map a requested merge format to its output extension and ffmpeg codec args.

    MP3 chapters can be stream-copied into an MP3 container, but the MP4/M4B
    muxer rejects raw MP3 streams, so M4B output must be re-encoded to AAC.
    Unknown formats fall back to ``m4b``.

    Returns a ``(fmt, codec_args)`` tuple.
    """
    fmt = (audio_format or "m4b").lower()
    if fmt not in ("m4b", "mp3"):
        fmt = "m4b"
    if fmt == "mp3":
        codec_args = ["-c", "copy"]
    else:
        codec_args = ["-c:a", "aac", "-b:a", "128k"]
    return fmt, codec_args


def _find_chapter(chapters: list[dict], chapter_id: str) -> tuple[int, dict]:
    for index, chapter in enumerate(chapters):
        if str(chapter.get("id", index)) == chapter_id or str(index) == chapter_id:
            return index, chapter
    raise FileNotFoundError(f"Chapter '{chapter_id}' not found.")


def _chapter_audio_relative_path(chapter: dict, chapter_index: int) -> str:
    """Generate a human-readable audio filename using chapter number and sanitized title."""
    chapter_num = chapter_index + 1
    chapter_title = chapter.get("title", f"Chapter {chapter_num}")
    safe_title = _sanitize_filename(chapter_title, f"chapter_{chapter_num}")
    return f"audio/chapter-{chapter_num:02d}-{safe_title}.mp3"


async def synthesize_project_chapter(
    project_id: str,
    chapter_id: str,
    *,
    engine: str,
    voice: str,
    speed: float,
    read_headings: bool,
    force: bool = False,
    progress_cb=None,
) -> dict:
    meta = get_project(project_id)
    chapters = load_chapters(project_id)
    index, chapter = _find_chapter(chapters, chapter_id)
    settings_hash = tts_settings_hash(
        engine=engine,
        voice=voice,
        speed=speed,
        read_headings=read_headings,
        enabled_modules=meta.enabled_modules,
    )

    if chapter_audio_current(chapter, settings_hash, project_id) and not force:
        return {"status": "skipped", "chapter": chapter, "audio_path": chapter["tts"]["audio_path"]}

    rel_audio_path = chapter.get("tts", {}).get("audio_path") or _chapter_audio_relative_path(chapter, index)
    final_path = project_file(project_id, rel_audio_path)
    if final_path is None:
        raise ValueError("Chapter audio path could not be resolved.")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.with_name(f"{final_path.stem}.tmp{final_path.suffix}")

    previous_tts = dict(chapter.get("tts") or {})
    text_hash = chapter.get("text_hash")
    chapters[index]["tts"] = {
        **previous_tts,
        "status": "generating",
        "audio_path": rel_audio_path,
        "text_hash": previous_tts.get("text_hash"),
        "settings_hash": previous_tts.get("settings_hash"),
        "engine": engine,
        "voice": voice,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    chapters[index]["audio_path"] = rel_audio_path
    save_chapters(project_id, chapters)

    try:
        voice_sample_path = None
        voice_reference_text = None
        voice_samples_dir = None
        voice_temperature = None
        if engine == "f5-tts":
            voice_sample_path, voice_samples_dir, voice_reference_text, voice_temperature = _resolve_f5_voice_reference(project_id, voice)

        await synthesize_speech(
            text=compose_tts_text(chapter.get("title", f"Chapter {index + 1}"), chapter.get("text", ""), read_headings),
            output_path=temp_path,
            engine=engine,
            voice=voice,
            speed=speed,
            temperature=voice_temperature if voice_temperature is not None else 0.7,
            voice_sample_path=voice_sample_path,
            voice_reference_text=voice_reference_text,
            voice_samples_dir=voice_samples_dir,
            progress_cb=progress_cb,
            enabled_modules=meta.enabled_modules,
        )
        os.replace(temp_path, final_path)

        latest_chapters = load_chapters(project_id)
        latest_index, latest_chapter = _find_chapter(latest_chapters, chapter_id)
        latest_hash = latest_chapter.get("text_hash")
        status = "complete" if latest_hash == text_hash else "stale"
        latest_chapters[latest_index]["tts"] = {
            **(latest_chapter.get("tts") or {}),
            "status": status,
            "audio_path": rel_audio_path,
            "text_hash": text_hash,
            "settings_hash": settings_hash,
            "engine": engine,
            "voice": voice,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        latest_chapters[latest_index]["audio_path"] = rel_audio_path
        save_chapters(project_id, latest_chapters)
        return {"status": status, "chapter": latest_chapters[latest_index], "audio_path": rel_audio_path}
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        latest_chapters = load_chapters(project_id)
        latest_index, latest_chapter = _find_chapter(latest_chapters, chapter_id)
        latest_chapters[latest_index]["tts"] = {
            **(latest_chapter.get("tts") or previous_tts),
            "status": "failed",
            "audio_path": previous_tts.get("audio_path") or latest_chapter.get("tts", {}).get("audio_path"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
        latest_chapters[latest_index]["audio_path"] = latest_chapters[latest_index]["tts"].get("audio_path")
        save_chapters(project_id, latest_chapters)
        raise


async def _run_tts(project_id: str, task_id: str, engine: str, voice: str, speed: float,
                   single_file: bool = False, audio_format: str = "m4b",
                   read_headings: bool = True, force: bool = False):
    tts_started_at = datetime.now(timezone.utc).isoformat()
    tts_started_monotonic = time.perf_counter()

    def _persist_tts_status(status: str, stage: str, message: str, progress: int, error: str | None = None, extra: dict[str, Any] | None = None):
        payload: dict[str, Any] = {
            "status": status,
            "stage": stage,
            "message": message,
            "progress": progress,
            "started_at": tts_started_at,
        }
        if status in ("done", "error", "cancelled"):
            payload["completed_at"] = datetime.now(timezone.utc).isoformat()
            payload["duration_seconds"] = round(max(0.0, time.perf_counter() - tts_started_monotonic), 2)
        if error:
            payload["error"] = error
        if extra:
            payload.update(extra)
        try:
            update_project(project_id, {"last_tts_status": payload})
        except Exception:
            logger.exception("Failed to persist TTS status for project %s", project_id)

    try:
        meta = update_project(project_id, {
            "tts_engine": engine,
            "tts_voice": voice,
            "tts_speed": speed,
            "tts_read_headings": read_headings,
            "current_step": "export",
        })
        _set_task(task_id, "running", "Preparing synthesis…", 2, stage="Preparing")
        _persist_tts_status("running", "Preparing", "Preparing synthesis…", 2)

        chapters = load_chapters(project_id)
        if not chapters:
            raise ValueError("No chapters found. Parse the PDF first.")

        exports_dir = _project_path(project_id) / "exports"
        exports_dir.mkdir(exist_ok=True)

        audio_files = []

        for i, ch in enumerate(chapters):
            t = _get_task(task_id)
            if t and t.get("is_cancelled"):
                _set_task(task_id, "cancelled", "Task was cancelled.", t.get("progress", 0), stage="Cancelled")
                _persist_tts_status("cancelled", "Cancelled", "Task was cancelled.", int(t.get("progress", 0)))
                return

            progress = int((i / len(chapters)) * 90)
            ch_title = ch.get("title", f"Chapter {i + 1}")
            _set_task(task_id, "running", f"Chapter {i + 1}/{len(chapters)}: {ch_title} — Synthesizing…", progress, stage="Synthesizing")

            def _tts_progress_cb(msg: str, _pct: int = 0, _task_id: str = task_id, _base: int = progress):
                _set_task(_task_id, "running", msg, _base, stage="Synthesizing")

            result = await synthesize_project_chapter(
                project_id,
                str(ch.get("id", i)),
                engine=engine,
                voice=voice,
                speed=speed,
                read_headings=read_headings,
                force=force,
                progress_cb=_tts_progress_cb,
            )
            audio_path = project_file(project_id, result.get("audio_path"))
            if audio_path and audio_path.exists():
                audio_files.append(audio_path)

        if single_file and audio_files:
            _set_task(task_id, "running", "Merging audio files…", 95, stage="Merging")
            import subprocess
            ffmpeg_exe = shutil.which("ffmpeg")
            ffprobe_exe = shutil.which("ffprobe")
            if ffmpeg_exe is None:
                logger.warning("FFmpeg not found on PATH; skipping merge.")
                save_chapters(project_id, chapters)
                _set_task(task_id, "error",
                          "FFmpeg not found. Please reinstall narratible to trigger FFmpeg installation.", 95, stage="Error")
                _persist_tts_status(
                    "error",
                    "Error",
                    "FFmpeg not found. Please reinstall narratible to trigger FFmpeg installation.",
                    95,
                    error="FFmpeg not found",
                )
                return
            list_path = exports_dir / "concat_list.txt"
            with open(list_path, "w", encoding="utf-8") as f:
                for audio_path in audio_files:
                    ffmpeg_path = str(audio_path.resolve()).replace("\\", "/")
                    f.write(f"file '{ffmpeg_path}'\n")

            fmt, codec_args = resolve_merge_format(audio_format)
            safe_book = _sanitize_filename(meta.title, "audiobook")
            merged_path = exports_dir / f"{safe_book}.{fmt}"

            # Build ffmetadata with chapter markers if ffprobe is available
            metadata_path = exports_dir / "ffmetadata.txt"
            chapters_metadata_written = False
            if ffprobe_exe:
                try:
                    cursor_ms = 0
                    chapter_entries = []
                    # audio_files and chapters are parallel - zip by position
                    for audio_path, ch in zip(audio_files, chapters):
                        result = subprocess.run(
                            [ffprobe_exe, "-v", "error", "-show_entries",
                             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                             str(audio_path)],
                            capture_output=True, text=True, check=True
                        )
                        duration_ms = int(float(result.stdout.strip()) * 1000)
                        chapter_entries.append((cursor_ms, cursor_ms + duration_ms, ch.get("title", "")))
                        cursor_ms += duration_ms

                    lines = [";FFMETADATA1\n"]
                    if meta.title:
                        lines.append(f"title={meta.title}\n")
                    if meta.author:
                        lines.append(f"artist={meta.author}\n")
                        lines.append(f"album_artist={meta.author}\n")
                    # album = title groups chapters under the book in audiobook players
                    if meta.title:
                        lines.append(f"album={meta.title}\n")
                    lines.append("genre=Audiobook\n")
                    # year from created_at (e.g. "2026-06-18T...")
                    try:
                        lines.append(f"date={meta.created_at[:4]}\n")
                    except Exception:
                        pass
                    lines.append("\n")
                    for start_ms, end_ms, ch_title in chapter_entries:
                        lines.append("[CHAPTER]\n")
                        lines.append("TIMEBASE=1/1000\n")
                        lines.append(f"START={start_ms}\n")
                        lines.append(f"END={end_ms}\n")
                        if ch_title:
                            lines.append(f"title={ch_title}\n")
                        lines.append("\n")
                    metadata_path.write_text("".join(lines), encoding="utf-8")
                    chapters_metadata_written = True
                    logger.info(f"Wrote ffmetadata with {len(chapter_entries)} chapters.")
                except Exception as e:
                    logger.warning(f"Failed to build chapter metadata: {e}. Merging without chapters.")

            # Resolve cover art path
            cover_path: Path | None = None
            if fmt == "m4b" and meta.cover_image:
                candidate = _project_path(project_id) / meta.cover_image
                if candidate.exists():
                    cover_path = candidate

            try:
                cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path)]
                metadata_input_index: int | None = None
                cover_input_index: int | None = None
                next_input = 1
                if chapters_metadata_written:
                    cmd += ["-i", str(metadata_path)]
                    metadata_input_index = next_input
                    next_input += 1
                if cover_path:
                    cmd += ["-i", str(cover_path)]
                    cover_input_index = next_input
                    next_input += 1
                # Map streams: audio from concat input, optionally cover art
                cmd += ["-map", "0:a"]
                if cover_input_index is not None:
                    cmd += ["-map", f"{cover_input_index}:v",
                            "-c:v", "copy",
                            f"-disposition:{cover_input_index - 1}:v", "attached_pic"]
                if metadata_input_index is not None:
                    cmd += ["-map_metadata", str(metadata_input_index)]
                cmd += [*codec_args, str(merged_path)]
                subprocess.run(
                    cmd,
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
                )
                # optionally clean up individual chapters
                list_path.unlink(missing_ok=True)
                metadata_path.unlink(missing_ok=True)
            except subprocess.CalledProcessError as e:
                logger.warning(f"FFmpeg failed to merge audio: {e}\nstderr: {e.stderr}")
            except Exception as e:
                logger.warning(f"FFmpeg failed to merge audio: {e}")

        _set_task(task_id, "done", "Audio synthesis complete.", 100, stage="Done")
        _persist_tts_status(
            "done",
            "Done",
            "Audio synthesis complete.",
            100,
            extra={"chapter_count": len(audio_files), "single_file": bool(single_file), "format": audio_format},
        )
    except Exception as e:
        logger.exception("TTS task failed")
        _set_task(task_id, "error", str(e), 0, stage="Error")
        _persist_tts_status("error", "Error", str(e), 0, error=str(e))


@app.post("/api/projects/{project_id}/tts/synthesize")
async def synthesize_book(
    project_id: str,
    background_tasks: BackgroundTasks,
    engine: str = "edge-tts",
    voice: str = "en-US-AriaNeural",
    speed: float = 1.0,
    single_file: bool = False,
    audio_format: str = "m4b",
    read_headings: bool = True,
    force: bool = False,
):
    try:
        get_project(project_id)
        if engine == "f5-tts":
            _resolve_f5_voice_reference(project_id, voice)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"tts-{project_id}"
    _set_task(task_id, "running", "Queued…", 0, stage="Queued")
    background_tasks.add_task(_run_tts, project_id, task_id, engine, voice, speed, single_file, audio_format, read_headings, force)
    return {"task_id": task_id}


async def _run_chapter_tts(project_id: str, chapter_id: str, task_id: str, force: bool):
    try:
        meta = get_project(project_id)
        _set_task(task_id, "running", "Synthesizing chapter…", 10)

        def _progress_cb(msg: str, pct: int = 0):
            _set_task(task_id, "running", msg, max(10, min(95, pct)))

        result = await synthesize_project_chapter(
            project_id,
            chapter_id,
            engine=meta.tts_engine,
            voice=meta.tts_voice,
            speed=meta.tts_speed,
            read_headings=meta.tts_read_headings,
            force=force,
            progress_cb=_progress_cb,
        )
        message = "Chapter audio is current." if result["status"] == "skipped" else "Chapter audio generated."
        _set_task(task_id, "done", message, 100)
    except Exception as e:
        logger.exception("Chapter TTS task failed")
        _set_task(task_id, "error", str(e), 0)


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/tts")
async def synthesize_chapter(project_id: str, chapter_id: str, background_tasks: BackgroundTasks, force: bool = False):
    try:
        get_project(project_id)
        _find_chapter(load_chapters(project_id), chapter_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"tts-{project_id}-{chapter_id}"
    _set_task(task_id, "running", "Queued…", 0)
    background_tasks.add_task(_run_chapter_tts, project_id, chapter_id, task_id, force)
    return {"task_id": task_id}


@app.get("/api/projects/{project_id}/chapters/{chapter_id}/audio")
async def get_chapter_audio(project_id: str, chapter_id: str):
    try:
        get_project(project_id)
        _, chapter = _find_chapter(load_chapters(project_id), chapter_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    audio_path = project_file(project_id, (chapter.get("tts") or {}).get("audio_path") or chapter.get("audio_path"))
    if not audio_path or not audio_path.exists():
        raise HTTPException(status_code=404, detail="Chapter audio not found.")
    return FileResponse(audio_path, media_type="audio/mpeg", filename=audio_path.name)


# ── Voice Sample Upload (for F5-TTS cloning) ──────────────────────────────────

def _voices_dir(project_id: str) -> Path:
    return _project_path(project_id) / "voices"


def _resolve_voice_sample_path(project_id: str, filename: str) -> Path:
    sample_name = Path(filename or "").name
    if not sample_name or sample_name != filename or Path(sample_name).suffix.lower() not in VOICE_SAMPLE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Invalid voice sample filename.")
    return _voices_dir(project_id) / sample_name

@app.post("/api/projects/{project_id}/voices/upload")
async def upload_voice_sample(project_id: str, file: UploadFile = File(...)):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    suffix = Path(file.filename).suffix.lower() if file.filename else ".wav"
    if suffix not in VOICE_SAMPLE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Voice sample must be WAV, MP3, or FLAC.")

    voices_dir = _voices_dir(project_id)
    voices_dir.mkdir(exist_ok=True)
    dest = voices_dir / (Path(file.filename).name if file.filename else f"sample{suffix}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"message": "Voice sample uploaded.", "filename": dest.name}


@app.get("/api/projects/{project_id}/voices")
async def list_voice_samples(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    voices_dir = _voices_dir(project_id)
    if not voices_dir.exists():
        return {"voices": []}
    return {"voices": sorted(f.name for f in voices_dir.iterdir() if f.is_file() and f.suffix.lower() in VOICE_SAMPLE_SUFFIXES)}


@app.delete("/api/projects/{project_id}/voices/{filename}")
async def delete_voice_sample(project_id: str, filename: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    sample_path = _resolve_voice_sample_path(project_id, filename)
    if not sample_path.exists() or not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Voice sample not found.")
    sample_path.unlink()
    return {"message": "Voice sample removed.", "filename": sample_path.name}


# ── Export ────────────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/export/epub")
async def export_epub(project_id: str, include_notes: bool = False):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    chapters = load_chapters(project_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters to export. Parse the PDF first.")

    exports_dir = _project_path(project_id) / "exports"
    exports_dir.mkdir(exist_ok=True)
    output_path = exports_dir / f"{_preferred_epub_stem(meta)}.epub"

    cover_path = None
    if meta.cover_image:
        candidate = _project_path(project_id) / meta.cover_image
        if candidate.exists():
            cover_path = candidate

    try:
        build_epub(
            output_path=output_path,
            title=meta.title,
            author=meta.author,
            language=meta.language,
            description=meta.description,
            publisher=meta.publisher,
            subject=meta.subject,
            isbn=meta.isbn,
            series=meta.series,
            chapters=chapters,
            cover_image_path=cover_path,
            include_notes=include_notes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(output_path, media_type="application/epub+zip", filename=output_path.name)


@app.get("/api/projects/{project_id}/exports")
async def list_exports(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    exports_dir = _project_path(project_id) / "exports"
    files = [f.name for f in exports_dir.iterdir() if f.is_file()] if exports_dir.exists() else []
    chapter_audio_files = set()
    for chapter in load_chapters(project_id):
        audio_path = project_file(project_id, (chapter.get("tts") or {}).get("audio_path") or chapter.get("audio_path"))
        if audio_path and audio_path.exists() and audio_path.parent == audio_dir(project_id):
            chapter_audio_files.add(audio_path.name)
    audio_files = sorted(chapter_audio_files)
    return {"files": sorted(files + audio_files)}


@app.get("/api/projects/{project_id}/exports/{filename}")
async def download_export(project_id: str, filename: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    exports_dir = (_project_path(project_id) / "exports").resolve()
    audio_artifacts_dir = audio_dir(project_id).resolve()
    file_path = (exports_dir / safe_filename).resolve()
    if not file_path.exists():
        file_path = (audio_artifacts_dir / safe_filename).resolve()
        if not str(file_path).startswith(str(audio_artifacts_dir)):
            raise HTTPException(status_code=400, detail="Invalid filename.")
    elif not str(file_path).startswith(str(exports_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path, filename=safe_filename)


@app.delete("/api/projects/{project_id}/exports/{filename}")
async def delete_export(project_id: str, filename: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    exports_dir = (_project_path(project_id) / "exports").resolve()
    audio_artifacts_dir = audio_dir(project_id).resolve()
    export_candidate = (exports_dir / safe_filename).resolve()
    audio_candidate = (audio_artifacts_dir / safe_filename).resolve()

    file_path: Path | None = None
    is_chapter_audio = False

    if export_candidate.exists() and str(export_candidate).startswith(str(exports_dir)):
        file_path = export_candidate
    elif audio_candidate.exists() and str(audio_candidate).startswith(str(audio_artifacts_dir)):
        file_path = audio_candidate
        is_chapter_audio = True

    if file_path is None or not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    file_path.unlink()

    if is_chapter_audio:
        changed = False
        now_iso = datetime.now(timezone.utc).isoformat()
        chapters = load_chapters(project_id)
        for chapter in chapters:
            rel_path = (chapter.get("tts") or {}).get("audio_path") or chapter.get("audio_path")
            if rel_path and Path(rel_path).name == safe_filename:
                tts_state = dict(chapter.get("tts") or {})
                tts_state["status"] = "missing"
                tts_state["error"] = None
                tts_state["updated_at"] = now_iso
                chapter["tts"] = tts_state
                changed = True
        if changed:
            save_chapters(project_id, chapters)

    return {"message": "Export removed.", "filename": safe_filename}


# ── Audiobookshelf ────────────────────────────────────────────────────────────

class UploadToAbsRequest(BaseModel):
    library_id: str
    files: list[str]  # filenames from the exports directory


@app.get("/api/audiobookshelf/libraries")
async def abs_libraries():
    cfg = load_config()
    if not cfg.audiobookshelf_url or not cfg.audiobookshelf_token:
        raise HTTPException(status_code=400, detail="Audiobookshelf URL and token are not configured.")
    try:
        uploader = AudiobookshelfUploader(cfg.audiobookshelf_url, cfg.audiobookshelf_token)
        return {"libraries": uploader.get_libraries()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/projects/{project_id}/upload-to-abs")
async def upload_to_abs(project_id: str, req: UploadToAbsRequest):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    cfg = load_config()
    if not cfg.audiobookshelf_url or not cfg.audiobookshelf_token:
        raise HTTPException(status_code=400, detail="Audiobookshelf URL and token are not configured.")

    exports_dir = (_project_path(project_id) / "exports").resolve()
    file_paths = []
    for fname in req.files:
        candidate = (exports_dir / fname).resolve()
        if not str(candidate).startswith(str(exports_dir)):
            raise HTTPException(status_code=400, detail=f"Invalid filename: {fname}")
        file_paths.append(candidate)

    try:
        uploader = AudiobookshelfUploader(cfg.audiobookshelf_url, cfg.audiobookshelf_token)
        result = uploader.upload_files(req.library_id, meta.title, meta.author, file_paths)
        return {"message": "Upload successful.", "result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Task Status ───────────────────────────────────────────────────────────────

@app.post("/api/tasks/{task_id}/decision")
async def submit_task_decision(task_id: str, req: TaskDecisionRequest):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    pending = task.get("pending_decision")
    if not pending:
        raise HTTPException(status_code=409, detail="Task is not waiting for a decision.")
    choices = pending.get("choices", [])
    if req.action not in choices:
        raise HTTPException(status_code=400, detail="Invalid decision for this task.")
    task["decision_response"] = req.action
    save_task_snapshot(_tasks)
    return {"ok": True}

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _tasks[task_id]


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp_server = create_mcp_server(lambda: _tasks, streamable_http_path="/")
app.mount("/mcp", mcp_server.streamable_http_app())


# ── Static Frontend Serving (PyInstaller Packaged) ────────────────────────────
from fastapi.responses import HTMLResponse

if getattr(sys, "frozen", False):
    frontend_dist = Path(sys._MEIPASS) / "frontend_dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
        
        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            # Fallback to index.html for SPA routing
            local_path = frontend_dist / full_path
            if local_path.is_file() and full_path != "":
                return FileResponse(local_path)
            return FileResponse(frontend_dist / "index.html")
