"""Tests for project chapter hashes and stale-aware TTS persistence."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app import projects  # noqa: E402


def _project_with_current_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project = projects.create_project("Book", "Author")
    projects.save_chapters(project.id, [{"title": "Chapter 1", "text": "Original text", "audio_path": None}])
    chapter = projects.load_chapters(project.id)[0]
    rel_audio = f"audio/{chapter['id']}.mp3"
    audio_path = projects.project_file(project.id, rel_audio)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"existing audio")
    settings_hash = projects.tts_settings_hash(
        engine=project.tts_engine,
        voice=project.tts_voice,
        speed=project.tts_speed,
        read_headings=project.tts_read_headings,
        enabled_modules=project.enabled_modules,
    )
    chapter["tts"] = {
        "status": "complete",
        "audio_path": rel_audio,
        "text_hash": chapter["text_hash"],
        "settings_hash": settings_hash,
        "engine": project.tts_engine,
        "voice": project.tts_voice,
        "updated_at": "2026-06-17T00:00:00+00:00",
        "error": None,
    }
    chapter["audio_path"] = rel_audio
    projects.save_chapters(project.id, [chapter])
    return project.id


def test_chapter_text_change_marks_existing_audio_stale(tmp_path, monkeypatch):
    project_id = _project_with_current_audio(tmp_path, monkeypatch)
    chapter = projects.load_chapters(project_id)[0]
    old_audio_path = chapter["tts"]["audio_path"]
    old_tts_hash = chapter["tts"]["text_hash"]

    chapter["text"] = "Changed text"
    projects.save_chapters(project_id, [chapter])

    updated = projects.load_chapters(project_id)[0]
    assert updated["text_hash"] != old_tts_hash
    assert updated["tts"]["status"] == "stale"
    assert updated["tts"]["audio_path"] == old_audio_path
    assert updated["tts"]["text_hash"] == old_tts_hash


def test_tts_settings_change_marks_current_audio_stale(tmp_path, monkeypatch):
    project_id = _project_with_current_audio(tmp_path, monkeypatch)

    projects.update_project(project_id, {"tts_voice": "en-US-GuyNeural"})

    updated = projects.load_chapters(project_id)[0]
    assert updated["tts"]["status"] == "stale"
    assert updated["tts"]["audio_path"]


def test_chapter_tts_skips_when_audio_is_current(tmp_path, monkeypatch):
    project_id = _project_with_current_audio(tmp_path, monkeypatch)
    chapter = projects.load_chapters(project_id)[0]
    calls = []

    async def fake_synthesize_speech(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(main, "synthesize_speech", fake_synthesize_speech)

    result = asyncio.run(main.synthesize_project_chapter(
        project_id,
        chapter["id"],
        engine="edge-tts",
        voice="en-US-AriaNeural",
        speed=1.0,
        read_headings=True,
    ))

    assert result["status"] == "skipped"
    assert calls == []


def test_chapter_tts_regenerates_only_requested_stale_chapter(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project = projects.create_project("Book", "Author")
    projects.save_chapters(project.id, [
        {"title": "Chapter 1", "text": "One", "audio_path": None},
        {"title": "Chapter 2", "text": "Two", "audio_path": None},
    ])
    chapters = projects.load_chapters(project.id)
    calls = []

    async def fake_synthesize_speech(**kwargs):
        calls.append(kwargs["text"])
        kwargs["output_path"].write_bytes(b"new audio")

    monkeypatch.setattr(main, "synthesize_speech", fake_synthesize_speech)

    result = asyncio.run(main.synthesize_project_chapter(
        project.id,
        chapters[1]["id"],
        engine="edge-tts",
        voice="en-US-AriaNeural",
        speed=1.0,
        read_headings=True,
    ))

    updated = projects.load_chapters(project.id)
    assert result["status"] == "complete"
    assert len(calls) == 1
    assert calls[0].startswith("Chapter 2.")
    assert updated[0]["tts"]["status"] == "not_generated"
    assert updated[1]["tts"]["status"] == "complete"
    assert projects.project_file(project.id, updated[1]["tts"]["audio_path"]).exists()
