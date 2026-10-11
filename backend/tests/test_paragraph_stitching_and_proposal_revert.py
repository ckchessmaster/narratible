import asyncio
import sys
from pathlib import Path
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, projects
from app.parsing_modules.prose_reflow import stitch_split_paragraph_blocks
from app.main import StitchParagraphsRequest


def test_revert_proposal_does_not_resurrect_on_save(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Test Revert", "Author")
    project_id = proj.id

    # 1. Save chapter with a pending proposal
    chapters = [
        {
            "id": "ch1",
            "title": "Chapter 1",
            "text": "Proposed text",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "format": "prose",
                    "source_page": 1,
                    "text": "Proposed text",
                    "pending_proposal": {
                        "original_text": "Original text",
                        "proposed_text": "Proposed text",
                    },
                }
            ],
        }
    ]
    projects.save_chapters(project_id, chapters)

    loaded = projects.load_chapters(project_id)
    assert "pending_proposal" in loaded[0]["blocks"][0]

    # 2. Client reverts proposal and saves
    reverted_chapters = [
        {
            "id": "ch1",
            "title": "Chapter 1",
            "text": "Original text",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "format": "prose",
                    "source_page": 1,
                    "text": "Original text",
                    # pending_proposal explicitly omitted/deleted
                }
            ],
        }
    ]
    projects.save_chapters(project_id, reverted_chapters)

    # 3. Verify it is NOT resurrected on reload
    reloaded = projects.load_chapters(project_id)
    assert "pending_proposal" not in reloaded[0]["blocks"][0]
    assert reloaded[0]["blocks"][0]["text"] == "Original text"


def test_stitch_split_paragraph_blocks_syntactic_continuity():
    blocks = [
        {
            "id": "b1",
            "type": "body",
            "format": "prose",
            "source_page": 11,
            "text": "With the exception of the complete vocabulary of the works edited in the two. volumes of the Vil",
        },
        {
            "id": "b2",
            "type": "body",
            "format": "prose",
            "source_page": 12,
            "text": "Vienna edition, preserved in Munich for the sake of the great Thesaurus.",
        },
    ]

    stitched, count = stitch_split_paragraph_blocks(blocks)
    assert count == 1
    assert len(stitched) == 1
    assert stitched[0]["id"] == "b1"
    assert stitched[0]["source_page"] == 11
    assert "Vil Vienna edition" in stitched[0]["text"]


def test_stitch_split_paragraph_blocks_trailing_hyphen():
    blocks = [
        {
            "id": "b1",
            "type": "body",
            "format": "prose",
            "source_page": 1,
            "text": "This was a magni-",
        },
        {
            "id": "b2",
            "type": "body",
            "format": "prose",
            "source_page": 2,
            "text": "ficent demonstration.",
        },
    ]

    stitched, count = stitch_split_paragraph_blocks(blocks)
    assert count == 1
    assert len(stitched) == 1
    assert stitched[0]["text"] == "This was a magnificent demonstration."


def test_stitch_split_paragraph_blocks_intervening_footnote():
    blocks = [
        {
            "id": "b1",
            "type": "body",
            "format": "prose",
            "source_page": 24,
            "text": "We must hold fast to the indissoluble union of Father, Son and Holy",
        },
        {
            "id": "fn1",
            "type": "footnote",
            "format": "prose",
            "source_page": 24,
            "text": "1 Prax. 6; cf. various creeds.",
        },
        {
            "id": "b2",
            "type": "body",
            "format": "prose",
            "source_page": 25,
            "text": "Spirit. Yet the Father and the Son are distinct.",
        },
    ]

    stitched, count = stitch_split_paragraph_blocks(blocks)
    assert count == 1
    assert len(stitched) == 2
    assert stitched[0]["id"] == "b1"
    assert stitched[0]["text"] == "We must hold fast to the indissoluble union of Father, Son and Holy Spirit. Yet the Father and the Son are distinct."
    assert stitched[1]["id"] == "fn1"
    assert stitched[1]["type"] == "footnote"


def test_stitch_split_paragraph_blocks_does_not_merge_verse_or_lists():
    blocks = [
        {
            "id": "b1",
            "type": "body",
            "format": "verse",
            "source_page": 1,
            "text": "Line one without period",
        },
        {
            "id": "b2",
            "type": "body",
            "format": "verse",
            "source_page": 1,
            "text": "Line two without period",
        },
        {
            "id": "b3",
            "type": "body",
            "format": "prose",
            "source_page": 2,
            "text": "Normal prose ending with period.",
        },
        {
            "id": "b4",
            "type": "body",
            "format": "prose",
            "source_page": 2,
            "text": "1. First item in list",
        },
    ]

    stitched, count = stitch_split_paragraph_blocks(blocks)
    assert count == 0
    assert len(stitched) == 4


def test_stitch_paragraphs_endpoint_clean_state_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Test Endpoint", "Author")
    project_id = proj.id

    chapters = [
        {
            "id": "ch1",
            "title": "Preface",
            "text": "Proposed text",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "text": "Proposed text",
                    "pending_proposal": {"original_text": "Orig", "proposed_text": "Prop"},
                }
            ],
        }
    ]
    projects.save_chapters(project_id, chapters)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.api_stitch_paragraphs(project_id, StitchParagraphsRequest(chapter_index=0)))
    assert exc.value.status_code == 400
    assert "pending AI proposals" in exc.value.detail


def test_stitch_paragraphs_endpoint_success(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Test Endpoint Success", "Author")
    project_id = proj.id

    chapters = [
        {
            "id": "ch1",
            "title": "Preface",
            "text": "Intro",
            "blocks": [
                {
                    "id": "b1",
                    "type": "body",
                    "format": "prose",
                    "source_page": 1,
                    "text": "This paragraph continues onto",
                },
                {
                    "id": "b2",
                    "type": "body",
                    "format": "prose",
                    "source_page": 2,
                    "text": "the next page smoothly.",
                },
            ],
        }
    ]
    projects.save_chapters(project_id, chapters)

    res = asyncio.run(main.api_stitch_paragraphs(project_id, StitchParagraphsRequest(chapter_index=0)))
    assert res["stitched_count"] == 1
    assert len(res["chapters"][0]["blocks"]) == 1
    assert res["chapters"][0]["blocks"][0]["text"] == "This paragraph continues onto the next page smoothly."
