"""Tests for project-level cleaning evaluation persistence."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import projects  # noqa: E402
from app import main  # noqa: E402


def test_cleaning_eval_round_trips_outside_chapters_json(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project_id = "project-1"
    project_dir = tmp_path / project_id
    project_dir.mkdir()

    chapters = [{"title": "Chapter 1", "text": "Body", "audio_path": None}]
    evaluation = {
        "version": 1,
        "project_id": project_id,
        "profile": "safe",
        "chapters": [
            {
                "chapter_index": 0,
                "title": "Chapter 1",
                "fallback_count": 1,
                "chunks": [{"chunk_id": 0, "status": "fallback"}],
            }
        ],
    }

    projects.save_chapters(project_id, chapters)
    projects.save_cleaning_eval(project_id, evaluation)

    loaded_chapters = projects.load_chapters(project_id)
    assert loaded_chapters[0]["title"] == chapters[0]["title"]
    assert loaded_chapters[0]["text"] == chapters[0]["text"]
    assert loaded_chapters[0]["audio_path"] is None
    assert loaded_chapters[0]["id"]
    assert loaded_chapters[0]["text_hash"]
    assert projects.load_cleaning_eval(project_id) == evaluation
    assert (project_dir / "chapters.json").exists()
    assert (project_dir / "cleaning_eval.json").exists()


def _create_project_with_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project = projects.create_project("Book", "Author")
    projects.save_chapters(project.id, [{"title": "Chapter 1", "text": "Original text", "audio_path": None}])
    evaluation = {
        "version": 1,
        "project_id": project.id,
        "profile": "safe",
        "provider": "openai",
        "cleaner": "llm",
        "chapters": [
            {
                "chapter_index": 0,
                "title": "Chapter 1",
                "provider": "openai",
                "accepted_count": 0,
                "fallback_count": 1,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "status": "fallback",
                        "source_text": "Original text",
                        "accepted_text": "Original text",
                        "candidate_text": "Bad text",
                        "integrity_issues": ["missing source anchor phrases"],
                        "metrics": {"word_count_ratio": 0.5, "anchor_required": 1, "anchor_matches": 0},
                        "risk_level": "high",
                        "risk_reasons": ["missing anchors"],
                        "recommended_action": "review",
                        "variants": [
                            {
                                "variant_id": "0-1",
                                "accepted_text": "Better text",
                                "candidate_text": "Better text",
                                "risk_level": "low",
                                "integrity_issues": [],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    projects.save_cleaning_eval(project.id, evaluation)
    return project.id


def test_apply_cleaning_variant_marks_eval_without_overwriting_chapter(tmp_path, monkeypatch):
    project_id = _create_project_with_eval(tmp_path, monkeypatch)

    result = asyncio.run(main.apply_cleaning_variant(
        project_id,
        0,
        0,
        main.ApplyVariantRequest(variant_id="0-1"),
    ))

    updated_eval = projects.load_cleaning_eval(project_id)
    updated_chunk = updated_eval["chapters"][0]["chunks"][0]
    assert result["replacement_text"] == "Better text"
    assert updated_chunk["applied_variant_id"] == "0-1"
    assert updated_chunk["variants"][0]["is_applied"] is True
    assert projects.load_chapters(project_id)[0]["text"] == "Original text"


def test_batch_redo_cleaning_stores_variants(tmp_path, monkeypatch):
    project_id = _create_project_with_eval(tmp_path, monkeypatch)

    def fake_llm_clean_text(*args, **kwargs):
        return "Retried text", {
            "profile": kwargs.get("cleaning_profile", "balanced"),
            "chunks": [
                {
                    "status": "accepted",
                    "candidate_text": "Retried text",
                    "accepted_text": "Retried text",
                    "notes_text": "",
                    "integrity_issues": [],
                    "metrics": {"word_count_ratio": 1.0, "anchor_required": 0, "anchor_matches": 0},
                    "risk_level": "low",
                    "risk_reasons": [],
                    "recommended_action": "accept",
                }
            ],
        }

    monkeypatch.setattr(main, "llm_clean_text", fake_llm_clean_text)

    result = asyncio.run(main.batch_redo_cleaning(
        project_id,
        main.BatchRedoCleaningRequest(
            chunks=[main.BatchRedoChunkRequest(chapter_index=0, chunk_id=0)],
            cleaning_profile="balanced",
        ),
    ))

    updated_chunk = projects.load_cleaning_eval(project_id)["chapters"][0]["chunks"][0]
    assert result["results"][0]["ok"] is True
    assert updated_chunk["variants"][-1]["accepted_text"] == "Retried text"
    assert updated_chunk["variants"][-1]["risk_level"] == "low"


def test_cleaning_report_summarizes_eval(tmp_path, monkeypatch):
    project_id = _create_project_with_eval(tmp_path, monkeypatch)

    report = asyncio.run(main.get_cleaning_report(project_id))

    assert report["project"]["title"] == "Book"
    assert report["total_chunks"] == 1
    assert report["total_fallbacks"] == 1
    assert report["risk_counts"]["high"] == 1