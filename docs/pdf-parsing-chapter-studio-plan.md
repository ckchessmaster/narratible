# Aligned Architecture & Implementation Plan: PDF Parsing & Chapter Studio UI/UX Overhaul

## 1. Executive Summary & Problems Solved
Refactor the parsing, cleanup, and chapter management workflow in Narratible to eliminate UX friction, reduce cognitive load, and provide real-time visual ground truth when proofreading and organizing documents.

### Key Problems Solved:
1. **Nested Stepper & "Locking" Friction:** Eliminates the confusing sub-stepper ("1. Cleanup + Metadata", "2. Chapter Setup", "3. Final Review") and high-stress "Lock Step" buttons in favor of persistent state and continuous auto-saving.
2. **Abstract Chunk Review:** Replaces disconnected Git-style diff cards ("Passage 1", "Passage 2") with inline editorial highlights directly inside the text editor.
3. **Screen Real Estate Waste:** Removes the persistent 33% width Book Metadata column during chapter editing and moves it to an accessible header flyout modal / slideout.
4. **Disconnected Ground Truth:** Implements a dockable, on-demand visual PDF Inspector powered by lazy backend page rendering (<15ms native JPEG/PNG streaming with disk caching), letting users instantly verify complex layouts (multi-column text, callouts, footnotes) against the original scan.
5. **Granular Audio Control:** Supports one-click audio muting at both the chapter level (for Frontmatter, TOC, Index) and paragraph level (for tables, reading exercises, callout boxes) without stripping content from EPUB builds.

---

## 2. Aligned Decisions (from Alignment Interview)

| Area | Decision | Details |
|---|---|---|
| **Data Schema** | **Hybrid Block Model** | `chapters.json` stores `blocks: list[Block]` (`id`, `source_page`, `text`, `audio_muted`, `warning`). A synchronized `text` string is maintained for complete EPUB export and backward compatibility. Legacy projects automatically synthesize blocks on load. |
| **Page Attribution** | **Backend Offset & Substring Matching** | During PyMuPDF extraction, page numbers are recorded. Post-cleaning, paragraph blocks are resolved against source page text and linked to `cleaning_eval` chunk warnings. |
| **Center Workspace Editor** | **Fluid Document Flow** | Paragraphs look and feel like a continuous page with auto-growing textareas, seamless Enter/Backspace splitting/merging, subtle gutter controls (`🔊 / 🔇`, `P. 12`), hover split divider (`--- ✂ Split Chapter Here ---`), inline warning resolution pills, and a Raw Text fallback toggle. |
| **PDF Source Inspector** | **C-Engine JPEG Streaming + Disk Cache** | PyMuPDF renders pages via C-accelerated pixmap generation (~15ms) as high-quality JPEG/PNG with `<project_dir>/artifacts/pages/` disk caching (<2ms repeated views). Supports Peek (slideover) and Pinned (split screen) layouts. |
| **Inspector Sync** | **Auto-Open & Jump** | Clicking `[ Inspect Scan ↗ ]` or any paragraph's `P. 12` chip auto-opens the inspector, navigates to the page, and prefetches adjacent pages (`p - 1`, `p + 1`). |
| **Chapter Outline & Bulk Actions** | **Drag & Drop + Bulk Actions** | Native HTML5 drag handles (`⠿`), multi-selection (`Shift + Click` or checkboxes), bulk Delete, and bulk Merge (merges sequentially into first chapter, retains title with instant Toast Undo). Health badges display narration duration estimate (`~4 min audio`) and warning counts. |
| **Global Book Details** | **Right Slideover Sheet** | Opens from top workspace header (`[Project Title] · [Author] [ ✎ Book Details ]`), allowing live auto-saving edits to Title, Author, Cover Art, ISBN, Language, Subject, Series, and Description without sacrificing editor space. |
| **Modernization Module** | **Dedicated Studio Drawer** | Text Modernization (`modernize_text`) lives in an on-demand toolbar drawer/action rather than gating the primary review pipeline with modal locks. |
| **TTS & EPUB Pipeline** | **Selective Narration** | TTS synthesizer skips chapters marked `include_in_audio: false` and paragraph blocks marked `audio_muted: true`. EPUB export preserves 100% of the book text. |

---

## 3. High-Level Workflow Comparison

### Old Workflow (6 Screens / Nested Sub-Steps):
`1. Upload` ➔ `2. Review (Sub: Cleanup/Metadata)` ➔ `Review (Sub: Chapter Setup)` ➔ `Review (Sub: Final Review)` ➔ `3. Voice` ➔ `4. Export`

### New Streamlined Workflow (4 Steps):
`1. Upload & Options` ➔ `2. Chapter Studio` ➔ `3. Voice Library` ➔ `4. Export`

```
┌──────────────────┐     ┌───────────────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    1. UPLOAD     │ ──► │     2. CHAPTER STUDIO     │ ──► │     3. VOICE     │ ──► │    4. EXPORT     │
│  File & Presets  │     │   Unified Edit & Review   │     │ Narrator Choice  │     │  Audiobook/EPUB  │
└──────────────────┘     └─────────────┬─────────────┘     └──────────────────┘     └──────────────────┘
                                       │
                         ┌─────────────┴─────────────┐
                         │  [ ✎ Edit Book Details ]  │ (Header Slideout: Title,
                         │ Global Metadata Slideover │  Author, Cover, Tags)
                         └───────────────────────────┘
```

---

## 4. Technical Specifications & API Contracts

### 4.1. PDF Page Rendering Endpoint
```http
GET /api/projects/{project_id}/pages/{page_number}.jpg?dpi=150
```
- **Handler Logic:**
  1. Verify project exists; locate original PDF at `source/original.pdf`.
  2. Check disk cache at `artifacts/pages/page_{page_number}_{dpi}.jpg`. If hit, return immediately via `FileResponse`.
  3. If miss, open via `fitz.open(pdf_path)`.
  4. Select page: `page = doc[page_number - 1]`.
  5. Compute matrix: `scale = dpi / 72.0`, `pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)`.
  6. Save pixmap to cache file: `pix.save(str(cache_path), output="jpg")`.
  7. Return `FileResponse(cache_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})`.

### 4.2. Chapter Data Model (`chapters.json`)
```json
{
  "id": "ch_03",
  "order": 3,
  "title": "Introduction",
  "include_in_audio": true,
  "text": "Digitized by the Internet Archive...\n\nSecond paragraph text...",
  "text_hash": "...",
  "updated_at": "2026-10-04T15:00:00Z",
  "blocks": [
    {
      "id": "blk_101",
      "source_page": 12,
      "text": "Digitized by the Internet Archive...",
      "audio_muted": false,
      "warning": {
        "type": "anchor_fallback",
        "message": "Anchor phrases dropped near footnote",
        "raw_text": "Original messy OCR text...",
        "status": "pending"
      }
    },
    {
      "id": "blk_102",
      "source_page": 12,
      "text": "Second paragraph text...",
      "audio_muted": false,
      "warning": null
    }
  ],
  "tts": {
    "status": "not_generated",
    "audio_path": null
  }
}
```

---

## 5. Step-by-Step Implementation Roadmap

### Phase 1: Backend Page Endpoint & Schema Foundation
- [x] Add `GET /api/projects/{project_id}/pages/{page_number}.jpg` in `backend/app/main.py` using PyMuPDF native JPEG encoding.
- [x] Implement on-disk caching in `<project_dir>/artifacts/pages/`.
- [x] Update `backend/app/projects.py` to support `include_in_audio` on chapters and `blocks: list[dict]`.
- [x] Add backward-compatibility normalization in `normalize_chapters`: automatically synthesize paragraph `blocks` if missing from legacy projects.
- [x] Update `backend/app/tts.py` and `_run_tts` in `main.py` to:
  - Skip chapters where `include_in_audio == False`.
  - Filter out paragraph blocks where `audio_muted == True` when assembling narration text.
- [x] Update `backend/app/parser.py` to retain page number mapping during PDF text extraction.

### Phase 2: Header Refactor & Global Book Details Slideout
- [x] Create `frontend/src/components/BookDetailsModal.jsx` (slideout drawer styling).
- [x] Support Title, Author, Language, ISBN, Subject, Series, Description, and Cover Art upload/preview.
- [x] Add trigger `[Project Title] · [Author] [ ✎ Book Details ]` in the top workspace navigation.
- [x] Remove persistent 33% metadata right column from the editor workspace.

### Phase 3: Left Rail Chapter Outline Modernization
- [x] Implement draggable grab handles (`⠿`) with HTML5 drag-and-drop reordering.
- [x] Add multi-select checkboxes and `Shift + Click` selection.
- [x] Build floating bulk action toolbar: `[ Merge Selected ]` and `[ 🗑 Delete Selected ]`.
- [x] Implement sequential chapter merge with first-chapter title retention and instant Toast Undo.
- [x] Add `🔊 / 🔇` narration toggle per chapter row (persists `include_in_audio`).
- [x] Add narration duration badge (`~X min audio`) and warning counter badge (`⚠️ N checks`).

### Phase 4: Center Workspace Fluid Editor & Inline Warnings
- [x] Implement fluid document editor rendering auto-growing paragraph blocks.
- [x] Implement keyboard ergonomics: `Enter` to split paragraph, `Backspace` at start to merge with previous, cursor up/down traversal.
- [x] Add inter-paragraph hover split divider: `--- ✂ Split Chapter Here ---`.
- [x] Add paragraph gutter controls: `🔊 / 🔇` mute toggle and `P. {page}` badge.
- [x] Render amber left border on paragraphs with pending AI warnings.
- [x] Build contextual action banner: `[ Inspect Scan ↗ ] [ Accept AI Cleaned ] [ Revert to Raw OCR ]`.
- [x] Add optional `[ Raw Text ]` toggle in the editor toolbar.
- [x] Deprecate legacy "Passage 1 / Passage 2" Git diff cards and remove "Lock Step" buttons.

### Phase 5: Dockable PDF Source Inspector
- [x] Create `frontend/src/components/SourceInspector.jsx`.
- [x] Support Peek slideout drawer and Pinned side-by-side split screen.
- [x] Implement zoom (`+`, `-`, `Fit`, `100%`), pan, and page pagination with jump-to-page input.
- [x] Add background prefetching for `page - 1` and `page + 1`.
- [x] Wire `[ Inspect Scan ↗ ]` buttons and paragraph `P. {page}` badges to auto-open and navigate the inspector.

### Phase 6: Modernization Tool Drawer & Final Polish
- [x] Move Text Modernization controls into a dedicated on-demand drawer/panel in Chapter Studio.
- [x] Run full end-to-end tests with scanned multi-column PDF.
- [x] Verify chapter splitting, merging, undo, and TTS/EPUB outputs.

---

## 6. Implementation Status
All phases (Phase 1 through Phase 6) have been implemented and verified with backend unit tests and frontend production builds.
