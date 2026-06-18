# Changelog

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
