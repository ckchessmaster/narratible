"""Tests for modernization API helpers and persistence."""

import asyncio
import sys
from pathlib import Path

from fastapi import BackgroundTasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, projects  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.parsing_modules import MODERNIZATION_MODULE_ID  # noqa: E402


def test_modernization_eval_round_trips_outside_chapters_json(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project_id = "project-1"
    project_dir = tmp_path / project_id
    project_dir.mkdir()

    chapters = [{"title": "Chapter 1", "text": "Body", "audio_path": None}]
    evaluation = {
        "version": 1,
        "project_id": project_id,
        "profile": "standard_modern",
        "chapters": [{"chapter_index": 0, "title": "Chapter 1", "chunks": []}],
    }

    projects.save_chapters(project_id, chapters)
    projects.save_modernization_eval(project_id, evaluation)

    assert projects.load_chapters(project_id)[0]["text"] == "Body"
    assert projects.load_modernization_eval(project_id) == evaluation
    assert (project_dir / "chapters.json").exists()
    assert (project_dir / "modernization_eval.json").exists()


def test_parse_pdf_allows_modernization_module_with_regex_cleanup(monkeypatch):
    monkeypatch.setattr(main, "get_project", lambda project_id: object())
    monkeypatch.setattr(main, "load_config", lambda: AppConfig(gemini_api_key="key"))

    result = asyncio.run(
        main.parse_pdf(
            "project-1",
            BackgroundTasks(),
            cleaner="regex",
            modules=[MODERNIZATION_MODULE_ID],
        )
    )

    assert result == {"task_id": "parse-project-1"}


def _create_project_with_modernization_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    project = projects.create_project("Book", "Author")
    projects.save_chapters(project.id, [{"title": "Chapter 1", "text": "Original text", "audio_path": None}])
    evaluation = {
        "version": 1,
        "project_id": project.id,
        "profile": "standard_modern",
        "provider": "openai",
        "chapters": [
            {
                "chapter_index": 0,
                "title": "Chapter 1",
                "provider": "openai",
                "chunks": [
                    {
                        "chunk_id": 0,
                        "status": "candidate",
                        "source_text": "Original text",
                        "accepted_text": "Original text",
                        "candidate_text": "Modern text",
                        "integrity_issues": [],
                        "metrics": {"word_count_ratio": 1.0},
                        "risk_level": "low",
                        "risk_reasons": [],
                        "recommended_action": "accept",
                        "variants": [
                            {
                                "variant_id": "0-1",
                                "accepted_text": "Modern text",
                                "candidate_text": "Modern text",
                                "risk_level": "low",
                                "integrity_issues": [],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    projects.save_modernization_eval(project.id, evaluation)
    return project.id


def test_apply_modernization_variant_marks_eval_without_overwriting_chapter(tmp_path, monkeypatch):
    project_id = _create_project_with_modernization_eval(tmp_path, monkeypatch)

    result = asyncio.run(main.apply_modernization_variant(
        project_id,
        0,
        0,
        main.ApplyVariantRequest(variant_id="0-1"),
    ))

    updated_chunk = projects.load_modernization_eval(project_id)["chapters"][0]["chunks"][0]
    assert result["replacement_text"] == "Modern text"
    assert updated_chunk["applied_variant_id"] == "0-1"
    assert updated_chunk["variants"][0]["is_applied"] is True
    assert projects.load_chapters(project_id)[0]["text"] == "Original text"


def test_select_commit_and_undo_modernization_session_uses_source_snapshot(tmp_path, monkeypatch):
    project_id = _create_project_with_modernization_eval(tmp_path, monkeypatch)
    evaluation = projects.load_modernization_eval(project_id)
    evaluation["chapters"][0]["chunks"] = [
        {
            "chunk_id": 0,
            "status": "unselected",
            "source_text": "Old first passage.",
            "accepted_text": "Old first passage.",
            "candidate_text": "Modern first passage.",
            "integrity_issues": [],
            "metrics": {"word_count_ratio": 1.0},
            "risk_level": "low",
            "risk_reasons": [],
            "recommended_action": "accept",
            "variants": [{"variant_id": "0-1", "accepted_text": "Modern first passage.", "candidate_text": "Modern first passage."}],
        },
        {
            "chunk_id": 1,
            "status": "unselected",
            "source_text": "Old second passage.",
            "accepted_text": "Old second passage.",
            "candidate_text": "Modern second passage.",
            "integrity_issues": [],
            "metrics": {"word_count_ratio": 1.0},
            "risk_level": "low",
            "risk_reasons": [],
            "recommended_action": "accept",
            "variants": [{"variant_id": "1-1", "accepted_text": "Modern second passage.", "candidate_text": "Modern second passage."}],
        },
    ]
    projects.save_modernization_eval(project_id, evaluation)
    projects.save_chapters(project_id, [{"title": "Chapter 1", "text": "Manual edits before commit", "audio_path": None}])

    asyncio.run(main.select_modernization_variant(project_id, 0, 0, main.SelectVariantRequest(variant_id="0-1")))
    selected_eval = projects.load_modernization_eval(project_id)
    assert selected_eval["chapters"][0]["chunks"][0]["selected_variant_id"] == "0-1"
    assert projects.load_chapters(project_id)[0]["text"] == "Manual edits before commit"

    commit_result = asyncio.run(main.commit_modernization_session(project_id, 0))

    assert commit_result["chapter"]["text"] == "Modern first passage.\n\nOld second passage."
    last_commit = projects.load_modernization_eval(project_id)["chapters"][0]["last_commit"]
    assert last_commit["before_text"] == "Manual edits before commit"
    assert last_commit["selected_variant_ids"] == ["0-1"]

    undo_result = asyncio.run(main.undo_last_modernization_commit(project_id, 0))

    assert undo_result["chapter"]["text"] == "Manual edits before commit"
    assert projects.load_modernization_eval(project_id)["chapters"][0]["status"] == "commit_undone"


def test_skip_and_clear_modernization_selection_do_not_change_chapter_text(tmp_path, monkeypatch):
    project_id = _create_project_with_modernization_eval(tmp_path, monkeypatch)

    asyncio.run(main.select_modernization_variant(project_id, 0, 0, main.SelectVariantRequest(variant_id="0-1")))
    asyncio.run(main.skip_modernization_chunk(project_id, 0, 0))
    skipped_chunk = projects.load_modernization_eval(project_id)["chapters"][0]["chunks"][0]

    assert skipped_chunk["status"] == "skipped"
    assert "selected_variant_id" not in skipped_chunk
    assert projects.load_chapters(project_id)[0]["text"] == "Original text"

    asyncio.run(main.select_modernization_variant(project_id, 0, 0, main.SelectVariantRequest(variant_id="0-1")))
    asyncio.run(main.clear_modernization_selection(project_id, 0, 0))
    cleared_chunk = projects.load_modernization_eval(project_id)["chapters"][0]["chunks"][0]

    assert cleared_chunk["status"] == "unselected"
    assert "selected_variant_id" not in cleared_chunk
    assert projects.load_chapters(project_id)[0]["text"] == "Original text"


def test_discarded_modernization_session_stays_inactive_after_read(tmp_path, monkeypatch):
    project_id = _create_project_with_modernization_eval(tmp_path, monkeypatch)

    discard_result = asyncio.run(main.discard_modernization_session(project_id, 0))
    read_result = asyncio.run(main.get_project_modernization_eval(project_id))
    chapter_eval = read_result["chapters"][0]

    assert discard_result["chapter"]["status"] == "superseded"
    assert chapter_eval["active_session_id"] is None
    assert chapter_eval["status"] == "superseded"
    assert chapter_eval["chunks"] == []
    assert projects.load_chapters(project_id)[0]["text"] == "Original text"


def test_redo_modernization_appends_variant_with_redo_context(tmp_path, monkeypatch):
    project_id = _create_project_with_modernization_eval(tmp_path, monkeypatch)
    captured = {}

    def fake_modernize_text(text, **kwargs):
        captured["text"] = text
        captured["redo_context"] = kwargs.get("redo_context")
        return "Fresh modern text", {
            "profile": "standard_modern",
            "chunks": [
                {
                    "status": "candidate",
                    "candidate_text": "Fresh modern text",
                    "variants": [{"candidate_text": "Fresh modern text"}],
                    "integrity_issues": [],
                    "metrics": {"word_count_ratio": 1.0},
                    "risk_level": "low",
                    "risk_reasons": [],
                    "recommended_action": "accept",
                    "similarity_to_previous": 0.25,
                }
            ],
        }

    monkeypatch.setattr(main, "llm_modernize_text", fake_modernize_text)

    result = asyncio.run(main.redo_modernization_chunk(
        project_id,
        0,
        0,
        main.RedoModernizationRequest(redo_mode="more_faithful", instruction="Keep Saviour unchanged"),
    ))

    assert captured["text"] == "Original text"
    assert captured["redo_context"]["previous_candidates"] == ["Modern text"]
    assert captured["redo_context"]["redo_mode"] == "more_faithful"
    assert captured["redo_context"]["instruction"] == "Keep Saviour unchanged"
    assert result["variant"]["variant_id"] == "0-2"
    assert result["variant"]["redo_mode"] == "more_faithful"
    assert result["variant"]["similarity_to_previous"] == 0.25
    assert len(projects.load_modernization_eval(project_id)["chapters"][0]["chunks"][0]["variants"]) == 2