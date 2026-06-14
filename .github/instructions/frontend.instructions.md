---
description: "Use when building or updating React wizard UI, component state flow, or CSS styling in frontend/src for narratible."
name: "narratible Frontend Conventions"
applyTo:
  - "frontend/src/**/*.jsx"
  - "frontend/src/**/*.js"
  - "frontend/*.js"
  - "frontend/index.html"
  - "frontend/Dockerfile*"
  - "frontend/src/**/*.css"
---
# narratible Frontend Conventions

- Keep implementation aligned with current app boundaries documented in [AGENTS.md](../../AGENTS.md).
- Prefer React function components and hooks, consistent with [frontend/src/App.jsx](../../frontend/src/App.jsx) and [frontend/src/main.jsx](../../frontend/src/main.jsx).
- Preserve the wizard progression behavior unless the task explicitly asks to refactor navigation/state architecture.
- Keep styling in existing CSS files under frontend/src; do not introduce a new styling framework without request.
- Make incremental UI changes instead of large rewrites so behavior remains reviewable.

## First-Time Tips (Coach-Marks)

The app ships a first-time-user coach-mark tour (see [frontend/src/tips.js](../../frontend/src/tips.js), [frontend/src/useTips.js](../../frontend/src/useTips.js), and [frontend/src/components/Coachmark.jsx](../../frontend/src/components/Coachmark.jsx)). Tips are anchored to DOM elements via a `data-tip-anchor="<id>"` attribute and persist dismissal in `localStorage`.

When adding or changing any user-facing control, wizard step, or Settings field, evaluate whether it needs a tip:

1. Decide if the new/changed element introduces behavior a first-time user should be guided through. If unsure, prefer adding a concise tip.
2. If a tip is warranted, add an entry to the `TIPS` array in [frontend/src/tips.js](../../frontend/src/tips.js) with a unique `id`, the correct `context` (`'wizard'` or `'settings'`), the `step` or `tab` it belongs to, an `anchor`, a `placement`, and a short `title`/`body`.
3. Add a matching `data-tip-anchor="<anchor>"` attribute to the target element so the coach-mark can position itself.
4. Keep tips short and chained in a sensible reading order (definition order within a step/tab controls sequence).
5. Do not remove or repurpose existing tip `id`s — dismissed ids are stored in user `localStorage`.

## Frontend Validation Checklist

1. Install dependencies when needed: `cd frontend && npm install`
2. Lint source: `cd frontend && npm run lint`
3. Build production bundle: `cd frontend && npm run build`
4. Run dev server for manual checks: `cd frontend && npm run dev`
5. If you added or changed a user-facing control, confirm a coach-mark tip was added (or consciously skipped) per the First-Time Tips section above.
