# Anata Worker Lab Supervisor Roadmap

## Latest exact-SHA audit — 2026-11-02 07:45 ICT

**Source of truth:** `EpicNIthan/A-Woker-Lab` branch `worker-control`; never use inert `automation/**` copies on `anata-local-hardening`. Historical roadmap preserved byte-for-byte in [2026-11-02 06:50 snapshot](./roadmap_archive/supervisor_roadmap_through_20261102_0650.md) (954,160 characters, original blob `5c89cc72cb0aabb3807c6cebfcfb863cd99b81de`). Earlier exact-SHA audit records remain accessible in that archive and Git history. Keep this live roadmap compact and archive older reviews before it nears GitHub's 1 MiB file-size limit.

### Fresh refs, changes and authoritative queue

- Public Specialist `anata-local-hardening` **`db4c6bf1ba8f81ee4f4ae27ba59da756594db853`** (2026-10-29 10:49 UTC); latest parent `c7a3c7f5cb4637b16dcf099097e2b0afe48bc5e4`, +112/-0 in ONLY `part2/capital_flow/tests/test_runner_two_child_spawn_preflight.py`. This proves sequential two-child spawn preflight, **not** overlapping-writer correctness. No new public Specialist commit.
- Private `EpicNIthan/-Anata_AI-Trader` `anata-local-hardening` **`6c0d5d494b9a55b4d66e2daa60aa7ad41bc11cdb`**, read-only, unchanged. Neither `main` branch touched. No Railway.
- Control branch pre-update **`be14887064cb5f53487f3887c2a40cc18318b48c`** is the safe history-archive commit. Since prior supervisor `4e0c288a026a`, only A `7aa919d37614`, C `ecbc33edfeba`, B `709fdb0845f2` planner-status JSON additions and this worker-control archive commit; no public Specialist code, queue or workflow edits.
- Authoritative `worker-control/automation/executor_queue`: **0 pending / 30 done / 27 failed**. `pending/` absent; counts confirmed directly in `done/` and `failed/`. No queued task to audit for `base_sha`, narrow paths, schema or pytest; no pending-without-trigger infrastructure failure currently.
- Last push-triggered Gemini Specialist Executor Queue run **41134555607** (2026-10-30 21:55 UTC) failed at `git diff --check` exit 2 for `SUPERVISOR-20261031-role-identity-0453-01`. The failed task is narrowly scoped to one test, `base_sha=db4c6bf1...`, collect-only + targeted + full Capital Flow pytest required, but no commit was produced. Run job **124333661975** failed, **zero artifacts**; pre-reset patch, diff-check stderr and pytest transcripts missing. Do **not** infer pytest PASS or specific cause; later scheduled executor successes do not validate a public HEAD.

### Exact-SHA validation and same-SHA planner verdicts

- Current public HEAD is **VALIDATED via rule (b) only**: `automation/executor_queue/done/SUPERVISOR-20261029-two-child-spawn-preflight-1748-01.json` has `executor_result.status=PASS` and `commit_sha=db4c6bf1ba8f81ee4f4ae27ba59da756594db853`. Bounded executor task required collect-only, targeted test and full `python -m pytest -q part2/capital_flow/tests` before commit; successful queue run **40860520862**. This is not an independent newly executed regression suite. Any subsequent unvalidated public commit voids proof and all planner verdicts.
- **A — integration/completeness:** `BLOCKED_PLATEAU` at 06:56 ICT (`A-20261102-db4c6bf-0656-execution-only-evidence-gate-blocked.json`). Frozen deterministic contracts need executable exact-SHA proof; do not proliferate speculative tests.
- **B — source breadth:** `SOURCE_ADMISSION_PLATEAU` at 07:33 ICT (`B-20261102-db4c6bf-0733-source-plateau.json`). No new qualified independent first-party BTC/ETH PIT source; rejected sources not recycled.
- **C — quality audit:** `QUALITY_EVIDENCE_INCOMPLETE` at 07:16 ICT (`C-20261102-db4c6bf-quality-execution-evidence-freeze-0716.json`). Source-derived archive-integrity risk and other contracts remain unexecuted.
- **Supervisor independent verdict:** `NOT_PLATEAU`. **PROMOTION BLOCKED**: A/C are not unconditional same-SHA PLATEAU and Supervisor is NOT_PLATEAU. All A/B/C/Supervisor automations enabled on existing schedules; latest scheduled executions A ~07:00, C ~07:18, B ~07:34 ICT. Each lane provides a concrete blocker or PLATEAU rationale, so no sharpening or re-enable necessary.

### Highest-priority safe action and test acceptance

**Stop repeating source-only risk hypotheses; recover executable evidence.** Obtain an authorized disposable exact-`db4c6bf1` checkout or separately authorized infrastructure diagnostics retaining sanitized pre-reset patch, `git diff --check` stderr/exit, and targeted/full pytest transcripts. Current connector can read GitHub state but cannot run full exact-repository pytest. Do not change infrastructure `main`, workflows or secrets under this supervisor mandate. Do not blindly requeue malformed/undebuggable Gemini attempts.

**Frozen no-network deterministic regression contracts** (not yet executed, NOT proven production failures):
1. Valid JSONL rowA without terminal newline, then distinct PIT-visible rowB: either commit two parseable rows + coherent returned/persisted three handoffs + replay dedup, **or** reject without changing archive or baseline handoffs. Mutation followed by ValueError is a FAIL. Separate crash-partial-tail negative control.
2. Positive-ACK controlled overlapping writers: prove serialization and no mixed-generation handoffs; test same-clock stale-generation rollback and scoring/context source-record identity in both returned and persisted output.
3. Orphan-lock recovery with validated nonempty rowB input: prove actual writer-lock timeout and no mutation before test-owned orphan cleanup, then successful append/read/handoff after cleanup, and deduplicated repeat.
4. Execute collect-only, targeted deterministic pytest and full `python -m pytest -q part2/capital_flow/tests` with retained logs. Only Gemini-hosted executor may edit public Specialist code.

**Queue policy:** Only when authoritative pending is empty, a planner may enqueue at most ONE narrow `anata-gemini-task-v1` with fresh exact `base_sha`, minimal permitted `read_paths`/`allowed_write_paths`, deterministic targeted plus full Capital Flow pytest, and no private/prediction/execution content. Verify push immediately triggers Gemini Specialist Executor Queue; pending without a corresponding run is an infrastructure failure. If HEAD advances, invalidate stale tasks/verdicts.

**Promotion boundary:** require exact current HEAD validation (matching Specialist Lab Validation PASS or bounded matching done-task PASS) **AND** unqualified A PLATEAU + B PLATEAU + C PLATEAU + independent Supervisor PLATEAU **for that exact SHA**. Then and only then promote reviewed `part2/**` and `specialist_evidence/**` to private `anata-local-hardening`; NEVER `automation/**`, `.github/**`, controls/status/queue, secrets, prediction/API orchestration/journals, Telegram, MT5, broker/execution. After actual consensus promotion, rotate to next safe Specialist slice. Never touch either `main`, Railway, or schedules; never disable Supervisor; only re-enable unexpectedly disabled A/B/C.
