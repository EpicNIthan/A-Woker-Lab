# Active Worker Task — Capital Flow / On-chain

Source authority: private repo `EpicNIthan/-Anata_AI-Trader`, branch `anata-local-hardening`.

This public lab contains only the currently exported Specialist evidence/data slice. Workers A/B/C must improve this slice only.

## Current supervisor roadmap
Always derive the exact current `anata-local-hardening` HEAD before work; do not copy a stale SHA from this file.

P0 — preserve the now-covered architecture:
- every live-safe provider module must be registered in `runner.py` and have focused live-integration coverage
- context-only evidence stays visible in audit/handoff but excluded from frozen scoring
- context-only freshness/causal metadata must never make stale or absent scoring evidence look usable/fresh
- every new source needs defensible PIT timing plus immutable revision/report identity

Lane A — integration/completeness: re-inventory live-safe providers versus runner registration, archive/handoff visibility, evidence-health visibility, and focused live tests. Fix only concrete remaining gaps; otherwise report exact-HEAD PLATEAU.

Lane B — source breadth: seek genuinely independent first-party machine-stable Capital Flow/On-chain evidence. Require explicit economic/entity scope, effective/available/observed clocks, immutable revision identity, and non-overlapping contribution. Reject weak candidates rather than relaxing PIT rules; if no candidate clears the bar, report exact-HEAD PLATEAU with concrete rejected candidates/reasons.

Lane C — quality audit: the context-only/scoring freshness defect is already fixed; do not retry it. Audit the next concrete handoff/revision/provenance/missingness/dependence defect. Prefer a minimal fix plus focused regression; otherwise report exact-HEAD PLATEAU.

Promotion remains blocked unless the exact current public HEAD has PASS and A/B/C independently report PLATEAU for that same exact HEAD and supervisor independently agrees.

## Goal
Make Capital Flow / On-chain evidence richer, fresher, trustworthy, point-in-time safe, non-overlapping, model-ready, and fail-safe. Prefer a genuinely new first-party, machine-stable BTC evidence family or a material source-quality/freshness improvement. Do not duplicate completed IBIT, stablecoin composition, mempool miner/network, or BitMEX reserve-transparency work unless there is a concrete regression.

## Required invariants
- evidence only; no final BTC prediction or trade decision
- no OpenAI/Gemini/9Router/model orchestration
- no MT5, broker, execution, Telegram runtime, or Railway
- preserve PIT/revision timing, provenance, freshness/staleness, missingness, no-future-leakage
- context-only evidence must not be forced bullish/bearish
- raw/audit evidence stays separate from compact handoff
- one coherent batch per worker run
- `automation/worker_lab_lock.json` is deprecated/informational only; never gate, acquire, repair, or block work on it
- use optimistic concurrency for writes: immediately re-read exact branch HEAD and target blob SHA, then normal create/update; never force refs
- status/control write failures do not block substantive code/research work
- work on branch `anata-local-hardening`, never `main`

If a trustworthy source is blocked, record the exact blocker and rotate to another non-overlapping Capital Flow/On-chain opportunity rather than weakening evidence rules.
