# Anata Worker Lab Roadmap

## Current slice
Capital Flow / On-chain

## Exact validated public state
- public branch: `anata-local-hardening`
- exact HEAD: `7e4970a4764c892957c84f96f267a9cdd8abc5d7`
- GitHub Actions: PASS
- newest batch: PIT-safe Strategy corporate BTC treasury collector/tests

## Important integration gap found by Supervisor
The Strategy collector exists in `providers_strategy.py` and has focused tests, but `runner.py` does not import or register `StrategyTreasuryCollector` in the live `collectors` tuple. Therefore the new evidence is not yet collected by normal Capital Flow live runs. This is the highest-priority correctness/completeness gap.

## Promotion gate
No promotion until exact current HEAD PASS + A/B/C each independently write PLATEAU for that exact HEAD + Supervisor independently agrees. Any CONTINUE/BLOCKED/stale-head verdict prevents promotion.

## Parallel worker lanes
- **Loop A — integration/completeness:** wire Strategy treasury into normal live collection, add a representative runner/integration regression proving the collector is attempted and context-only evidence does not enter frozen scoring. Keep PIT/missingness/fail-closed semantics.
- **Loop B — source breadth:** after re-reading the exact current HEAD, research one genuinely independent first-party exchange reserve/custody transparency source or another non-overlapping Capital Flow source. Do not duplicate BitMEX or Strategy. Implement only with defensible publication/PIT clocks.
- **Loop C — quality audit:** inspect current ETF/stablecoin/miner/network/exchange/treasury handoff for a concrete freshness/revision/provenance/missingness/coverage defect. Prefer a specific testable defect over generic docs/metadata work.

## Coordination
1. Research/assessment/status updates do **not** require the shared lock.
2. Acquire `automation/worker_lab_lock.json` only immediately before actual code/test mutation on `anata-local-hardening`; keep the lease short and release immediately after push/exit.
3. A worker seeing an active code-mutation lease may continue research and update its own status rather than wasting the run.
4. After any code push, re-read exact HEAD and GitHub Actions before starting another mutation.
5. A blocked source is not PLATEAU; rotate to another trustworthy gap.
6. Do not revisit completed BitMEX regex or Strategy base collector unless a new defect is found.
