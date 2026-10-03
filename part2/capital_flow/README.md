# Capital Flow — V1.1 Frozen Handoff

**Status: V1.1 FREE-SOURCE BASELINE IMPLEMENTED, USER-MACHINE VALIDATED, AND FROZEN FOR ANATA CONSUMPTION.**

Capital Flow is the Part 2 specialist for slower capital and BTC movement. It is intentionally separate from Market Driver and remains prediction-free.

The original V0 design in repository history is superseded operationally by the implemented V1/V1.1 contracts. Read `V1_STATUS.md`, `V1_1_FREE_SOURCES.md`, `ANATA_HANDOFF.md`, `SOURCES.md`, and `AGENTS.md` before changing this specialist.

## Mission

Capital Flow answers:

> **Where are BTC and purchasing capital moving, how unusual/persistent are those movements, and what longer-horizon supply/liquidity positioning do they create?**

Primary horizon: hours -> days -> weeks.

It does not predict final BTC direction, output BUY/SELL, size positions, or execute trades.

## Frozen Anata-facing baseline

The validated live handoff is `cf-anata-handoff-v1`. The legacy compact output `cf-output-v1` and rich audit artifact remain available for compatibility and audit.

V1.1 provides explicit family availability/status for ETF, Exchange BTC, Stablecoin, Whale/LTH, Miner, and Treasury evidence; separate capital-inflow, BTC-to-liquid-venues, and holder-accumulation axes; explicit quality, missingness, freshness, dynamics, and context-only support; and point-in-time-safe source/provenance handling.

The V1.1 free-source activation passed the owner-machine focused suite with 47/47 tests, `source_errors=[]`, core coverage 1.0, all three Capital Flow axes populated, and unchanged-input deduplication verified. Treasury remains explicitly missing until a clean source exists. Context-only enrichment does not silently alter frozen scoring semantics.

## Non-overlap boundary

Market Driver owns seconds-to-hours spot/perp pressure, order book, funding, OI, basis, liquidations, and immediate mechanical causes. Capital Flow owns slower ETF/on-chain/exchange/stablecoin/holder/miner/treasury movement. NEI owns event meaning. Crowd owns public reaction. Anata owns cross-specialist future prediction.

Do not move another specialist's evidence into Capital Flow merely to increase coverage.

## Point-in-time and revision invariants

Every usable observation must preserve enough provenance to determine when it became legally usable. Historical/live state at time `T` may use only evidence available by `T`. Preserve `effective_at`, `available_at`, `observed_at`, source identity, source record identity, and revision/version metadata where the source supports them.

Never backfill final revised values into earlier states, never pretend a forward-filled daily value is a new hourly observation, and never convert stale/missing evidence to zero.

## Deterministic-first rule

Collection, normalization, timestamps, revisions, net flows, rolling changes, anomaly/persistence, coverage, freshness, missingness, and deduplication remain deterministic/statistical work. Do not train a model to imitate these formulas.

A learned Capital Flow component is optional only if a genuinely difficult internal attribution/classification job later proves incremental unseen-data value. Cross-specialist BTC-price prediction belongs to Anata, not this specialist.

## Readiness / freeze rule

Treat V1.1 as the current frozen first-version Capital Flow input for future Anata composition. Do not reopen feature expansion without a concrete correctness, provenance, source-quality, or interface failure. Missing optional families are represented explicitly and are not a reason to fabricate evidence.

Future Anata composition must consume the versioned handoff with its quality/missingness semantics intact and must allow Capital Flow to be unavailable or degraded without manufacturing a neutral zero.

## Validation and change discipline

Any intentional Capital Flow change must preserve the source-time/revision boundary, family separation, scoring-vs-context separation, and compact-vs-audit separation. Add focused regressions for changed semantics and require local validation before promoting a new frozen version.

The current project roadmap should therefore move on to the next incomplete specialist/readiness blocker rather than continue optimizing Capital Flow without evidence of a defect.
