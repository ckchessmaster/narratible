import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.epub import build_epub  # noqa: E402
from app.projects import normalize_chapters  # noqa: E402


def test_normalize_chapters_moves_legacy_notes_section_into_structured_notes():
    normalized = normalize_chapters([
        {
            "title": "Chapter",
            "text": "Main text.\n\n--- NOTES ---\n\n1 Legacy note body.",
        }
    ])

    assert normalized[0]["text"] == "Main text."
    assert normalized[0]["notes"][0]["text"] == "1 Legacy note body."


def test_normalize_chapters_keeps_split_continuation_from_reusing_previous_id():
    previous = [
        {"id": "chapter-1", "title": "Chapter", "text": "First half.", "notes": [{"text": "Original note"}]},
    ]
    normalized = normalize_chapters(
        [
            {"id": "chapter-1", "title": "Chapter", "text": "First half.", "notes": [{"text": "Original note"}]},
            {"title": "Chapter (cont.)", "text": "Second half.", "notes": [{"text": "Moved note"}]},
        ],
        previous,
    )

    assert normalized[0]["id"] == "chapter-1"
    assert normalized[1]["id"] != "chapter-1"
    assert normalized[1]["notes"][0]["text"] == "Moved note"


def test_epub_excludes_notes_by_default_and_includes_when_requested(tmp_path):
    chapters = [
        {
            "title": "Chapter",
            "text": "Main text.",
            "notes": [{"type": "margin", "text": "cf. John vi. 38", "page": 34}],
        }
    ]
    without_notes = tmp_path / "without.epub"
    with_notes = tmp_path / "with.epub"

    build_epub(without_notes, "Title", "Author", "en", "", "", "", "", "", chapters)
    build_epub(with_notes, "Title", "Author", "en", "", "", "", "", "", chapters, include_notes=True)

    with zipfile.ZipFile(without_notes) as epub:
        chapter_html = epub.read("OEBPS/chapter001.xhtml").decode("utf-8")
        assert "Main text." in chapter_html
        assert "John vi" not in chapter_html

    with zipfile.ZipFile(with_notes) as epub:
        chapter_html = epub.read("OEBPS/chapter001.xhtml").decode("utf-8")
        assert "Main text." in chapter_html
        assert "John vi. 38" in chapter_html
