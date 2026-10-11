"""Tests for on-demand text tools endpoints (scripture expander and clean text)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, projects  # noqa: E402
from app.main import ExpandScriptureRequest, CleanTextRequest  # noqa: E402


def test_expand_scripture_chapter_and_all(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Test Book", "Author")
    project_id = proj.id

    chapters = [
        {
            "title": "Chapter 1",
            "text": "Read Ps 1:4 and Jn 3:16.",
            "blocks": [
                {"id": "b1", "type": "body", "text": "Read Ps 1:4 and Jn 3:16."}
            ],
            "audio_path": None,
        },
        {
            "title": "Chapter 2",
            "text": "Check Rom 8:28.",
            "blocks": [
                {"id": "b2", "type": "body", "text": "Check Rom 8:28."}
            ],
            "audio_path": None,
        },
    ]
    projects.save_chapters(project_id, chapters)

    # 1. Expand single chapter
    res_single = asyncio.run(main.api_expand_scripture(project_id, ExpandScriptureRequest(chapter_index=0)))
    assert "Psalms 1, verse 4" in res_single["chapters"][0]["blocks"][0]["text"]
    assert "John 3, verse 16" in res_single["chapters"][0]["blocks"][0]["text"]
    # Chapter 2 should be untouched
    assert "Rom 8:28" in res_single["chapters"][1]["blocks"][0]["text"]

    # 2. Expand all chapters
    res_all = asyncio.run(main.api_expand_scripture(project_id, ExpandScriptureRequest(chapter_index=None)))
    assert "Romans 8, verse 28" in res_all["chapters"][1]["blocks"][0]["text"]


def test_clean_text_regex_on_demand(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    chapters = [
        {
            "title": "Chapter 1",
            "text": "This has soft-\nhyphen breaks and My Title header.",
            "blocks": [
                {"id": "b1", "type": "body", "text": "This has soft-\nhyphen breaks and My Title header."}
            ],
            "audio_path": None,
        }
    ]
    projects.save_chapters(project_id, chapters)

    res = asyncio.run(main.api_clean_text(project_id, CleanTextRequest(chapter_index=0, provider="regex", cleaning_profile="safe")))
    b = res["chapters"][0]["blocks"][0]
    assert "pending_proposal" in b
    proposed = b["pending_proposal"]["proposed_text"]
    assert "soft-hyphen" not in proposed or "softhyphen" in proposed or "soft- hyphen" not in proposed
    assert len(res["chapters"]) == 1

    # Accept the proposal
    res_accept = asyncio.run(main.api_resolve_proposal(project_id, main.ResolveProposalRequest(action="accept", chapter_index=0)))
    b_accepted = res_accept["chapters"][0]["blocks"][0]
    assert "pending_proposal" not in b_accepted
    assert b_accepted["text"] == proposed


def test_clean_text_revert_proposal(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    chapters = [
        {
            "title": "Chapter 1",
            "text": "Original text here with soft-\nhyphen.",
            "blocks": [
                {"id": "b1", "type": "body", "text": "Original text here with soft-\nhyphen."}
            ],
            "audio_path": None,
        }
    ]
    projects.save_chapters(project_id, chapters)

    res = asyncio.run(main.api_clean_text(project_id, CleanTextRequest(chapter_index=0, provider="regex", cleaning_profile="safe")))
    assert "pending_proposal" in res["chapters"][0]["blocks"][0]

    # Revert proposal
    res_revert = asyncio.run(main.api_resolve_proposal(project_id, main.ResolveProposalRequest(action="revert", chapter_index=0)))
    b_reverted = res_revert["chapters"][0]["blocks"][0]
    assert "pending_proposal" not in b_reverted
    assert b_reverted["text"] == "Original text here with soft-\nhyphen."


def test_tts_debug_text_with_enabled_modules(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    # Test without bible module
    req_plain = main.PreviewRequest(
        text="Read Ps 1:4.",
        engine="edge-tts",
        enabled_modules=["prose_reflow"],
    )
    res_plain = asyncio.run(main.tts_debug_text(project_id, req_plain))
    assert res_plain["enabled_modules"] == ["prose_reflow"]

    # Test with bible module in request
    req_bible = main.PreviewRequest(
        text="Read Ps 1:4.",
        engine="edge-tts",
        enabled_modules=["bible", "prose_reflow"],
    )
    res_bible = asyncio.run(main.tts_debug_text(project_id, req_bible))
    assert "bible" in res_bible["enabled_modules"]
    assert "Psalms 1, verse 4" in res_bible["prepared_text"]


def test_clean_text_with_modernize_combined(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    chapters = [
        {
            "title": "Chapter 1",
            "text": "Thou hast spoken truly.",
            "blocks": [
                {"id": "b1", "type": "body", "text": "Thou hast spoken truly."}
            ],
            "audio_path": None,
        }
    ]
    projects.save_chapters(project_id, chapters)

    # Mock llm_modernize_text to return modernized text
    def mock_modernize(text, **kwargs):
        return ("You have spoken truly.", {})

    monkeypatch.setattr(main, "llm_modernize_text", mock_modernize)

    req = CleanTextRequest(
        chapter_index=0,
        provider="regex",
        cleaning_profile="safe",
        modernize=True,
        modernization_profile="light",
    )
    res = asyncio.run(main.api_clean_text(project_id, req))
    b = res["chapters"][0]["blocks"][0]
    assert "pending_proposal" in b
    assert b["pending_proposal"]["original_text"] == "Thou hast spoken truly."
    assert b["pending_proposal"]["proposed_text"] == "You have spoken truly."


def test_reflow_prose_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    chapters = [
        {
            "title": "Chapter 1",
            "text": "This was a strong fortifica-\ntion of the ancient\ncity wall.",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "format": "prose",
                    "text": "This was a strong fortifica-\ntion of the ancient\ncity wall.",
                }
            ],
            "audio_path": None,
        }
    ]
    projects.save_chapters(project_id, chapters)

    res = asyncio.run(main.api_reflow_prose(project_id, main.ReflowProseRequest(chapter_index=0)))
    b = res["chapters"][0]["blocks"][0]
    assert b["text"] == "This was a strong fortification of the ancient city wall."
    assert res["chapters"][0]["text"] == "This was a strong fortification of the ancient city wall."
    assert res["reflowed_blocks_count"] == 1


def test_reflow_prose_preserves_verse(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("My Title", "Author")
    project_id = proj.id

    verse_text = "The Lord is my shepherd;\nI shall not want.\nHe maketh me to lie down."
    prose_text = "Here is some prose\nthat wrapped around\nthe margins."
    chapters = [
        {
            "title": "Chapter 1",
            "text": f"{verse_text}\n\n{prose_text}",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "format": "verse",
                    "text": verse_text,
                },
                {
                    "id": "b2",
                    "type": "body",
                    "format": "prose",
                    "text": prose_text,
                },
            ],
            "audio_path": None,
        }
    ]
    projects.save_chapters(project_id, chapters)

    res = asyncio.run(main.api_reflow_prose(project_id, main.ReflowProseRequest(chapter_index=0)))
    b_verse = res["chapters"][0]["blocks"][0]
    b_prose = res["chapters"][0]["blocks"][1]
    # Verse remains strictly lineated
    assert b_verse["text"] == verse_text
    # Prose is cleanly reflowed
    assert b_prose["text"] == "Here is some prose that wrapped around the margins."



