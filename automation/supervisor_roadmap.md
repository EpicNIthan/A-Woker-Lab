# Anata Worker Lab Supervisor Roadmap

## Exact state — 2026-10-08 18:50 ICT

- Public Specialist branch `anata-local-hardening` exact HEAD: `03a76dc20b3753e6fb7b0509592236e91c7e981e` (worker-a Farside run_once integration test, only `part2/capital_flow/tests/test_farside_live_integration.py` added).
- Prior HEAD: `11c62faeb6f6816bfc0c049a305a213ab2c42fef` (DefiLlama stablecoin snapshot-coherence fix).
- Authoritative `worker-control` queue: **1 pending / 6 done / 6 failed**. Pending: `A-20261008-farside-live-scoring-integration-03.json`, stale base_sha `11c62fa...`.
- GitHub Gemini Specialist Executor Queue workflow `37746873956` reported `status=PASS`, `commit_sha=03a76dc20b3753e6fb7b0509592236e91c7e981e`, `attempt=2`, code push true. The executor ran task-targeted `python -m pytest -q part2/capital_flow/tests/test_farside_live_integration.py` and full `python -m pytest -q part2/capital_flow/tests` before commit; `git diff --check` was enforced. Queue bookkeeping push failed. See https://github.com/EpicNIthan/A-Woker-Lab/actions/runs/37746873956 .
- No exact-HEAD Specialist Lab Validation PASS and no authoritative worker-control `done` record with `executor_result.status=PASS` and `executor_result.commit_sha=03a76dc20b3753e6fb7b0509592236e91c7e981e`. Therefore **exact-HEAD validation gate is BLOCKED**, despite the successful executor run.
- Supervisor attempted to create the missing `done` proof, but repository write safety rejected the mutation. Do not fabricate or infer the authoritative proof, bypass safety, retry the stale task, or remove pending before verified reconciliation.
- A: integration/completeness — Farside test already implemented, no duplicate. No current exact-HEAD PLATEAU; independently audit live provider registration, archive/handoff and evidence-health.
- B: source breadth — latest exact-HEAD CONTINUE for SEC EDGAR GBTC quarter-end BTC holdings accession `0001588489-26-000005`. Before a task, verify immutable XBRL QName/unit/context, publication clock and context-only non-overlap. Earlier same-HEAD Binance PoR PLATEAU is superseded by CONTINUE.
- C: quality audit — exact-HEAD BLOCKED by stale A queue entry. Confirmed malformed `if __name__ == '__main मूल':` sentinel in `part2/capital_flow/tests/test_v1_handoff.py`; once queue clears, narrow test-only correction through Gemini.
- A/B/C planner automations enabled; all code edits belong to Gemini executor. Private `EpicNIthan/-Anata_AI-Trader` branch `anata-local-hardening` read-only at `6c0d5d494b9a55b4d66e2daa60aa7ad41bc11cdb`.

## Infrastructure priority

1. Reconcile already-completed Farside task atomically on `worker-control`: preserve workflow/test evidence in `done`, then clear identical stale `pending`. If repository-write safety rejects, record BLOCKED; do not circumvent.
2. Review executor `mark_task` bookkeeping race (git push fails on concurrent control update). A safe bounded fetch/rebase/retry on worker-control, with exact task identity and branch leases, belongs to a separate approved infrastructure workflow; never touch `main` in this supervisor lane.
3. When queue empty, allow one narrow `anata-gemini-task-v1` task from A/B/C only, exact fresh base_sha, minimal paths, deterministic targeted + full Capital Flow pytest, `max_attempts<=2`. Queue push should trigger immediate Gemini Specialist Executor Queue; investigate missing run.
4. Refresh A/B/C exact-HEAD verdicts after every Specialist commit. If two runs in one lane produce neither useful task nor concrete blocker/PLATEAU rationale, sharpen that lane.

## Promotion — BLOCKED

Require same exact public HEAD: (a) Specialist Lab Validation PASS for exact SHA or authoritative worker-control done executor PASS for exact SHA with targeted/full pytest before commit; (b) A PLATEAU; (c) B PLATEAU; (d) C PLATEAU; (e) independent Supervisor PLATEAU. No condition may be inherited from older HEADs. Only promote `part2/**` and `specialist_evidence/**` to private `anata-local-hardening`; never `automation/**`, `.github/**`, queue/control/status, secrets, prediction/API orchestration/journals/Telegram/MT5/broker/execution. After valid consensus promotion, rotate to next safe Specialist slice. Never touch `main` or use Railway.
