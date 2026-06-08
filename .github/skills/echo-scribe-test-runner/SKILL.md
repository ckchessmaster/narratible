---
name: echo-scribe-test-runner
description: 'Run Echo-Scribe verification checks for backend and frontend changes. Use for test requests, regression checks, and pre-PR validation when full automated tests are not yet available.'
argument-hint: 'Optional scope: backend, frontend, or full'
user-invocable: true
---

# Echo-Scribe Test Runner

Use this skill to run repeatable validation checks and report results consistently.

Primary automation script:
- [run-test-validation.ps1](./scripts/run-test-validation.ps1)

## When To Use

- User asks to run tests.
- User asks to verify a change before commit or PR.
- You need a quick regression check after editing backend or frontend code.

## Current Reality

- There is no committed backend test suite yet.
- Primary verification is lint/build/syntax checks plus focused manual smoke checks.
- Keep this skill aligned with [AGENTS.md](../../../AGENTS.md) and [implementation_plan.md](../../../implementation_plan.md).
- Manual mutation validation is required whenever unit test files are added or changed.

## Procedure

1. Determine scope from request argument.
- backend: run only backend checks.
- frontend: run only frontend checks.
- full or missing argument: run both.

2. Run automation script.
- Full scope example:
	- `pwsh -File .github/skills/echo-scribe-test-runner/scripts/run-test-validation.ps1 -Scope full`
- Backend scope example:
	- `pwsh -File .github/skills/echo-scribe-test-runner/scripts/run-test-validation.ps1 -Scope backend`

3. If test files changed, perform a manual mutation and provide evidence.
- Example invocation after mutation is executed and observed failing:
	- `pwsh -File .github/skills/echo-scribe-test-runner/scripts/run-test-validation.ps1 -Scope full -MutationTarget "backend/tests/test_cleaner.py::test_regex_cleanup" -MutationSummary "Inverted expected cleanup string" -MutationKilled`

4. Review generated report.
- Reports are written to `reports/test-validation/test-validation-<timestamp>.md` unless `-ReportPath` is provided.
- Failures include both command failures and mutation-gate failures.

## Reporting Rules

- Surface failures first with actionable next steps.
- If all checks pass, state residual risk: backend behavior beyond health endpoint may still be scaffold-level.
- Do not claim full test coverage while automated suites are absent.
- Always include report file path in your response when this skill runs.
