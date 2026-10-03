# Active Worker Task — Capital Flow / On-chain

Source authority: private repo `EpicNIthan/-Anata_AI-Trader`, branch `anata-local-hardening`.

This public lab contains only the currently exported Specialist evidence/data slice. Workers A/B/C must improve this slice only.

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
- acquire `automation/worker_lab_lock.json` immediately before state-changing work and release after push/exit
- work on branch `anata-local-hardening`, never `main`

If a trustworthy source is blocked, record the exact blocker and rotate to another non-overlapping Capital Flow/On-chain opportunity rather than weakening evidence rules.
