---
description: "Use when adding or modifying FastAPI endpoints, backend processing modules, config persistence, or Python dependencies in Echo-Scribe."
name: "Echo-Scribe Backend Conventions"
applyTo: "backend/**/*.py"
---
# Echo-Scribe Backend Conventions

- Treat [implementation_plan.md](../../implementation_plan.md) as roadmap guidance only; verify current behavior from code.
- Follow boundaries documented in [AGENTS.md](../../AGENTS.md) before introducing new modules.
- Prefer incremental endpoint additions in [backend/app/main.py](../../backend/app/main.py) over broad rewrites.
- Preserve async function signatures in processing modules so call chains remain compatible.
- Keep development CORS permissive unless a task explicitly asks for security hardening.
- Keep config persistence compatible with the user-home file in [backend/app/config.py](../../backend/app/config.py); avoid location changes without migration.
- If extending LLM cleanup behavior, preserve regex fallback when API keys are missing.

## Backend Validation Checklist

1. Run dependency sync when needed: `cd backend && pip install -r requirements.txt`
2. Run a syntax smoke check: `cd backend && python -m compileall app run.py`
3. Start local API for manual verification when endpoint behavior changes: `cd backend && python run.py`
