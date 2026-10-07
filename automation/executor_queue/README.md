# Gemini Executor Queue

This queue bridges the ChatGPT planner workers (A/B/C/Supervisor) to the GitHub-hosted Gemini code executor.

## Branches

- Task/control queue: `worker-control`
- Code target: `anata-local-hardening`
- Executor infrastructure/workflow: `main`

## Queue layout

- `automation/executor_queue/pending/*.json` — ready for the executor.
- `automation/executor_queue/done/*.json` — executor completed successfully or returned NO_CHANGE.
- `automation/executor_queue/failed/*.json` — stale/invalid/failed tasks.

The scheduled workflow processes at most one pending task per run.

## Task contract

Use schema `anata-gemini-task-v1`:

```json
{
  "schema": "anata-gemini-task-v1",
  "task_id": "A-20261007-example",
  "worker": "A",
  "title": "short implementation title",
  "base_sha": "FULL_40_CHARACTER_anata-local-hardening_SHA",
  "instructions": "Precise implementation instructions and invariants.",
  "read_paths": [
    "part2/capital_flow/runner.py"
  ],
  "allowed_write_paths": [
    "part2/capital_flow/runner.py"
  ],
  "tests": [
    "python -m pytest -q part2/capital_flow/tests"
  ],
  "max_attempts": 2
}
```

## Planner rules

1. Re-read the exact current `anata-local-hardening` HEAD immediately before creating a task.
2. Put that full SHA in `base_sha`. Stale tasks fail closed and are not applied.
3. Make the task narrow. Include only the files Gemini actually needs.
4. Write paths are restricted to public Specialist code/data under `part2/` or `specialist_evidence/`.
5. Never queue secrets, credentials, private-repo content, prediction/composition logic, Telegram, broker/execution, Railway, or API-model orchestration.
6. Tests are deterministic pytest commands only.
7. One task should be one coherent implementation batch.
8. Do not enqueue duplicate tasks for a gap already fixed at the current HEAD.
9. A status/control write failure must not cause the planner to weaken the task or write code itself; retry enqueue on a later run.

## Gemini key behavior

The executor can read up to ten encrypted GitHub Actions secrets named `GEMINI_API_KEY_01` through `GEMINI_API_KEY_10`.

It safely fails over to another configured key for authentication rejection, transient network errors, timeouts, and Gemini 5xx errors. It does **not** rotate across accounts on HTTP 429 quota/rate-limit responses. A quota-limited task remains pending for a later run.
