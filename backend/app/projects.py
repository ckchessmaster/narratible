import uuid
import json
import shutil
import logging
import sys
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, Any

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    _app_data_dir = Path(os.environ.get('APPDATA', Path.home())) / "narratible"
    _app_data_dir.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR = _app_data_dir / "projects"
else:
    PROJECTS_DIR = Path(__file__).parent.parent / "projects"


class ProjectMetadata(BaseModel):
    id: str
    title: str
    author: str = ""
    language: str = "en"
    description: str = ""
    publisher: str = ""
    subject: str = ""
    isbn: str = ""
    series: str = ""
    created_at: str = Field(default_factory=lambda: _utc_now())
    updated_at: str = Field(default_factory=lambda: _utc_now())
    current_step: str = "upload"
    source_pdf: dict[str, str] | None = None
    cover_image: Optional[str] = None  # relative path inside project dir
    tts_engine: str = "edge-tts"
    tts_voice: str = "en-US-AriaNeural"
    tts_speed: float = 1.0
    tts_read_headings: bool = True
    enabled_modules: list[str] = Field(default_factory=list)
    chapter_count: int = 0
    last_parse_status: dict[str, Any] | None = None
    last_tts_status: dict[str, Any] | None = None
    review_flow_step: str | None = None
    review_flow_completed_steps: list[str] = Field(default_factory=list)
    review_flow_unlocked_at: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _metadata_path(project_id: str) -> Path:
    return _project_path(project_id) / "metadata.json"


def source_pdf_path(project_id: str) -> Path:
    return _project_path(project_id) / "source" / "original.pdf"


def audio_dir(project_id: str) -> Path:
    return _project_path(project_id) / "audio"


def artifact_dir(project_id: str) -> Path:
    return _project_path(project_id) / "artifacts"


def project_file(project_id: str, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return _project_path(project_id) / path


def _write_json_atomic(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def chapter_text_hash(title: str, text: str) -> str:
    """Hash the text that can affect synthesized chapter audio."""
    payload = f"{title or ''}\0{text or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tts_settings_hash(*, engine: str, voice: str, speed: float, read_headings: bool, enabled_modules: list[str] | None = None) -> str:
    settings = {
        "engine": engine,
        "voice": voice,
        "speed": round(float(speed), 3),
        "read_headings": bool(read_headings),
        "enabled_modules": sorted(enabled_modules or []),
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def list_projects() -> list[ProjectMetadata]:
    if not PROJECTS_DIR.exists():
        return []
    projects = []
    for folder in sorted(PROJECTS_DIR.iterdir()):
        meta_file = folder / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    projects.append(ProjectMetadata(**json.load(f)))
            except Exception as e:
                logger.warning(f"Skipping corrupt project {folder.name}: {e}")
    return projects


def get_project(project_id: str) -> ProjectMetadata:
    meta_file = _metadata_path(project_id)
    if not meta_file.exists():
        raise FileNotFoundError(f"Project '{project_id}' not found.")
    with open(meta_file, "r", encoding="utf-8") as f:
        return ProjectMetadata(**json.load(f))


def create_project(title: str, author: str = "") -> ProjectMetadata:
    project_id = str(uuid.uuid4())
    project_dir = _project_path(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "source").mkdir(exist_ok=True)
    (project_dir / "artifacts").mkdir(exist_ok=True)
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "voices").mkdir(exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    now = _utc_now()
    meta = ProjectMetadata(id=project_id, title=title, author=author, created_at=now, updated_at=now)
    _save_metadata(meta)
    logger.info(f"Created project {project_id}: {title}")
    return meta


def update_project(project_id: str, updates: dict) -> ProjectMetadata:
    meta = get_project(project_id)
    clean_updates = {key: value for key, value in updates.items() if key not in {"id", "created_at"}}
    tts_keys = {"tts_engine", "tts_voice", "tts_speed", "tts_read_headings", "enabled_modules"}
    tts_settings_changed = any(
        key in clean_updates and getattr(meta, key) != clean_updates[key]
        for key in tts_keys
    )
    clean_updates["updated_at"] = _utc_now()
    updated = meta.model_copy(update=clean_updates)
    _save_metadata(updated)
    if tts_settings_changed:
        mark_tts_stale_for_settings(project_id, updated)
    return updated


def delete_project(project_id: str):
    project_dir = _project_path(project_id)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project '{project_id}' not found.")
    shutil.rmtree(project_dir)
    logger.info(f"Deleted project {project_id}")


def _save_metadata(meta: ProjectMetadata):
    _write_json_atomic(_metadata_path(meta.id), meta.model_dump())


# ── Chapter helpers ────────────────────────────────────────────────────────────

def _chapters_path(project_id: str) -> Path:
    return _project_path(project_id) / "chapters.json"


def _cleaning_eval_path(project_id: str) -> Path:
    return _project_path(project_id) / "cleaning_eval.json"


def _modernization_eval_path(project_id: str) -> Path:
    return _project_path(project_id) / "modernization_eval.json"


def load_chapters(project_id: str) -> list[dict]:
    path = _chapters_path(project_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chapters(project_id: str, chapters: list[dict]):
    previous = load_chapters(project_id)
    normalized = normalize_chapters(chapters, previous)
    _write_json_atomic(_chapters_path(project_id), normalized)
    if _metadata_path(project_id).exists():
        update_project(project_id, {"chapter_count": len(normalized)})


def update_chapter(project_id: str, chapter_id: str, updates: dict) -> dict:
    chapters = load_chapters(project_id)
    for index, chapter in enumerate(chapters):
        if str(chapter.get("id", index)) == chapter_id:
            allowed = {key: updates[key] for key in ("title", "text", "order") if key in updates}
            chapters[index] = {**chapter, **allowed}
            save_chapters(project_id, chapters)
            return load_chapters(project_id)[index]
    raise FileNotFoundError(f"Chapter '{chapter_id}' not found.")


def normalize_chapters(chapters: list[dict], previous: list[dict] | None = None) -> list[dict]:
    previous = previous or []
    previous_by_id = {ch.get("id"): ch for ch in previous if ch.get("id")}
    normalized = []
    now = _utc_now()

    for index, chapter in enumerate(chapters):
        prior = previous_by_id.get(chapter.get("id")) or (previous[index] if index < len(previous) else {})
        title = chapter.get("title") or f"Chapter {index + 1}"
        text = chapter.get("text") or ""
        text_hash = chapter_text_hash(title, text)
        old_hash = prior.get("text_hash")
        chapter_id = chapter.get("id") or prior.get("id") or str(uuid.uuid4())
        tts = dict(chapter.get("tts") or prior.get("tts") or {})
        legacy_audio_path = chapter.get("audio_path") or prior.get("audio_path")
        if legacy_audio_path and not tts.get("audio_path"):
            tts["audio_path"] = legacy_audio_path
        if not tts.get("status"):
            tts["status"] = "complete" if tts.get("audio_path") else "not_generated"
        if not tts.get("text_hash") and tts.get("status") == "complete":
            tts["text_hash"] = old_hash or text_hash
        if old_hash and old_hash != text_hash:
            if tts.get("audio_path"):
                tts["status"] = "stale"
                tts["error"] = None
            else:
                tts["status"] = "not_generated"
        tts.setdefault("audio_path", None)
        tts.setdefault("text_hash", None)
        tts.setdefault("settings_hash", None)
        tts.setdefault("engine", None)
        tts.setdefault("voice", None)
        tts.setdefault("updated_at", None)
        tts.setdefault("error", None)

        normalized.append({
            **chapter,
            "id": chapter_id,
            "order": index + 1,
            "title": title,
            "text": text,
            "text_hash": text_hash,
            "updated_at": now if old_hash != text_hash else chapter.get("updated_at") or prior.get("updated_at") or now,
            "tts": tts,
            "audio_path": tts.get("audio_path"),
        })
    return normalized


def chapter_audio_current(chapter: dict, settings_hash: str, project_id: str | None = None) -> bool:
    tts = chapter.get("tts") or {}
    audio_path = tts.get("audio_path")
    if not (
        tts.get("status") == "complete"
        and tts.get("text_hash") == chapter.get("text_hash")
        and tts.get("settings_hash") == settings_hash
        and audio_path
    ):
        return False
    if project_id is None:
        return True
    resolved = project_file(project_id, audio_path)
    return bool(resolved and resolved.exists())


def mark_tts_stale_for_settings(project_id: str, meta: ProjectMetadata):
    chapters = load_chapters(project_id)
    if not chapters:
        return
    current_settings_hash = tts_settings_hash(
        engine=meta.tts_engine,
        voice=meta.tts_voice,
        speed=meta.tts_speed,
        read_headings=meta.tts_read_headings,
        enabled_modules=meta.enabled_modules,
    )
    changed = False
    now = _utc_now()
    for chapter in chapters:
        tts = chapter.get("tts") or {}
        if (
            tts.get("audio_path")
            and tts.get("status") == "complete"
            and tts.get("settings_hash") != current_settings_hash
        ):
            tts["status"] = "stale"
            tts["updated_at"] = now
            tts["error"] = None
            chapter["tts"] = tts
            changed = True
    if changed:
        _write_json_atomic(_chapters_path(project_id), chapters)


def load_cleaning_eval(project_id: str) -> dict | None:
    path = _cleaning_eval_path(project_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cleaning_eval(project_id: str, evaluation: dict):
    _write_json_atomic(_cleaning_eval_path(project_id), evaluation)


def load_modernization_eval(project_id: str) -> dict | None:
    path = _modernization_eval_path(project_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_modernization_eval(project_id: str, evaluation: dict):
    _write_json_atomic(_modernization_eval_path(project_id), evaluation)


def auto_split_chapters(text: str) -> list[dict]:
    """
    Heuristically split cleaned text into chapters using Markdown headings and common patterns.
    Captures text before the first heading as 'Frontmatter' if present.
    """
    import re
    # Match markdown '# ' or common structural names, or numbered combinations
    pattern = re.compile(
        r'^(#\s+[^\n]+|\s*(?:chapter|part)\s+[A-Za-z0-IVXLCDM]+[^\n]*|\d+\.\s+[A-Z][^\n]{3,60}|\s*(?:introduction|preface|prologue|epilogue|conclusion|foreword|acknowledgements?)\s*)$',
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"title": "Chapter 1", "text": text, "audio_path": None}]

    chapters = []
    
    # Check for text before the first match
    if matches[0].start() > 0:
        frontmatter = text[:matches[0].start()].strip()
        if frontmatter:
            chapters.append({"title": "Frontmatter", "text": frontmatter, "audio_path": None})

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        # Clean title: Remove leading '# ' if present
        title = match.group(0).strip()
        if title.startswith('# '):
            title = title[2:].strip()
            
        body = text[start:end].strip()
        # Optionally remove the matched title from the body so it doesn't repeat immediately, 
        # but since heading may have contextual newline we just strip if we want.
        # usually simpler to leave it, or strip if exactly matches
        if body.lower().startswith(match.group(0).lower().strip()):
            body = body[len(match.group(0).strip()):].strip()
            
        chapters.append({"title": title, "text": body, "audio_path": None})
    return chapters
