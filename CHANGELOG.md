# Changelog

## Unreleased

## v1.7.1 - 2026-08-27

### Packaging
- Replaced the monolithic CUDA-enabled Windows bundle with a slim base app and an isolated, post-install local-AI runtime managed by private Python and `uv`.
- Added checked-by-default installer setup for NVIDIA CUDA PyTorch and Kokoro, with hardware preflight, model verification, retryable failures, and update-time refresh of installed profiles.
- Added a 1.8 GiB release safety limit, Node.js 24 frontend builds, and GitHub CLI release uploads to avoid deprecated Node action runtimes and GitHub's 2 GiB asset failure.

### Features
- Added **Settings > Local AI** engine status and management for installing, verifying, repairing, and removing managed profiles.
- Added a persistent Kokoro sidecar worker so isolated dependencies do not require reloading the model for every chapter.
- Added isolated CUDA 12.8 profiles and persistent workers for F5-TTS and Chatterbox; Qwen3-TTS is now labeled Coming Soon instead of appearing as a broken setup.
- Added a Windows system tray menu for reopening narratible, viewing logs, opening the log folder, and quitting the hidden desktop process gracefully.
- Added a desktop-only Diagnostics view with live filtered logs, pause and refresh controls, copy and download actions, and an explicit Quit command.

### Improvements
- Closing the browser tab now leaves narratible available from the system tray while preserving FastAPI and local-AI worker cleanup on explicit shutdown.

### Safety
- Explicitly disallowed CPU PyTorch fallback and bound Kokoro installation to a hashed Windows/Python 3.12 CUDA 12.8 lockfile.
- Added staged environment activation and rollback pointers so failed local-AI updates preserve the last verified runtime.

### Bugfixes
- Suppressed Windows console windows for GPU detection, runtime installation and verification, persistent TTS workers, voice enhancement, and FFmpeg helpers; cached hardware preflight also removes duplicate Settings probes.
- Fixed windowed packaged startup by disabling Uvicorn's console-aware formatter and using narratible's file-backed logging configuration.
- Added SoundFile and its native dependencies to the isolated Kokoro lock, and marked environments from older locks for update before synthesis.
- Replaced the packaged Tk update prompt with the native Windows dialog and migrated to the current `pymupdf` import, removing Tcl version and `fitz` deprecation errors at startup.
- Integrated CUDA/Kokoro setup progress into the installer and switched the packaged app to the Windows GUI subsystem so runtime maintenance no longer opens a command window.
- Fixed the tray Quit confirmation buttons becoming unresponsive by moving the native dialog and shutdown work outside pystray's Windows message callback.

## v1.7.0 - 2026-08-26

### Features
- Redesigned the Voice Library and Step 3 around a unified voice catalog with recommended voices, saved custom voices, built-in voice browsing, engine filtering, search, previews, and per-project narration controls.
- Added reusable Voice Library entries for Edge-TTS and Kokoro voices alongside cloned voices, with persisted engine ownership, provider voice, speed, temperature, expression, CFG weight, notes, and reference transcript settings.
- Expanded multi-sample reference management across cloned engines with a redesigned workflow for uploading, activating, and removing WAV, MP3, or FLAC samples while retaining the original files.
- Added Chatterbox voice cloning with narration-tuned expression and CFG controls, explicit long-form pauses, silence trimming, pitch-preserving speed adjustment, and CUDA, Apple Metal, or CPU device support.
- Added optional AI reference-audio cleanup through Resemble Enhance, producing a denoised and bandwidth-restored copy while preserving the source recording. This feature uses a separately installed optional runtime.
- Added an experimental Qwen3-TTS 1.7B backend and packaged runtime integration. The engine is visible as **Coming soon** but disabled in the UI pending generation stabilization.
- Added descriptive engine choices explaining online/local operation, relative speed and quality, voice-cloning behavior, and hardware requirements.

### Improvements
- Added one-time engine confirmation for legacy cloned voices and prevented a saved voice from silently switching engines after creation.
- Improved project voice selection so choosing a saved voice also restores its engine-specific defaults and unavailable engines are clearly disabled.
- Expanded local TTS text segmentation and pacing for F5-TTS and Chatterbox, with engine-aware pauses suited to long-form narration.
- Improved model lifecycle management so switching local TTS engines releases cached models and GPU memory before loading another engine.
- Centralized application version loading from `VERSION`, build-time environment values, or packaged `app-version.txt`, and propagated the same version to the frontend and installer.
- Added locked dependency constraints and separate optional requirement sets for GPU engines, Chatterbox, Qwen3-TTS, voice enhancement, and packaged builds.

### Packaging
- Added a dedicated, dependency-fingerprinted `.venv-build` workflow for reproducible Windows builds without modifying the development virtual environment.
- Expanded Docker, CI, PyInstaller, and installer support for Chatterbox, Qwen3-TTS, and the isolated voice-enhancement worker, including packaged frontend and TTS import verification.
- Added CUDA build verification to prevent shipping a CPU-only PyTorch runtime and improved restoration of the selected PyTorch build after optional packages are installed.
- Improved packaged Hugging Face cache handling on Windows by materializing model-cache links where native loaders cannot follow symlinks reliably.
- Hardened installer upgrades by stopping a running app, removing stale bundled runtime files, and installing FFmpeg through `winget` instead of bundling GPL binaries.

### Bugfixes
- Fixed F5-TTS failures caused by reference transcripts that did not match the usable audio after preprocessing or 12-second clipping; narratible now validates transcript plausibility and prefers transcription of the processed clip when needed.
- Fixed clone-engine mismatches so a saved voice cannot be synthesized through a different engine than the one it was created with.
- Fixed packaged optional voice runtimes failing because of missing dynamic imports, package metadata, model source files, or incompatible shared PyTorch dependencies.
- Fixed stale packaged frontend bundles going unnoticed by verifying that every expected TTS engine label is present before startup.
- Fixed Qwen3-TTS compatibility failures with the current Transformers runtime during configuration, model loading, masking, and cached decoding; the engine remains disabled in the UI while output stability is evaluated.

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
