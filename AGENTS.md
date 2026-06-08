# AGENTS.md

Agent guidance for this repository. Keep changes small and aligned with the current implementation state.

## Project Snapshot

- Product: Echo-Scribe (PDF to ebook/audiobook workflow)
- Monorepo layout:
  - backend: FastAPI service and processing modules
  - frontend: React + Vite UI
- Current backend API surface is minimal (health endpoint only) while several modules are scaffolds.

Primary docs:
- [README.md](README.md)
- [implementation_plan.md](implementation_plan.md)
- [frontend/README.md](frontend/README.md)

## Quick Start Commands

Backend:
1. cd backend
2. pip install -r requirements.txt
3. python run.py

Frontend:
1. cd frontend
2. npm install
3. npm run dev

Useful checks:
- Frontend lint: cd frontend && npm run lint
- Frontend production build: cd frontend && npm run build

## Architecture Boundaries

Backend:
- Entry point: [backend/run.py](backend/run.py)
- FastAPI app: [backend/app/main.py](backend/app/main.py)
- Config persistence: [backend/app/config.py](backend/app/config.py)
- Processing modules (used by future API routes):
  - [backend/app/parser.py](backend/app/parser.py)
  - [backend/app/cleaner.py](backend/app/cleaner.py)
  - [backend/app/tts.py](backend/app/tts.py)

Frontend:
- App entry: [frontend/src/main.jsx](frontend/src/main.jsx)
- Current wizard UI: [frontend/src/App.jsx](frontend/src/App.jsx)

## Conventions For AI Agents

- Treat implementation_plan.md as a roadmap, not guaranteed current behavior.
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

## Suggested Next Customizations

If this repo grows, create focused instruction files:
- Backend instructions scoped to backend/** for API design and async/background processing rules.
- Frontend instructions scoped to frontend/** for UI/state conventions and accessibility checks.
- Testing instructions scoped to tests/** once backend/frontend test suites are added.
