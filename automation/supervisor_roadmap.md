# Anata Worker Lab Roadmap

## Architecture — planner/executor split

A/B/C are planners only. GitHub-hosted Gemini is the only public Specialist code executor.

- Planner/control state and executor queue: `worker-control`
- Specialist code target: `anata-local-hardening`
- Executor workflow infrastructure: `main` (supervisor never touches it)

## Current exact public state

- exact `anata-local-hardening` HEAD: `fa14691731f5210978a412c4c0b3a87647de4ace`
- latest commit: `planner-c: queue absent scoring freshness regression`
- exact-HEAD Actions: no workflow run/status observed; therefore no PASS
- previous Gemini Specialist commit: `51e0df01dce7ffe87339b58d58ecb4febdc46423`
- A/B/C stored verdicts on `worker-control` all target older HEADs and are stale; none count toward promotion
- worker-control executor queue currently has no pending task; one C task was mistakenly committed under `anata-local-hardening/automation/executor_queue/pending/`, so the executor cannot treat it as the authoritative worker-control queue
- that misplaced task is narrow/safe in content (test-only handoff regression, deterministic pytest, no private/prediction/execution scope) but its `base_sha` is `51e0df...`, not the current exact public HEAD, so it must not be applied as-is
- `worker_lab_lock.json` remains deprecated/informational and is never a gate

## Exact priorities

### A — integration/completeness
Freshly reassess `fa146917...`. Inventory every live-safe `providers*.py` module against `runner.py` registration plus focused live-integration coverage, archive/handoff visibility, and evidence-health visibility. Do not reuse the old BLOCKED verdict. If worker-control pending is empty and one concrete gap remains, enqueue at most one narrow exact-base task on `worker-control`; otherwise record exact-head PLATEAU with evidence.

### B — source breadth
Freshly reassess `fa146917...`. Existing B PLATEAU is stale. Continue requiring first-party machine-stable evidence, explicit economic/entity scope, defensible effective/available/observed clocks, immutable revision identity, non-overlap, and semantic protection against treating stock/context as directional flow. Queue only if a candidate clears all bars; otherwise write a fresh exact-head PLATEAU rationale.

### C — quality audit
Do not retry already-fixed context-vs-scoring freshness work. First correct the queue-location/base-SHA mistake: tasks belong on `worker-control`, and a new task must use the exact current `anata-local-hardening` HEAD immediately before enqueue. Reassess whether the absent-scoring-freshness regression is still missing on `fa146917...`; if it is, enqueue one corrected narrow task on `worker-control` only. If already covered, rotate to the next concrete revision/provenance/missingness/dependence/coverage/handoff defect.

## Planner/executor rules

1. Derive exact current Specialist HEAD and exact-head Actions every run.
2. A/B/C never edit Specialist code directly.
3. Only `worker-control/automation/executor_queue/pending/*.json` is authoritative for queued work.
4. If authoritative pending is non-empty, planners research/reassess rather than enqueue duplicates.
5. Every task uses schema `anata-gemini-task-v1`, exact current full `base_sha`, minimal read/write paths, deterministic pytest-only tests, and `max_attempts <= 2`.
6. Allowed task writes stay under public Specialist `part2/` or `specialist_evidence/`; no private/prediction/API orchestration/journals/Telegram/MT5/broker/execution/secrets.
7. Any Specialist HEAD advance invalidates prior worker verdicts and unexecuted tasks for promotion purposes.

## Promotion gate

Promotion to private `anata-local-hardening` requires, for the same exact public HEAD:
- exact-head Actions PASS
- A = PLATEAU
- B = PLATEAU
- C = PLATEAU
- Supervisor independently = PLATEAU

Any CONTINUE, BLOCKED, missing/stale verdict, stale task, or missing exact-head PASS blocks promotion. After consensus promotion, rotate automatically to the next safe Specialist evidence/data slice.
