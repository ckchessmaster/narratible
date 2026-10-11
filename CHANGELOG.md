# Changelog

## Unreleased

## v1.8.0 - 2026-10-10

### Features
- Added an intelligent spatial layout engine and document object model (`analyze_page_layout`) that classifies PDF pages into semantic blocks (`body`, `heading`, `marginalia`, `footnote`, `callout`, `figure_caption`, and `header_footer`) using PyMuPDF vector path analysis, image bounding box detection, and recursive XY-cut gutter analysis.
- Added dynamic verso/recto margin classification to automatically isolate alternating outer margins (left on even pages, right on odd pages), separating margin notes, scripture citations, and dates from the main reading flow while preserving them for EPUB exports.
- Added vector callout box detection via `page.get_drawings()` for shaded cards and text containers, plus illustration and caption binding that suppresses captions and apparatus notes from audio narration.
- Added automatic printed Table of Contents scanning and folio offset calibration across the first 25 pages of a document to synthesize chapter structures and bookmarks when native PDF outlines are missing.
- Redesigned Step 2 into Chapter Studio: a unified, continuous document editor replacing the rigid 3-sub-step workflow ("1. Cleanup/Metadata", "2. Chapter Setup", "3. Final Review") and modal locks with fluid paragraphs, auto-growing textareas, seamless split/merge, hover split dividers, and raw text fallback.
- Added granular audio narration muting with paragraph-level muting toggles (`🔊 / 🔇`) and chapter-level audio exclusion (`include_in_audio`), ensuring frontmatter, footnotes, indexes, and callouts can be excluded from speech synthesis without removing content from EPUB builds.
- Added a dockable, resizable visual PDF Source Inspector with C-accelerated PyMuPDF JPEG streaming (~15ms) and disk caching, featuring interactive SVG/Canvas zoning overlays to view, draw, resize, re-tag, and re-order layout bounding boxes against original scans.
- Added single-click layout template propagation across page ranges, supporting single templates or alternating even/odd (verso/recto) spreads with instant text re-extraction and chapter block synchronization.
- Added Chapter Studio Tools with Unified AI Text Enhancement, combining OCR cleanup and archaic modernization into a single pass (Safe/Balanced/Aggressive and Light/Standard/Deep profiles across Cloud LLM, Local GPU, or fast rule-based modes).
- Added inline visual track changes diffing directly inside editor paragraph blocks for reviewing AI cleanup and modernization proposals, complete with single-passage Accept/Revert and batch Accept All / Revert All controls.
- Added 1-click tools for cross-page paragraph stitching (rejoining broken sentences cut across page boundaries while respecting intervening marginalia/footnotes and repairing split hyphens) and wrapped prose reflow.
- Added on-demand scripture reference expansion (e.g. "Ps 1:4" → "Psalms 1, verse 4") at both the chapter and book level for natural pronunciation across all TTS engines.
- Added a built-in Model Context Protocol (FastMCP) server with tools for project management, chapter editing, text cleaning, task cancellation, log streaming, and EPUB export, supporting both stdio transport (`desktop_app.py --mcp-stdio`) and authenticated HTTP/SSE connections.
- Added MCP Personal Access Token (PAT) authentication with SHA-256 hashed storage, token prefix tracking, last-used timestamps, revocation, and a dedicated frontend MCP Settings tab with one-click client configuration snippets.
- Added an isolated `embedded-llm` profile to the local AI runtime catalog powered by private Python and `uv`, featuring persistent streaming inference with 4-bit BitsAndBytes quantization, Hugging Face token support, and automatic GPU VRAM lifecycle management.
- Replaced the persistent 33% screen-width metadata sidebar with an accessible header flyout sheet for live auto-saving edits to Title, Author, Cover Art, ISBN, Language, Subject, Series, and Description.

### Improvements
- Upgraded speech time-stretching across local TTS engines (Chatterbox, Qwen3-TTS) to use FFmpeg's speech-optimized `atempo` filter (with chained filter stages for extreme playback speeds outside 0.5–2.0x) and graceful fallback to Librosa.
- Enabled scripture citation expansions uniformly across Edge-TTS, Kokoro, F5-TTS, and Chatterbox to prevent awkward pronunciations.
- Added a TTS Converted Text Debugger in Step 3 to inspect speech-normalized text before synthesis, verifying pronunciation expansions, heading reading, and audio filtering.
- Streamlined Step 1 into a fast, dedicated PDF dropzone, relocating secondary metadata and cleaning options to Chapter Studio on-demand tools.
- Enhanced chapter outline management with real-time title search filtering, multi-selection (`Shift + Click`), drag-and-drop reordering, bulk delete, and bulk merge with instant toast undo.
- Added a collapsible Apparatus Notes drawer and popover system for inspecting and navigating peripheral footnotes, marginalia, and callout blocks bound to specific paragraphs.
- Expanded interactive tips for MCP server configuration, Personal Access Tokens, layout zoning overlays, template propagation, inline proposal review, and audio muting.

### Packaging & Runtime
- Added an optional `embeddedllm` task to the Windows Inno Setup installer to bootstrap the Local LLM Runtime (CUDA) alongside Kokoro during setup.
- Hardened Hugging Face cache access on Windows by materializing reparse points and symlinks to prevent `WinError 448` untrusted mount point traversal errors in windowed desktop environments.
- Implemented atomic file writing with exponential retry backoff for task snapshots and engine manifests to prevent Windows file-locking race conditions during concurrent worker access.
- Added support for the `NARRATIBLE_APP_DATA_DIR` environment variable to allow custom runtime and data directory overrides.

### Bugfixes
- Fixed AI enhancement proposal reversions being overwritten or resurrected on subsequent chapter saves.
- Prevented paragraph stitching operations when pending AI review proposals exist to avoid state divergence.
- Fixed layout block order desynchronization when saving chapters or re-extracting text from modified bounding zones.
- Fixed missing verse preservation in prose reflow by protecting lineated poetic passages, lists, and attribution headers.
- Fixed Chatterbox and Qwen3-TTS pitch and speed distortion when adjusting synthesis pacing.

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
