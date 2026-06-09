import logging
import shutil
from pathlib import Path
import psutil

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import AppConfig, load_config, save_config
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
from .cleaner import regex_clean_text, llm_clean_text
from .tts import synthesize_speech, get_available_voices
from .epub import build_epub
from .uploader import AudiobookshelfUploader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Echo-Scribe API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory task status store ──────────────────────────────────────────────
# Maps task_id -> {"status": "running"|"done"|"error", "message": str, "progress": 0-100, "is_cancelled": bool, "llm_output": str}
_tasks: dict[str, dict] = {}


def _set_task(task_id: str, status: str, message: str = "", progress: int = 0, is_cancelled: bool = False, append_output: str = None):
    existing = _tasks.get(task_id, {})
    _is_cancelled = existing.get("is_cancelled", False) if not is_cancelled else is_cancelled
    _llm_output = existing.get("llm_output", "")
    if append_output:
        _llm_output += append_output
    _tasks[task_id] = {
        "status": status, 
        "message": message, 
        "progress": progress, 
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


@app.get("/api/system/diagnostics")
async def system_diagnostics():
    cpu = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    info = {
        "cpu_percent": cpu,
        "ram_total_mb": round(memory.total / 1024**2),
        "ram_used_mb": round(memory.used / 1024**2),
        "ram_percent": memory.percent,
        "vram_total_mb": 0,
        "vram_used_mb": 0,
        "vram_percent": 0.0,
    }
    try:
        import torch
        if torch.cuda.is_available():
            vram_total = torch.cuda.get_device_properties(0).total_memory
            vram_allocated = torch.cuda.memory_allocated(0)
            info["vram_total_mb"] = round(vram_total / 1024**2)
            info["vram_used_mb"] = round(vram_allocated / 1024**2)
            info["vram_percent"] = round((vram_allocated / vram_total) * 100, 1) if vram_total > 0 else 0.0
    except Exception:
        pass

    return info


@app.get("/api/system/info")
async def system_info():
    """Returns GPU/CUDA availability — useful for debugging device selection."""
    info: dict = {"cuda_available": False, "gpu_name": None, "torch_version": None}
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["vram_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 2)
    except ImportError:
        info["torch_version"] = "not installed"
    return info


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings", response_model=AppConfig)
async def get_settings():
    return load_config()


@app.put("/api/settings", response_model=AppConfig)
async def update_settings(config: AppConfig):
    save_config(config)
    return config


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

class LLMModelsResponse(BaseModel):
    system_vram_mb: int
    families: list[LLMFamily]

@app.get("/api/llm/models", response_model=LLMModelsResponse)
async def get_llm_models():
    """Returns local LLM recommendations based on available CUDA VRAM."""
    vram_mb = 0
    try:
        import torch
        if torch.cuda.is_available():
            vram_mb = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 2)
    except (ImportError, RuntimeError):
        pass
    
    families_data = [
        {
            "name": "Qwen 2.5",
            "description": "Very fast, highly capable models. Great for quick cleanup tasks on older systems. May struggle with extremely complex margins at smaller sizes.",
            "variants": [
                ("Qwen/Qwen2.5-0.5B-Instruct", "0.5B", 2000, False),
                ("Qwen/Qwen2.5-1.5B-Instruct", "1.5B", 4000, False),
                ("Qwen/Qwen2.5-7B-Instruct", "7B", 14000, False),
            ]
        },
        {
            "name": "Gemma 4",
            "description": "Excellent reasoning and instruction following. Punches well above its weight class for its size.",
            "variants": [
                ("google/gemma-4-E4B-it", "E4B", 5500, True),
                ("google/gemma-4-12B-it", "12B", 24000, True),
                ("google/gemma-4-31B-it", "31B", 62000, True),
            ]
        },
        {
            "name": "Phi-3",
            "description": "Microsoft's high quality reasoning model. Best for structured formatting and handling margin notes gracefully.",
            "variants": [
                ("microsoft/Phi-3-mini-4k-instruct", "Mini (3.8B)", 8000, False),
                ("microsoft/Phi-3-small-8k-instruct", "Small (7B)", 15000, False),
            ]
        },
        {
            "name": "Llama 3",
            "description": "Production-grade performance and excellent instruction following. Meta's latest lightweight and medium-weight models.",
            "variants": [
                ("meta-llama/Llama-3.2-1B-Instruct", "3.2 (1B)", 3500, True),
                ("meta-llama/Llama-3.2-3B-Instruct", "3.2 (3B)", 7500, True),
                ("meta-llama/Meta-Llama-3.1-8B-Instruct", "3.1 (8B)", 16000, True),
            ]
        }
    ]
    
    families = []
    for f in families_data:
        variants = []
        for v_id, v_name, v_min_vram, v_gated in f["variants"]:
            variants.append(LLMVariant(
                id=v_id,
                name=v_name,
                min_vram_mb=v_min_vram,
                base_vram_mb=v_min_vram,
                recommended=vram_mb >= v_min_vram if vram_mb > 0 else True,
                gated=v_gated
            ))
        families.append(LLMFamily(name=f["name"], description=f["description"], variants=variants))
    
    return LLMModelsResponse(system_vram_mb=vram_mb, families=families)


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


def _run_parse(project_id: str, task_id: str, cleaner: str):
    try:
        _set_task(task_id, "running", "Extracting text and analyzing structure from PDF…", 10)
        pdf_path = _project_path(project_id) / "book.pdf"
        if not pdf_path.exists():
            raise FileNotFoundError("book.pdf not found. Upload a PDF first.")

        pdf_data = extract_structured_from_pdf(pdf_path)
        raw_text = pdf_data["raw_text"]
        raw_chapters = pdf_data["chapters"]
        
        raw_path = _project_path(project_id) / "raw_text.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        _set_task(task_id, "running", "Cleaning text…", 30)

        cleaned_chapters = []
        full_cleaned_text = ""
        
        if cleaner in ("llm", "embedded"):
            if cleaner == "embedded":
                provider = "embedded"
            else:
                cfg = load_config()
                provider = "gemini" if cfg.gemini_api_key else "openai"
                
            def _cancel_check():
                t = _get_task(task_id)
                return t and t.get("is_cancelled", False)
                
            for i, ch in enumerate(raw_chapters):
                if _cancel_check():
                    break
                    
                ch_title = ch["title"]
                
                def _progress_cb(msg: str, pct: int):
                    # Localize progress over total chapters
                    base_prog = 30 + int((i / len(raw_chapters)) * 50)
                    overall_prog = base_prog + int((pct / 100) * (50 / len(raw_chapters)))
                    _set_task(task_id, "running", f"Cleaning '{ch_title}' - {msg}", overall_prog)

                def _output_cb(chunk_text: str):
                    _set_task(task_id, "running", append_output=chunk_text + "\n\n")

                cleaned_ch_text = llm_clean_text(
                    ch["raw_text"], 
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
        else:
            for ch in raw_chapters:
                cleaned_txt = regex_clean_text(ch["raw_text"])
                cleaned_chapters.append({
                    "title": ch["title"],
                    "text": cleaned_txt,
                    "audio_path": None,
                    "confidence": ch.get("confidence", 1.0),
                    "warnings": ch.get("warnings", [])
                })
                full_cleaned_text += cleaned_txt + "\n\n"

        t = _get_task(task_id)
        if t and t.get("is_cancelled"):
            _set_task(task_id, "error", "Task was cancelled.", t.get("progress", 0))
            return

        cleaned_path = _project_path(project_id) / "cleaned_text.txt"
        cleaned_path.write_text(full_cleaned_text.strip(), encoding="utf-8")
        
        # We no longer need to auto-split because we split natively!
        _set_task(task_id, "running", "Saving chapters…", 90)

        chapters = cleaned_chapters
        save_chapters(project_id, chapters)
        _set_task(task_id, "done", f"Parsed {len(chapters)} chapter(s) via {pdf_data.get('method', 'unknown')}.", 100)
    except Exception as e:
        logger.exception("Parse task failed")
        _set_task(task_id, "error", str(e), 0)


@app.post("/api/projects/{project_id}/parse")
async def parse_pdf(
    project_id: str,
    background_tasks: BackgroundTasks,
    cleaner: str = "regex",
):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"parse-{project_id}"
    _set_task(task_id, "running", "Queued…", 0)
    background_tasks.add_task(_run_parse, project_id, task_id, cleaner)
    return {"task_id": task_id}


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


@app.post("/api/projects/{project_id}/tts/preview")
async def tts_preview(project_id: str, req: PreviewRequest):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    preview_path = _project_path(project_id) / "preview.mp3"
    try:
        voice_sample = _find_voice_sample(project_id) if req.engine == "f5-tts" else None
        await synthesize_speech(
            text=req.text[:500],
            output_path=preview_path,
            engine=req.engine,
            voice=req.voice,
            speed=req.speed,
            voice_sample_path=voice_sample,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(preview_path, media_type="audio/mpeg", filename="preview.mp3")


async def _run_tts(project_id: str, task_id: str, engine: str, voice: str, speed: float, single_file: bool = False):
    try:
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
            _set_task(task_id, "running", f"Synthesizing chapter {i + 1}/{len(chapters)}…", progress)
            audio_path = exports_dir / f"chapter{i + 1:03d}.mp3"
            voice_sample = _find_voice_sample(project_id) if engine == "f5-tts" else None
            await synthesize_speech(
                text=ch.get("text", ""),
                output_path=audio_path,
                engine=engine,
                voice=voice,
                speed=speed,
                voice_sample_path=voice_sample,
            )
            audio_files.append(audio_path)
            chapters[i]["audio_path"] = str(audio_path)

        if single_file and audio_files:
            _set_task(task_id, "running", "Merging audio files…", 95)
            import subprocess
            list_path = exports_dir / "concat_list.txt"
            with open(list_path, "w", encoding="utf-8") as f:
                for audio_path in audio_files:
                    f.write(f"file '{audio_path.name}'\n")
            
            merged_path = exports_dir / "audiobook.m4b"  # or .mp3
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(merged_path)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                # optionally clean up individual chapters
                list_path.unlink(missing_ok=True)
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
):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    task_id = f"tts-{project_id}"
    _set_task(task_id, "running", "Queued…", 0)
    background_tasks.add_task(_run_tts, project_id, task_id, engine, voice, speed, single_file)
    return {"task_id": task_id}


# ── Voice Sample Upload (for XTTS cloning) ────────────────────────────────────

@app.post("/api/projects/{project_id}/voices/upload")
async def upload_voice_sample(project_id: str, file: UploadFile = File(...)):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    suffix = Path(file.filename).suffix.lower() if file.filename else ".wav"
    if suffix not in (".wav", ".mp3", ".flac"):
        raise HTTPException(status_code=400, detail="Voice sample must be WAV, MP3, or FLAC.")

    voices_dir = _project_path(project_id) / "voices"
    voices_dir.mkdir(exist_ok=True)
    dest = voices_dir / (file.filename or f"sample{suffix}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"message": "Voice sample uploaded.", "filename": dest.name}


@app.get("/api/projects/{project_id}/voices")
async def list_voice_samples(project_id: str):
    try:
        get_project(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    voices_dir = _project_path(project_id) / "voices"
    if not voices_dir.exists():
        return {"voices": []}
    return {"voices": [f.name for f in voices_dir.iterdir() if f.is_file()]}


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_voice_sample(project_id: str) -> Path | None:
    """Return the first voice sample found in the project's voices/ dir, or None."""
    voices_dir = _project_path(project_id) / "voices"
    if not voices_dir.exists():
        return None
    for ext in (".wav", ".mp3", ".flac"):
        matches = list(voices_dir.glob(f"*{ext}"))
        if matches:
            return matches[0]
    return None
