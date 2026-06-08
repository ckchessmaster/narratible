---
description: "Use when building or updating React wizard UI, component state flow, or CSS styling in frontend/src for Echo-Scribe."
name: "Echo-Scribe Frontend Conventions"
applyTo:
  - "frontend/src/**/*.jsx"
  - "frontend/src/**/*.css"
---
# Echo-Scribe Frontend Conventions

- Keep implementation aligned with current app boundaries documented in [AGENTS.md](../../AGENTS.md).
- Prefer React function components and hooks, consistent with [frontend/src/App.jsx](../../frontend/src/App.jsx) and [frontend/src/main.jsx](../../frontend/src/main.jsx).
- Preserve the wizard progression behavior unless the task explicitly asks to refactor navigation/state architecture.
- Keep styling in existing CSS files under frontend/src; do not introduce a new styling framework without request.
- Make incremental UI changes instead of large rewrites so behavior remains reviewable.

## Frontend Validation Checklist

1. Install dependencies when needed: `cd frontend && npm install`
2. Lint source: `cd frontend && npm run lint`
3. Build production bundle: `cd frontend && npm run build`
4. Run dev server for manual checks: `cd frontend && npm run dev`
