# Anata Worker Lab Roadmap

## Current slice
Capital Flow / On-chain

## Exact validated public state
- public branch: `anata-local-hardening`
- exact HEAD: `1ebdc70600405d2451e13d175f45bd2da9303635`
- GitHub Actions: PASS
- BitMEX date-prefixed reserve regression: fixed; do not revisit without a new regression

## Promotion gate
No promotion until A+B+C each write PLATEAU for this exact HEAD and Supervisor independently agrees. Any CONTINUE/BLOCKED or stale-head status prevents promotion.

## Prioritized post-PASS work
1. **Corporate BTC treasury evidence (highest value).** Add only if a first-party corporate disclosure gives an explicit entity/legal scope and defensible publication clock. Contract must separate `effective_at` (holding/acquisition/reporting date) from `available_at` (first-party filing/press-release publication time), retain document/filing identity + revision/amendment identity, and never replay later amended holdings into earlier frames. Context-only: do not force treasury holdings/acquisitions bullish/bearish.
   - Tests: publication after effective date is invisible before publication; amendment creates a later revision rather than overwriting; subsidiaries/entities cannot be silently aggregated; missing publication timestamp fails closed.
2. **Independent exchange reserve/custody redundancy.** Require genuinely independent first-party venue/custodian evidence, not another mirror of BitMEX or wallet-attribution inference. Preserve venue/entity scope, snapshot publication time, asset/unit, and revision identity. Do not treat proof-of-reserves liabilities/attestations as exchange netflow.
3. **Audit current families for concrete defects before adding breadth.** ETF and DefiLlama bootstrap history is intentionally non-replayable because row publication clocks are absent. Look for a first-party source with stronger publication/revision timing rather than weakening this rule. Check stablecoin, miner/network, exchange and ETF freshness/revision/provenance tests.
4. **Handoff quality/coverage.** Add tests for explicit family missingness, stale-vs-missing distinction, provenance visibility, revision identity and source dependence; compact handoff must not hide degraded evidence behind aggregate coverage.

## Worker coordination
- Status files referencing `9da4877...` are stale and must be refreshed against `1ebdc706...`.
- One worker should pursue treasury contract/source feasibility; another independent reserve/custody redundancy; another concrete freshness/revision/handoff defects to avoid duplicate work.
- A blocked source is not PLATEAU: rotate to the next trustworthy gap.
