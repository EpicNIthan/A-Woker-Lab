# Gemini Specialist Executor

The public worker lab now separates planning from code execution:

1. ChatGPT Worker A/B/C/Supervisor inspects the public Specialist branch and writes a narrow task into `worker-control/automation/executor_queue/pending/`.
2. GitHub Actions on `main` wakes on a schedule and checks out:
   - `main` for executor infrastructure,
   - `anata-local-hardening` for code,
   - `worker-control` for the task queue.
3. Gemini receives only the planner task plus explicitly listed public files.
4. The executor accepts writes only to exact task allowlisted paths under `part2/` or `specialist_evidence/`.
5. Only deterministic pytest commands from the task are executed.
6. Tests must pass before a commit is pushed to `anata-local-hardening`.
7. A stale `base_sha` fails closed rather than applying an old plan to a new branch state.
8. The executor makes at most two model attempts for one task.

## Model

Default: `gemini-3.5-flash-lite`.

To change it without changing code, create a GitHub Actions repository variable named:

`GEMINI_MODEL`

Example value:

`gemini-3.5-flash-lite`

## Secrets

In GitHub:

**A-Woker-Lab → Settings → Secrets and variables → Actions → New repository secret**

Add any number of these, up to ten:

- `GEMINI_API_KEY_01`
- `GEMINI_API_KEY_02`
- `GEMINI_API_KEY_03`
- `GEMINI_API_KEY_04`
- `GEMINI_API_KEY_05`
- `GEMINI_API_KEY_06`
- `GEMINI_API_KEY_07`
- `GEMINI_API_KEY_08`
- `GEMINI_API_KEY_09`
- `GEMINI_API_KEY_10`

Never commit real keys to any branch.

## Key failover

The executor tries configured keys in order for legitimate reliability failures:

- authentication rejection (401/403),
- timeout/network failure,
- 408,
- 5xx provider failures.

HTTP 429 quota/rate-limit is deliberately **not** routed through other accounts. The task remains pending for a later run. This keeps the key pool a reliability mechanism rather than a quota-bypass mechanism.

The executor logs only the key index that succeeded, never the secret value.

## Schedule

The workflow polls at minutes 05, 20, 35, and 55 each hour and processes at most one pending task per invocation. It can also be launched manually with `workflow_dispatch`.

An empty queue costs no Gemini tokens.

## Safety boundary

The Gemini model cannot choose arbitrary shell commands or arbitrary paths. It returns replacement file contents only. The executor validates the paths, applies them in the temporary GitHub VM, runs allowlisted pytest commands, and pushes only after the tests pass.

The executor never receives private Anata repository content, broker credentials, Telegram credentials, prediction/composition logic, or live-execution authority.
