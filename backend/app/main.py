import logging
import shutil
import os
import sys
import tempfile
from pathlib import Path
import psutil

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Query, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

from .config import AppConfig, load_config, save_config, get_device_string
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
    _project_path,
)
from .parser import extract_structured_from_pdf
from .cleaner import regex_clean_text, llm_clean_text, llm_review_chapters
from .parsing_modules import list_modules, apply_modules, normalize_module_ids
from .tts import synthesize_speech, get_available_voices, compose_tts_text
from .tts_text import prepare_text_for_tts, segment_text_for_tts
from .epub import build_epub
from .uploader import AudiobookshelfUploader
from .voices import (
    create_library_voice,
    delete_library_voice,
    get_library_voice,
    get_library_voice_preview_path,
    get_library_voice_sample_path,
    list_library_voices,
    update_library_voice,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="narratible API", version="0.1.0")
VOICE_SAMPLE_SUFFIXES = {".wav", ".mp3", ".flac"}

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
# Maps task_id -> {"status": "running"|"done"|"error"|"cancelled", "stage": str, "message": str, "progress": 0-100, "is_cancelled": bool, "llm_output": str}
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
    _tasks[task_id] = {
        "status": status,
        "stage": _stage,
        "message": _message,
        "progress": _progress,
        "is_cancelled": _is_cancelled,
        "llm_output": _llm_output
    }

def _get_task(task_id: str):
    return _tasks.get(task_id)

@app.post("/api/projects/{project_id}/cancel")
async def api_cancel_task(project_id: str):
    task_id = f"parse-{project_id}"
    task = _get_task(task_id)
    if task:
        task["is_cancelled"] = True
    
    # Also attempt to cancel TTS tasks if they are running under tts-{project_id}
    tts_task_id = f"tts-{project_id}"
    tts_task = _get_task(tts_task_id)
    if tts_task:
        tts_task["is_cancelled"] = True

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
    save_config(config)
    return config


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

    dest = _project_path(project_id) / "book.pdf"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"message": "PDF uploaded successfully.", "path": str(dest)}


def _run_parse(project_id: str, task_id: str, cleaner: str, modules: list[str] | None = None):
    modules = normalize_module_ids(modules)
    try:
        meta = update_project(project_id, {"enabled_modules": modules})
        _set_task(task_id, "running", "Reading PDF…", 10, stage="Extracting text")
        pdf_path = _project_path(project_id) / "book.pdf"
        if not pdf_path.exists():
            raise FileNotFoundError("book.pdf not found. Upload a PDF first.")

        def _extract_progress(msg: str, frac: float):
            # Map extraction fraction (0..1) into the 10–28 progress band.
            pct = 10 + int(max(0.0, min(1.0, frac)) * 18)
            _set_task(task_id, "running", msg, pct, stage="Extracting text")

        pdf_data = extract_structured_from_pdf(pdf_path, progress_callback=_extract_progress)
        raw_text = pdf_data["raw_text"]
        raw_chapters = pdf_data["chapters"]
        
        raw_path = _project_path(project_id) / "raw_text.txt"
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
                cfg = load_config()
                lp = cfg.llm_provider
                if lp == "local":
                    review_provider = "embedded"
                elif lp in ("gemini", "openai"):
                    review_provider = lp
                else:
                    review_provider = "gemini" if cfg.gemini_api_key else "openai"
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
                    "PDF has an embedded table of contents — normally chapter review "
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
        
        if cleaner in ("llm", "embedded"):
            if cleaner == "embedded":
                provider = "embedded"
            else:
                cfg = load_config()
                lp = cfg.llm_provider
                if lp == "local":
                    provider = "embedded"
                elif lp in ("gemini", "openai"):
                    provider = lp
                else:
                    # "none" or unconfigured — fall back to key-based detection
                    provider = "gemini" if cfg.gemini_api_key else "openai"
                
            def _cancel_check():
                t = _get_task(task_id)
                return t and t.get("is_cancelled", False)
                
            try:
                for i, ch in enumerate(raw_chapters):
                    if _cancel_check():
                        break
                        
                    ch_title = ch["title"]
                    
                    def _progress_cb(msg: str, pct: int):
                        # Localize progress over total chapters
                        base_prog = 30 + int((i / len(raw_chapters)) * 50)
                        overall_prog = base_prog + int((pct / 100) * (50 / len(raw_chapters)))
                        _set_task(task_id, "running", f"Cleaning '{ch_title}' — {msg}", overall_prog, stage="Cleaning text")

                    def _output_cb(chunk_text: str):
                        # We just append whatever token/text we received directly
                        _set_task(task_id, "running", append_output=chunk_text)

                    cleaned_ch_text = llm_clean_text(
                        regex_clean_text(
                            ch["raw_text"],
                            known_titles=[meta.title, ch_title],
                        ),
                        provider=provider, 
                        progress_callback=_progress_cb, 
                        cancel_check=_cancel_check, 
                        output_callback=_output_cb
                    )
                    
                    cleaned_chapters.append({
                        "title": ch_title,
                        "text": cleaned_ch_text,
                        "audio_path": None,
                        "confidence": ch.get("confidence", 1.0),
                        "warnings": ch.get("warnings", [])
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
                # Map regex cleaning across the 30–88 band so the bar keeps moving.
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
                    "audio_path": None,
                    "confidence": ch.get("confidence", 1.0),
                    "warnings": ch.get("warnings", [])
                })
                full_cleaned_text += cleaned_txt + "\n\n"

        # Unload the LLM from VRAM *after* all chapters are done parsing.
        # Covers any path that may have loaded the embedded model — full embedded
        # cleaning as well as the embedded chapter-review debug cleaner.
        if cleaner in ("embedded", "llm_chapters_only_embedded"):
            from app.cleaner import unload_llm
            unload_llm()

        t = _get_task(task_id)
        if t and t.get("is_cancelled"):
            _set_task(task_id, "cancelled", "Processing cancelled.", t.get("progress", 0), stage="Cancelled")
            return

        # Apply optional parsing modules (deterministic, offline text transforms)
        # to each cleaned chapter, then rebuild the full text from the result.
        if modules:
            _set_task(task_id, "running", "Applying parsing modules…", 89, stage="Parsing modules")
            full_cleaned_text = ""
            for ch in cleaned_chapters:
                ch["text"] = apply_modules(ch["text"], modules)
                full_cleaned_text += ch["text"] + "\n\n"

        cleaned_path = _project_path(project_id) / "cleaned_text.txt"
        cleaned_path.write_text(full_cleaned_text.strip(), encoding="utf-8")
        
        # We no longer need to auto-split because we split natively!
        _set_task(task_id, "running", "Saving chapters…", 90, stage="Saving")

        chapters = cleaned_chapters
        save_chapters(project_id, chapters)
        _set_task(task_id, "done", f"Parsed {len(chapters)} chapter(s) via {pdf_data.get('method', 'unknown')}.", 100, stage="Done")
    except Exception as e:
        logger.exception("Parse task failed")
        _set_task(task_id, "error", str(e), 0, stage="Error")


@app.post("/api/projects/{project_id}/parse")
async def parse_pdf(
    project_id: str,
    background_tasks: BackgroundTasks,
    cleaner: str = "regex",
    modules: list[str] = Query(default=[]),
):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"parse-{project_id}"
    _set_task(task_id, "running", "Queued…", 0, stage="Queued")
    background_tasks.add_task(_run_parse, project_id, task_id, cleaner, modules)
    return {"task_id": task_id}


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
    return {"message": f"Saved {len(chapters)} chapter(s)."}


# ── Cover Image Upload ────────────────────────────────────────────────────────

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
    speed: float | None = None


def _resolve_f5_voice_reference(project_id: str, voice: str):
    if voice and voice != "__uploaded__":
        library_voice = get_library_voice(voice)
        return get_library_voice_sample_path(voice), None, library_voice.reference_text, library_voice.temperature
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


@app.post("/api/voice-library/test-draft")
async def api_test_voice_library_draft(
    text: str = Form(...),
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
            temperature=voice.temperature,
            voice_sample_path=get_library_voice_sample_path(voice_id),
            voice_reference_text=voice.reference_text,
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


async def _run_tts(project_id: str, task_id: str, engine: str, voice: str, speed: float,
                   single_file: bool = False, audio_format: str = "m4b",
                   read_headings: bool = True):
    try:
        meta = get_project(project_id)
        chapters = load_chapters(project_id)
        if not chapters:
            raise ValueError("No chapters found. Parse the PDF first.")

        exports_dir = _project_path(project_id) / "exports"
        exports_dir.mkdir(exist_ok=True)

        audio_files = []

        for i, ch in enumerate(chapters):
            t = _get_task(task_id)
            if t and t.get("is_cancelled"):
                _set_task(task_id, "error", "Task was cancelled.", t.get("progress", 0))
                return

            progress = int((i / len(chapters)) * 90)
            ch_title = ch.get("title", f"Chapter {i + 1}")
            _set_task(task_id, "running", f"Chapter {i + 1}/{len(chapters)}: {ch_title} — Synthesizing…", progress)
            safe_ch = _sanitize_filename(ch_title, f"chapter_{i + 1}")
            audio_path = exports_dir / f"{i + 1:03d}_{safe_ch}.mp3"
            voice_sample_path = None
            voice_reference_text = None
            voice_samples_dir = None
            voice_temperature = None
            if engine == "f5-tts":
                voice_sample_path, voice_samples_dir, voice_reference_text, voice_temperature = _resolve_f5_voice_reference(project_id, voice)

            def _tts_progress_cb(msg: str, _pct: int = 0, _task_id: str = task_id, _base: int = progress):
                _set_task(_task_id, "running", msg, _base)

            await synthesize_speech(
                text=compose_tts_text(ch_title, ch.get("text", ""), read_headings),
                output_path=audio_path,
                engine=engine,
                voice=voice,
                speed=speed,
                temperature=voice_temperature if voice_temperature is not None else 0.7,
                voice_sample_path=voice_sample_path,
                voice_reference_text=voice_reference_text,
                voice_samples_dir=voice_samples_dir,
                progress_cb=_tts_progress_cb,
                enabled_modules=meta.enabled_modules,
            )
            audio_files.append(audio_path)
            chapters[i]["audio_path"] = str(audio_path)

        if single_file and audio_files:
            _set_task(task_id, "running", "Merging audio files…", 95)
            import subprocess
            ffmpeg_exe = shutil.which("ffmpeg")
            if ffmpeg_exe is None:
                logger.warning("FFmpeg not found on PATH; skipping merge.")
                save_chapters(project_id, chapters)
                _set_task(task_id, "error",
                          "FFmpeg not found. Please reinstall narratible to trigger FFmpeg installation.", 95)
                return
            list_path = exports_dir / "concat_list.txt"
            with open(list_path, "w", encoding="utf-8") as f:
                for audio_path in audio_files:
                    f.write(f"file '{audio_path.name}'\n")

            fmt, codec_args = resolve_merge_format(audio_format)
            safe_book = _sanitize_filename(meta.title, "audiobook")
            merged_path = exports_dir / f"{safe_book}.{fmt}"
            try:
                subprocess.run(
                    [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
                     *codec_args, str(merged_path)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
                )
                # optionally clean up individual chapters
                list_path.unlink(missing_ok=True)
            except subprocess.CalledProcessError as e:
                logger.warning(f"FFmpeg failed to merge audio: {e}\nstderr: {e.stderr}")
            except Exception as e:
                logger.warning(f"FFmpeg failed to merge audio: {e}")

        save_chapters(project_id, chapters)
        _set_task(task_id, "done", "Audio synthesis complete.", 100)
    except Exception as e:
        logger.exception("TTS task failed")
        _set_task(task_id, "error", str(e), 0)


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
):
    try:
        get_project(project_id)
        if engine == "f5-tts":
            _resolve_f5_voice_reference(project_id, voice)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"tts-{project_id}"
    _set_task(task_id, "running", "Queued…", 0)
    background_tasks.add_task(_run_tts, project_id, task_id, engine, voice, speed, single_file, audio_format, read_headings)
    return {"task_id": task_id}


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
async def export_epub(project_id: str):
    try:
        meta = get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    chapters = load_chapters(project_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters to export. Parse the PDF first.")

    exports_dir = _project_path(project_id) / "exports"
    exports_dir.mkdir(exist_ok=True)
    safe_title = "".join(c for c in meta.title if c.isalnum() or c in " _-").strip() or "book"
    output_path = exports_dir / f"{safe_title}.epub"

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
            chapters=chapters,
            cover_image_path=cover_path,
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
    if not exports_dir.exists():
        return {"files": []}
    return {"files": [f.name for f in exports_dir.iterdir() if f.is_file()]}


@app.get("/api/projects/{project_id}/exports/{filename}")
async def download_export(project_id: str, filename: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    exports_dir = (_project_path(project_id) / "exports").resolve()
    file_path = (exports_dir / filename).resolve()
    if not str(file_path).startswith(str(exports_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path, filename=filename)


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

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _tasks[task_id]


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
