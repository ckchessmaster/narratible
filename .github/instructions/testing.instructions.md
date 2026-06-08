---
description: "Use when creating or modifying backend/frontend unit tests in Echo-Scribe. Enforces manual mutation checks and report generation."
name: "Echo-Scribe Testing And Mutation Policy"
applyTo:
  - "backend/tests/**/*.py"
  - "frontend/src/**/*.test.js"
  - "frontend/src/**/*.test.jsx"
  - "frontend/src/**/*.test.ts"
  - "frontend/src/**/*.test.tsx"
  - "frontend/src/**/*.spec.js"
  - "frontend/src/**/*.spec.jsx"
  - "frontend/src/**/*.spec.ts"
  - "frontend/src/**/*.spec.tsx"
---
# Echo-Scribe Testing And Mutation Policy

When a unit test is introduced or changed, treat mutation validation as required.

## Required Workflow

1. Run baseline checks using the test runner skill.
2. Perform a manual mutation against the changed test or covered production logic.
- Example mutations: invert assertion expectation, change boundary value, remove a branch check.
3. Re-run the relevant test command and confirm the mutated behavior is detected (test fails).
4. Revert mutation and re-run to confirm tests pass again.
5. Generate a run report with mutation evidence.

## Mandatory Report Artifacts

- Save report under `reports/test-validation/`.
- Include:
  - changed test files
  - mutation target
  - mutation summary
  - whether mutation was killed (expected failing outcome observed)
  - command matrix with pass/fail

## Skill Shortcut

Use [run-test-validation.ps1](../skills/echo-scribe-test-runner/scripts/run-test-validation.ps1) to execute checks and write a timestamped report.
