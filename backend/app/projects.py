import uuid
import json
import shutil
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

PROJECTS_DIR = Path(__file__).parent.parent / "projects"


class ProjectMetadata(BaseModel):
    id: str
    title: str
    author: str = ""
    cover_image: Optional[str] = None  # relative path inside project dir
    tts_engine: str = "edge-tts"
    tts_voice: str = "en-US-AriaNeural"
    tts_speed: float = 1.0


def _project_path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _metadata_path(project_id: str) -> Path:
    return _project_path(project_id) / "metadata.json"


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
    (project_dir / "voices").mkdir(exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    meta = ProjectMetadata(id=project_id, title=title, author=author)
    _save_metadata(meta)
    logger.info(f"Created project {project_id}: {title}")
    return meta


def update_project(project_id: str, updates: dict) -> ProjectMetadata:
    meta = get_project(project_id)
    updated = meta.model_copy(update=updates)
    _save_metadata(updated)
    return updated


def delete_project(project_id: str):
    project_dir = _project_path(project_id)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project '{project_id}' not found.")
    shutil.rmtree(project_dir)
    logger.info(f"Deleted project {project_id}")


def _save_metadata(meta: ProjectMetadata):
    with open(_metadata_path(meta.id), "w", encoding="utf-8") as f:
        json.dump(meta.model_dump(), f, indent=4)


# ── Chapter helpers ────────────────────────────────────────────────────────────

def _chapters_path(project_id: str) -> Path:
    return _project_path(project_id) / "chapters.json"


def load_chapters(project_id: str) -> list[dict]:
    path = _chapters_path(project_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chapters(project_id: str, chapters: list[dict]):
    with open(_chapters_path(project_id), "w", encoding="utf-8") as f:
        json.dump(chapters, f, indent=4, ensure_ascii=False)


def auto_split_chapters(text: str) -> list[dict]:
    """
    Heuristically split cleaned text into chapters using common heading patterns.
    Falls back to a single chapter if no headings are found.
    """
    import re
    pattern = re.compile(
        r'^(chapter\s+\w+[^\n]*|part\s+\w+[^\n]*|\d+\.\s+[A-Z][^\n]+)',
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"title": "Chapter 1", "text": text, "audio_path": None}]

    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = match.group(0).strip()
        body = text[start:end].strip()
        chapters.append({"title": title, "text": body, "audio_path": None})
    return chapters
