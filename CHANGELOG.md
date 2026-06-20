# Changelog

## v1.6.0 - 2026-06-19

### Features
- Added a full text modernization workflow with selectable profiles, per-chunk variants, and commit/undo/discard session controls across backend APIs and the Step 2 editor.
- Added richer parse-time metadata extraction (title/author/subject/publisher, ISBN, series, language, description) plus automatic PDF cover extraction and project metadata updates.
- Expanded the guided review experience with persisted review-flow state, modernization checkpoints, and improved chapter/edit synchronization in the review UI.
- Enhanced TTS and voice-library support for F5 voices, including multi-sample management and improved reference transcript handling.

### Bugfixes
- Fixed modernization review actions so selecting, skipping, or clearing chunk variants does not overwrite chapter text until an explicit commit.
- Fixed parsing and synthesis progress UX issues by improving persisted task-status hydration and preventing stale polling/session updates in export flows.
- Fixed stale-audio handling so chapter audio is marked stale when text/settings change, skips regeneration when current, and supports targeted forced regeneration.
- Fixed F5 reference transcript mismatches by validating transcript plausibility against clip duration and preferring transcribed text when supplied text is unsuitable.

## v1.5.0 - 2026-06-17

### Features
- Added backend MCP server support and workspace MCP configuration for runtime inspection tooling.
- Added runtime state and logging support modules with new backend tests for MCP and cloud LLM provider behavior.
- Added a root .env example and updated deployment/runtime docs for local, Docker, and MCP-backed workflows.

### Bugfixes
- Fixed cloud LLM provider handling across backend config, API routing, and cleaning flow.
- Improved frontend settings and upload flow integration for cloud LLM-related configuration paths.
- Improved container and frontend runtime configuration (Docker and nginx) to reduce API connectivity issues during review and local runs.

## v1.4.0 - 2026-06-17

### Features
- Added resume-state persistence across backend and frontend so users can continue work in progress.
- Added AI workflow validation tooling and fixtures to support workflow-level testing.
- Improved LLM-assisted cleaning flow across the app.

### Bugfixes
- Fixed state synchronization issues between UI steps and backend project data.
- Improved persistence reliability for cleaning evaluations and TTS-related project state.
- Hardened LLM cleaner safety behavior and fallback handling.
