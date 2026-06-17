# Save and Resume Project Persistence Plan

Date: 2026-06-17

This plan captures the filesystem-backed project save/resume work so it can be picked up after a reboot. The goal is to avoid re-running expensive PDF cleanup/LLM/TTS steps when a user closes the app, resumes later, or edits only a small part of the book.

## Goals

1. Save an in-progress project with the current PDF metadata, chapters, chapter edits, workflow state, and generated artifacts.
2. Resume a project later without re-running completed expensive stages.
3. Regenerate TTS chapter by chapter so text edits do not require rebuilding the entire audiobook.
4. Detect stale chapter audio when chapter text or relevant TTS settings change.
5. Keep the first implementation simple and inspectable by using filesystem persistence instead of adding a database.

## Non-Goals For The First Pass

- Multi-user collaboration.
- Cloud sync.
- Database-backed persistence.
- Full job queue infrastructure.
- Cross-device project portability beyond keeping a self-contained project folder.

## Filesystem Layout

Use one directory per project under an app data projects directory.

For local/dev runs, the likely root should be near the existing app data/config location. For packaged Windows builds, align with the existing `%APPDATA%\narratible` convention.

Suggested layout:

```text
projects/
  {project_id}/
    project.json
    source/
      original.pdf
    artifacts/
      extracted_text.json
      cleaned_chapters.json
    audio/
      {chapter_id}.mp3
      {chapter_id}.wav
```

`project.json` is the source of truth for resumable state. Artifact files hold larger intermediate outputs and generated audio.

## Project Data Model

Minimum useful shape:

```json
{
  "id": "uuid",
  "name": "My Book",
  "created_at": "2026-06-17T00:00:00Z",
  "updated_at": "2026-06-17T00:00:00Z",
  "current_step": "edit",
  "source_pdf": {
    "filename": "book.pdf",
    "stored_path": "source/original.pdf"
  },
  "chapters": [
    {
      "id": "chapter-uuid",
      "order": 1,
      "title": "Chapter 1",
      "text": "...",
      "text_hash": "sha256...",
      "updated_at": "2026-06-17T00:00:00Z",
      "tts": {
        "status": "complete",
        "audio_path": "audio/chapter-uuid.mp3",
        "text_hash": "sha256...",
        "settings_hash": "sha256...",
        "engine": "kokoro",
        "voice": "default",
        "updated_at": "2026-06-17T00:00:00Z",
        "error": null
      }
    }
  ],
  "settings": {
    "cleanup_model": "...",
    "tts_engine": "kokoro",
    "tts_voice": "default"
  }
}
```

Key rule: chapter text and TTS artifacts must be independently hashable.

- `chapter.text_hash` changes whenever the editable chapter text changes.
- `chapter.tts.text_hash` records the chapter text hash used for the existing audio.
- `chapter.tts.settings_hash` records the TTS settings used for the existing audio.
- If either hash no longer matches, the chapter audio is stale.

## Backend API Surface

Add a small project API around filesystem persistence. Keep this incremental and aligned with the existing FastAPI app.

Suggested endpoints:

```text
POST   /projects
GET    /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
PATCH  /projects/{project_id}/chapters/{chapter_id}
POST   /projects/{project_id}/chapters/{chapter_id}/tts
POST   /projects/{project_id}/tts
GET    /projects/{project_id}/chapters/{chapter_id}/audio
DELETE /projects/{project_id}
```

Endpoint behavior:

- `POST /projects`: create a project, optionally from an uploaded PDF.
- `GET /projects`: return lightweight project summaries for a resume screen.
- `GET /projects/{project_id}`: return the full project state needed to restore the UI.
- `PATCH /projects/{project_id}`: update project-level metadata/settings/current step.
- `PATCH /projects/{project_id}/chapters/{chapter_id}`: save title/text/order edits, recompute `text_hash`, and mark audio stale when appropriate.
- `POST /projects/{project_id}/chapters/{chapter_id}/tts`: regenerate only one chapter, unless the existing audio is current and `force` is false.
- `POST /projects/{project_id}/tts`: regenerate all missing/stale chapters, with optional `force=true` to rebuild everything.
- `GET /projects/{project_id}/chapters/{chapter_id}/audio`: stream or return the generated chapter audio.
- `DELETE /projects/{project_id}`: remove a project folder after confirmation in the UI.

## Backend Implementation Notes

Create a focused project persistence module, likely `backend/app/projects.py` or `backend/app/project_store.py`, depending on the current code shape.

Responsibilities:

- Resolve the project root directory consistently for local, Docker, and packaged runs.
- Create project directories and copy uploaded PDFs into `source/original.pdf`.
- Read/write `project.json` atomically to reduce corruption risk on app close.
- Generate stable UUIDs for projects and chapters.
- Compute text/settings hashes.
- Provide helpers for project summaries, full project reads, chapter updates, and audio metadata updates.
- Avoid deleting previous audio until replacement audio generation succeeds.

Atomic write pattern:

1. Write JSON to `project.json.tmp`.
2. Flush/close the file.
3. Replace `project.json` with the temp file using an atomic filesystem replace.

## TTS Behavior

Refactor TTS orchestration so a single chapter can be synthesized independently.

Useful shape:

```python
async def synthesize_project_chapter(project_id: str, chapter_id: str, *, force: bool = False):
    ...
```

Rules:

- If existing audio has matching `text_hash` and `settings_hash`, skip unless `force=true`.
- If chapter text changed, keep the old audio file but report the TTS state as `stale`.
- During generation, set status to `generating`.
- On success, write the new file, update hashes, clear errors, and set status to `complete`.
- On failure, keep any previous audio file and set status to `failed` with the error message.
- Bulk TTS should call the chapter-level function for each missing/stale chapter.

This prevents a single chapter failure from destroying usable output for other chapters.

## Frontend UX

The frontend should treat the backend project object as durable state instead of relying only on transient React state.

Add/adjust UI flows:

- A start/resume view listing recent projects from `GET /projects`.
- Project creation from PDF upload.
- Resume by loading `GET /projects/{project_id}` and restoring the current wizard/editor state.
- Debounced autosave for chapter title/text edits.
- A manual save affordance for dev confidence.
- Save status text such as `Saved`, `Saving...`, `Unsaved changes`, and `Save failed`.
- Per-chapter TTS status: `Not generated`, `Ready`, `Stale`, `Generating`, `Failed`.
- Per-chapter regenerate button.
- Bulk action for generating missing/stale chapter audio.

Keep stale audio playable if it exists, but make the stale state visible so the user understands the audio does not match the current text.

## Implementation Order

1. Add project schema helpers and filesystem persistence.
2. Add backend project CRUD endpoints.
3. Persist uploaded source PDFs and extracted/cleaned chapter artifacts.
4. Wire chapter edits to project persistence and stale TTS detection.
5. Refactor TTS orchestration to support chapter-level regeneration.
6. Add frontend project list/resume flow.
7. Add frontend autosave/manual save state.
8. Add per-chapter TTS status and regenerate controls.
9. Add focused backend tests.
10. Run frontend lint/build and backend compile/tests.

## Testing Plan

Backend tests:

- Project create/save/load round trip.
- Project summaries exclude large chapter text but include useful resume metadata.
- Chapter edit recomputes `text_hash`.
- Chapter edit marks existing TTS stale when the text hash changes.
- Chapter edit does not mark TTS stale when text is unchanged.
- Chapter-level TTS skips current audio when `force=false`.
- Chapter-level TTS regenerates only the requested chapter.
- Bulk TTS processes only missing/stale chapters by default.
- Failed TTS preserves previous audio metadata/file where possible.
- Atomic project writes leave a valid `project.json` after updates.

Frontend checks:

- Resume list renders project summaries.
- Loading a project restores chapters and current wizard state.
- Editing a chapter shows save progress and then saved state.
- Editing chapter text changes that chapter's TTS status to stale.
- Regenerate on one chapter does not trigger regeneration for other chapters.

Repository-specific validation:

- Backend compile: `cd backend && .\.venv\Scripts\python.exe -m compileall app`
- Backend tests: `cd backend && .\.venv\Scripts\python.exe -m pytest tests`
- Frontend lint: `cd frontend && npm run lint`
- Frontend build: `cd frontend && npm run build`
- For any introduced or modified unit test, run the manual mutation validation flow and write the report artifact under `reports/test-validation/`.

## Open Design Questions

- Should project storage live under the same app data root as config, or should local dev use a repo-local ignored directory?
- Should `project.json` store full chapter text, or should chapter text move into separate files once books become large?
- Should exported EPUB/audiobook files be tracked as project artifacts or treated as disposable export outputs?
- Should autosave happen on every edit debounce, on chapter blur, or both?
- Should stale audio remain included in exports, or should export require current audio unless the user explicitly overrides?
