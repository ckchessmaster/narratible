import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel


VOICE_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac"}

def _app_data_dir() -> Path:
    configured = os.environ.get("NARRATIBLE_DATA_DIR")
    if configured:
        return Path(configured)
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('APPDATA', Path.home())) / "narratible"
    return Path.home() / ".narratible"


VOICE_LIBRARY_DIR = _app_data_dir() / "voice_library"
LEGACY_VOICE_LIBRARY_DIR = Path(__file__).parent.parent / "voice_library"

VOICE_LIBRARY_FILE = VOICE_LIBRARY_DIR / "voices.json"


class LibraryVoice(BaseModel):
    id: str
    name: str
    engine: str = "f5-tts"
    reference_text: str = ""
    notes: str = ""
    speed: float = 1.0
    temperature: float = 0.7
    sample_filename: str
    created_at: str
    updated_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_library_dir() -> None:
    VOICE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_library()


def _migrate_legacy_library() -> None:
    if VOICE_LIBRARY_FILE.exists() or not LEGACY_VOICE_LIBRARY_DIR.exists():
        return
    legacy_file = LEGACY_VOICE_LIBRARY_DIR / "voices.json"
    if not legacy_file.exists() or LEGACY_VOICE_LIBRARY_DIR.resolve() == VOICE_LIBRARY_DIR.resolve():
        return
    for item in LEGACY_VOICE_LIBRARY_DIR.iterdir():
        destination = VOICE_LIBRARY_DIR / item.name
        if destination.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, destination)
        elif item.is_file():
            shutil.copy2(item, destination)


def _voice_dir(voice_id: str) -> Path:
    return VOICE_LIBRARY_DIR / voice_id


def _library_data() -> list[dict]:
    _ensure_library_dir()
    if not VOICE_LIBRARY_FILE.exists():
        return []
    with open(VOICE_LIBRARY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_library(voices: list[LibraryVoice]) -> None:
    _ensure_library_dir()
    with open(VOICE_LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump([voice.model_dump() for voice in voices], f, indent=4, ensure_ascii=False)


def _safe_filename(filename: str, fallback: str) -> str:
    path = Path(filename or fallback)
    suffix = path.suffix.lower() or ".wav"
    stem = path.stem or fallback
    safe_stem = "".join(c if c.isalnum() or c in "_-" else "_" for c in stem).strip("_-")
    return f"{safe_stem or fallback}{suffix}"


def list_library_voices() -> list[LibraryVoice]:
    voices = []
    for raw in _library_data():
        try:
            voices.append(LibraryVoice(**raw))
        except Exception:
            continue
    return sorted(voices, key=lambda voice: voice.name.casefold())


def get_library_voice(voice_id: str) -> LibraryVoice:
    for voice in list_library_voices():
        if voice.id == voice_id:
            return voice
    raise FileNotFoundError(f"Voice '{voice_id}' not found.")


def create_library_voice(
    name: str,
    reference_text: str,
    notes: str,
    speed: float,
    temperature: float,
    filename: str,
    fileobj: BinaryIO,
) -> LibraryVoice:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Voice name is required.")

    sample_filename = _safe_filename(filename, "reference.wav")
    if Path(sample_filename).suffix.lower() not in VOICE_AUDIO_SUFFIXES:
        raise ValueError("Reference audio must be WAV, MP3, or FLAC.")

    voice_id = str(uuid.uuid4())
    voice_dir = _voice_dir(voice_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    sample_path = voice_dir / sample_filename
    with open(sample_path, "wb") as f:
        shutil.copyfileobj(fileobj, f)

    now = _utc_now()
    voice = LibraryVoice(
        id=voice_id,
        name=clean_name,
        reference_text=(reference_text or "").strip(),
        notes=(notes or "").strip(),
        speed=max(0.5, min(float(speed), 2.0)),
        temperature=max(0.0, min(float(temperature), 1.5)),
        sample_filename=sample_filename,
        created_at=now,
        updated_at=now,
    )
    _save_library([*list_library_voices(), voice])
    return voice


def update_library_voice(voice_id: str, updates: dict) -> LibraryVoice:
    voices = list_library_voices()
    for index, voice in enumerate(voices):
        if voice.id != voice_id:
            continue
        normalized = {key: value for key, value in updates.items() if value is not None}
        if "name" in normalized:
            normalized["name"] = normalized["name"].strip()
            if not normalized["name"]:
                raise ValueError("Voice name is required.")
        if "reference_text" in normalized:
            normalized["reference_text"] = normalized["reference_text"].strip()
        if "notes" in normalized:
            normalized["notes"] = normalized["notes"].strip()
        if "speed" in normalized:
            normalized["speed"] = max(0.5, min(float(normalized["speed"]), 2.0))
        if "temperature" in normalized:
            normalized["temperature"] = max(0.0, min(float(normalized["temperature"]), 1.5))
        normalized["updated_at"] = _utc_now()
        updated = voice.model_copy(update=normalized)
        voices[index] = updated
        _save_library(voices)
        return updated
    raise FileNotFoundError(f"Voice '{voice_id}' not found.")


def delete_library_voice(voice_id: str) -> None:
    voices = list_library_voices()
    remaining = [voice for voice in voices if voice.id != voice_id]
    if len(remaining) == len(voices):
        raise FileNotFoundError(f"Voice '{voice_id}' not found.")
    _save_library(remaining)
    shutil.rmtree(_voice_dir(voice_id), ignore_errors=True)


def get_library_voice_sample_path(voice_id: str) -> Path:
    voice = get_library_voice(voice_id)
    sample_path = _voice_dir(voice.id) / voice.sample_filename
    if not sample_path.exists() or not sample_path.is_file():
        raise FileNotFoundError(f"Reference audio for voice '{voice.name}' was not found.")
    return sample_path


def get_library_voice_preview_path(voice_id: str) -> Path:
    get_library_voice(voice_id)
    voice_dir = _voice_dir(voice_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    return voice_dir / "preview.mp3"