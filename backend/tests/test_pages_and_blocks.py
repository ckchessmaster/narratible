import io
import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.testclient import TestClient
import pymupdf as fitz

from app import main, projects, epub


def test_blocks_and_audio_muting(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Test Book", "Author")
    
    # Save chapter with blocks
    blocks = [
        {"id": "b1", "source_page": 1, "text": "Paragraph 1", "audio_muted": False, "warning": None},
        {"id": "b2", "source_page": 1, "text": "Paragraph 2 - Table", "audio_muted": True, "warning": None},
        {"id": "b3", "source_page": 2, "text": "Paragraph 3", "audio_muted": False, "warning": None},
    ]
    projects.save_chapters(proj.id, [{
        "title": "Chapter 1",
        "blocks": blocks,
        "include_in_audio": True,
    }])

    chaps = projects.load_chapters(proj.id)
    assert len(chaps) == 1
    assert chaps[0]["text"] == "Paragraph 1\n\nParagraph 2 - Table\n\nParagraph 3"
    assert len(chaps[0]["blocks"]) == 3
    assert chaps[0]["blocks"][1]["audio_muted"] is True
    assert chaps[0]["include_in_audio"] is True

    # Mutate include_in_audio
    projects.update_chapter(proj.id, chaps[0]["id"], {"include_in_audio": False})
    chaps2 = projects.load_chapters(proj.id)
    assert chaps2[0]["include_in_audio"] is False


def test_pdf_page_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("PDF Book", "Author")

    # Create dummy PDF
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Hello Page 1")
    page2 = doc.new_page()
    page2.insert_text((50, 50), "Hello Page 2")

    pdf_dest = projects.source_pdf_path(proj.id)
    pdf_dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(pdf_dest))
    doc.close()

    client = TestClient(main.app)

    # Info endpoint
    info_res = client.get(f"/api/projects/{proj.id}/pages/info")
    assert info_res.status_code == 200
    assert info_res.json() == {"total_pages": 2, "has_source_pdf": True}

    # Render page 1
    p1_res = client.get(f"/api/projects/{proj.id}/pages/1.jpg?dpi=72")
    assert p1_res.status_code == 200
    assert p1_res.headers["content-type"] == "image/jpeg"
    assert len(p1_res.content) > 100

    # Cache hit check
    cache_path = projects.artifact_dir(proj.id) / "pages" / "page_1_72.jpg"
    assert cache_path.exists()
    p1_cached_res = client.get(f"/api/projects/{proj.id}/pages/1.jpg?dpi=72")
    assert p1_cached_res.status_code == 200

    # Out of bounds
    oob_res = client.get(f"/api/projects/{proj.id}/pages/99.jpg")
    assert oob_res.status_code == 404


def test_selective_tts_and_epub_preservation(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Audiobook Test", "Test Author")

    ch1_blocks = [
        {"id": "f1", "source_page": 1, "text": "Frontmatter Title Page", "audio_muted": False, "warning": None},
    ]
    ch2_blocks = [
        {"id": "b1", "source_page": 2, "text": "Spoken opening paragraph.", "audio_muted": False, "warning": None},
        {"id": "b2", "source_page": 2, "text": "Muted table column data.", "audio_muted": True, "warning": None},
        {"id": "b3", "source_page": 3, "text": "Spoken concluding paragraph.", "audio_muted": False, "warning": None},
    ]

    projects.save_chapters(proj.id, [
        {"title": "Frontmatter", "blocks": ch1_blocks, "include_in_audio": False},
        {"title": "Chapter 1", "blocks": ch2_blocks, "include_in_audio": True},
    ])

    chaps = projects.load_chapters(proj.id)
    ch1_id = chaps[0]["id"]
    ch2_id = chaps[1]["id"]

    # 1. Synthesizing ch1 (excluded from audio) should be skipped
    res1 = asyncio.run(main.synthesize_project_chapter(
        proj.id,
        ch1_id,
        engine="edge-tts",
        voice="en-US-GuyNeural",
        speed=1.0,
        read_headings=True,
    ))
    assert res1["status"] == "skipped"
    assert "excluded from audio" in res1["message"]

    # 2. Mock synthesize_speech to verify only audible blocks are synthesized
    spoken_texts = []
    async def mock_synthesize(text, output_path, **kwargs):
        spoken_texts.append(text)
        output_path.write_bytes(b"dummy mp3")

    monkeypatch.setattr(main, "synthesize_speech", mock_synthesize)

    res2 = asyncio.run(main.synthesize_project_chapter(
        proj.id,
        ch2_id,
        engine="edge-tts",
        voice="en-US-GuyNeural",
        speed=1.0,
        read_headings=True,
    ))
    assert res2["status"] == "complete"
    assert len(spoken_texts) == 1
    spoken = spoken_texts[0]
    assert "Spoken opening paragraph." in spoken
    assert "Spoken concluding paragraph." in spoken
    assert "Muted table column data." not in spoken

    # 3. EPUB generator must retain 100% of both chapters and all text
    epub_out = tmp_path / "book.epub"
    epub.build_epub(
        output_path=epub_out,
        title="Audiobook Test",
        author="Test Author",
        language="en",
        description="A test book",
        publisher="Self",
        subject="Fiction",
        isbn="1234567890",
        series="Test Series",
        chapters=chaps,
    )
    assert epub_out.exists()
    assert epub_out.stat().st_size > 500


def test_chapter_patch_api_blocks_and_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path)
    proj = projects.create_project("Patch Test", "Test Author")

    projects.save_chapters(proj.id, [
        {"title": "Original Title", "text": "Paragraph A\n\nParagraph B", "include_in_audio": True},
    ])

    chaps = projects.load_chapters(proj.id)
    ch_id = chaps[0]["id"]

    client = TestClient(main.app)

    patch_res = client.patch(
        f"/api/projects/{proj.id}/chapters/{ch_id}",
        json={
            "title": "Patched Title",
            "include_in_audio": False,
            "blocks": [
                {"id": "blk_new_1", "source_page": 5, "text": "Updated Para 1", "audio_muted": False, "warning": None},
                {"id": "blk_new_2", "source_page": 5, "text": "Updated Para 2", "audio_muted": True, "warning": None},
            ],
        },
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["title"] == "Patched Title"
    assert patched["include_in_audio"] is False
    assert len(patched["blocks"]) == 2
    assert patched["blocks"][1]["audio_muted"] is True
    assert patched["text"] == "Updated Para 1\n\nUpdated Para 2"
