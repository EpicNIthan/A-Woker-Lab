# Anata Worker Lab Roadmap

## Current slice
Capital Flow / On-chain

## Exact validated public state
- public branch: `anata-local-hardening`
- exact HEAD: `7e4970a4764c892957c84f96f267a9cdd8abc5d7`
- GitHub Actions: PASS
- newest batch: PIT-safe Strategy corporate BTC treasury collector/tests

## P0 — integration/completeness (Loop A)
`providers_strategy.py` exists, but `runner.py` still does not import/register `StrategyTreasuryCollector`. Normal live runs therefore omit Strategy treasury evidence. Reclaim the expired loop-A mutation lease, wire Strategy into the normal collectors tuple, and add a representative integration regression proving attempt/archive/handoff/evidence-health visibility while `context_only` remains excluded from frozen scoring.

## P1 — quality audit (Loop C)
Refresh the stale 9da4877/BitMEX status against the exact current HEAD. Audit role-separated freshness in `evidence_health.py`: a fresh context-only treasury observation must not make stale directional/scoring treasury evidence appear fresh. If confirmed, repair minimally with regression tests; otherwise identify one concrete freshness/revision/provenance/missingness/dependence/coverage defect.

## P2 — source breadth (Loop B)
Continue independent first-party reserve/custody research. Do not ingest Gate/other candidates unless historical machine-readable artifacts have authoritative publication clocks plus immutable report/revision identity. Rotate to another trustworthy source when a candidate fails the PIT contract; blocked source != PLATEAU.

## Coordination / promotion
- Shared lock is for actual code/test mutation only; research/status/roadmap work is lock-free.
- Current loop-A lease ending 2026-10-04T21:18:00Z is expired/stale and may be cleared/reclaimed normally.
- Keep A integration, B breadth, C quality lanes distinct.
- No promotion until exact current HEAD PASS + A/B/C PLATEAU on that same HEAD + independent Supervisor PLATEAU. Any CONTINUE/BLOCKED/stale status prevents promotion.
- Never touch main or Railway. Specialist evidence/data scope only.
