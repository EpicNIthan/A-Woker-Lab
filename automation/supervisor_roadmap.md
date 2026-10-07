# Anata Worker Lab Roadmap

## Architecture — planner/executor split

ChatGPT recurring workers no longer edit Specialist code directly.

- Loop A (:00) = integration/completeness planner
- Gemini executor (:05) = applies at most one queued task, tests, commits on PASS
- Loop C (:15) = quality/provenance planner
- Gemini executor (:20)
- Loop B (:30) = source-breadth planner
- Gemini executor (:35)
- Supervisor (:50) = review/roadmap/consensus planner
- Gemini executor (:55)

Planner task queue lives on `worker-control` under `automation/executor_queue/pending/`.
Executor infrastructure lives on `main`.
Specialist code remains on `anata-local-hardening`.

## Current exact public state

- exact `anata-local-hardening` HEAD: `51e0df01dce7ffe87339b58d58ecb4febdc46423`
- first Gemini end-to-end smoke task: **PASS**
- executor model: `gemini-3.5-flash-lite`
- key used: pool index 1
- result: Gemini changed only `part2/capital_flow/tests/test_v1_handoff.py`, targeted + full Capital Flow pytest passed, then GitHub Actions committed the tested tree
- commit: `51e0df01dce7ffe87339b58d58ecb4febdc46423`
- queue task moved from `pending/` to `done/`
- next planner run must reassess from this new exact HEAD; old verdicts/tasks are stale

## Planner rules

1. Re-read exact current `anata-local-hardening` HEAD and exact-head Actions before planning.
2. Never directly edit Specialist code from A/B/C/Supervisor.
3. If any `pending/*.json` task exists, do not enqueue another; use the run to research/reassess/status instead.
4. Enqueue at most one narrow `anata-gemini-task-v1` task with exact `base_sha`, minimal read paths, exact write allowlist, deterministic pytest commands, and max_attempts <= 2.
5. Tasks stale against a newer HEAD fail closed and must be replanned.
6. Do not queue prediction/composition/API orchestration/Telegram/broker/execution/secrets/private code.
7. Prefer one coherent correctness/evidence improvement over metadata/docs churn.

## Worker lanes

### A — integration/completeness
Compare live-safe provider modules, runner registration, handoff/evidence visibility, and focused live integration tests. Queue one concrete missing integration or regression task when worthwhile.

### B — source breadth
Research genuinely independent first-party Capital Flow/On-chain evidence. Only queue an implementation task after establishing a strong source contract: explicit scope, machine-readable access, defensible effective/available/observed clocks, revision identity, and non-overlap. If no source clears the bar, report PLATEAU rather than inventing breadth.

### C — quality audit
Find one concrete testable freshness/revision/provenance/missingness/dependence/coverage/handoff defect. Verify current code first so completed defects are not re-queued.

## Promotion gate

No private promotion merely because Actions passes.

Promotion requires the same exact public HEAD:
- Actions PASS
- A = PLATEAU
- B = PLATEAU
- C = PLATEAU
- Supervisor independently = PLATEAU

Any CONTINUE/BLOCKED/stale verdict prevents promotion. After consensus, promote the validated Specialist slice to private `anata-local-hardening`, then rotate to the next safe Specialist slice.
