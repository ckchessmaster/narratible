# copilot-instructions.md

Agent guidance for this repository. Keep changes small and aligned with the current implementation state.

## Project Snapshot

- Product: narratible (PDF to ebook/audiobook workflow)
- Monorepo layout:
  - backend: FastAPI service and processing modules
  - frontend: React + Vite UI
- Current backend API surface is minimal (health endpoint only) while several modules are scaffolds.

Primary docs:
- [README.md](../README.md)
- implementation_plan.md (roadmap, if present)
- [frontend/README.md](../frontend/README.md)

## Quick Start Commands

Backend:
1. cd backend
2. pip install -r requirements.txt
3. .\.venv\Scripts\python.exe run.py

Frontend:
1. cd frontend
2. npm install
3. npm run dev

Useful checks:
- Frontend lint: cd frontend && npm run lint
- Frontend production build: cd frontend && npm run build
- Backend tests: cd backend && .\.venv\Scripts\python.exe -m pytest tests
- Backend compile check: cd backend && .\.venv\Scripts\python.exe -m compileall app

## MCP Runtime Tools

- Workspace MCP config: [.vscode/mcp.json](../.vscode/mcp.json)
- Server entry point: `cd backend && .\.venv\Scripts\python.exe -m app.mcp_server`
- FastAPI mount when the backend is running: `http://localhost:8000/mcp`
- Use the narratible MCP tools when runtime state is needed, especially `tail_logs` and `watch_logs` for live backend logs, plus project/task/chapter inspection tools for current app data.
- Prefer MCP runtime inspection over guessing from code when diagnosing active parse, cleanup, TTS, export, or upload behavior. Continue using code search and tests for static implementation changes.

## Architecture Boundaries

Backend:
- Entry point: [backend/run.py](../backend/run.py)
- FastAPI app: [backend/app/main.py](../backend/app/main.py)
- MCP server: [backend/app/mcp_server.py](../backend/app/mcp_server.py)
- Config persistence: [backend/app/config.py](../backend/app/config.py)
- Processing modules (used by future API routes):
  - [backend/app/parser.py](../backend/app/parser.py)
  - [backend/app/cleaner.py](../backend/app/cleaner.py)
  - [backend/app/tts.py](../backend/app/tts.py)

Frontend:
- App entry: [frontend/src/main.jsx](../frontend/src/main.jsx)
- Current wizard UI: [frontend/src/App.jsx](../frontend/src/App.jsx)

## Conventions For AI Agents

- Treat implementation_plan.md as a roadmap, not guaranteed current behavior.
- Always use the backend virtualenv interpreter for backend commands and tests: backend/.venv/Scripts/python.exe.
- Verify behavior from code before adding features or tests.
- Preserve async patterns in backend processing functions.
- Keep frontend changes consistent with existing React function-component style.
- Prefer incremental API additions in main.py instead of broad rewrites.
- For every introduced or modified unit test, run a manual mutation check and generate a report artifact under reports/test-validation/.

## Known Pitfalls

- CORS in backend is currently wide open for development. Do not tighten it unless requested.
- App config is stored in a user-home file via Path.home(); avoid breaking that location without migration.
- LLM cleanup in cleaner.py falls back to regex when API keys are missing; keep fallback behavior intact.
- Kokoro TTS path requires local model/runtime setup and may fail in unprepared environments.
