# Anata Worker Lab Supervisor Roadmap

## Exact state — 2026-10-08 21:46 ICT

- Public Specialist branch `anata-local-hardening` exact HEAD: `03a76dc20b3753e6fb7b0509592236e91c7e981e`; most recent change is only `part2/capital_flow/tests/test_farside_live_integration.py` (Gemini Farside run_once integration test).
- Authoritative control branch: `worker-control`, checked HEAD `46811046d848ad5000ef0f41163d185415a6d699`.
- Authoritative queue: **1 pending / 6 done / 6 failed**. The pending `A-20261008-farside-live-scoring-integration-03.json` has `base_sha=11c62faeb6f6816bfc0c049a305a213ab2c42fef`, now stale. Scope was test-only, write path exactly `part2/capital_flow/tests/test_farside_live_integration.py`, targeted pytest plus full Capital Flow pytest, max_attempts 2, no private/execution content.
- Gemini executor workflow [37746873956](https://github.com/EpicNIthan/A-Woker-Lab/actions/runs/37746873956) reported `PASS`, `commit_sha=03a76dc20b3753e6fb7b0509592236e91c7e981e`, code push true, attempt 2. The commit changed only the allowed test path. Queue bookkeeping push failed due to concurrent control updates. **Do not rerun or duplicate** this already-implemented task.
- No exact-HEAD Specialist Lab Validation PASS and no authoritative `done` record with `executor_result.status=PASS` and `commit_sha=03a76dc20b3753e6fb7b0509592236e91c7e981e`. Thus **exact-HEAD validation is BLOCKED** despite the successful executor run. Normal supervisor `done`-record creation was rejected by repository-write safety at 21:46 ICT; do not bypass.
- Planner A (integration/completeness): exact-HEAD **BLOCKED**. Farside covered; next uncovered default collector is `DefiLlamaStablecoinCollector` focused live `run_once` test, followed by context-only `DefiLlamaStablecoinCompositionCollector`. No new queue task while pending.
- Planner B (source breadth): latest exact-HEAD **PLATEAU** on Kraken Proof of Reserves (21:33 ICT): no immutable machine-readable first-party artifact/publication clock. GBTC, BITB, Binance/OKX PoR also lacked necessary source-contract proof. Reassess on any new HEAD.
- Planner C (quality audit): exact-HEAD **BLOCKED** by stale queue; identified malformed unittest entrypoint in `part2/capital_flow/tests/test_v1_handoff.py`. After queue reconciliation, a narrow test-only Gemini correction is appropriate.
- A/B/C are planners only; Gemini alone edits public Specialist code. Their latest worker-control planner statuses are authoritative over older `automation/worker_status/loop-*.json` snapshots.

## Next actions

1. Reconcile completed Farside task on `worker-control` using an approved safe mutation: preserve matching workflow, exact commit and test proof in `done`, then remove identical stale `pending`. A safety rejection is a hard stop, not permission to bypass or replay.
2. Fix executor bookkeeping concurrency through a separately authorized infrastructure workflow: bounded control-branch fetch/rebase/retry with exact task identity and lease. No changes to `main`.
3. When authoritative pending is empty, allow at most one narrow `anata-gemini-task-v1` task, exact fresh base_sha, minimal paths under `part2/**` or `specialist_evidence/**`, deterministic targeted and full Capital Flow pytest, max_attempts<=2. Confirm immediate push-triggered executor run; scheduled polling is fallback.
4. Refresh A/B/C exact-HEAD verdicts after every new Specialist commit and sharpen unproductive lanes after two inconclusive runs.

## Promotion — BLOCKED

Only when current exact public HEAD has either exact-SHA Specialist Lab Validation PASS or matching authoritative executor `done` PASS (targeted/full tests before commit), and **A PLATEAU + B PLATEAU + C PLATEAU + independent Supervisor PLATEAU** all for that SHA. Promote only `part2/**` and `specialist_evidence/**` to private `anata-local-hardening`, never automation, workflows, control/status, secrets, prediction/API orchestration, journals, Telegram, MT5, broker/execution. After valid consensus promotion rotate to the next safe Specialist slice. Never touch `main` or use Railway.
