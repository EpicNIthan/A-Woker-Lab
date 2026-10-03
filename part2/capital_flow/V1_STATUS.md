# Capital Flow V1 code-output upgrade status

## Goal

Upgrade Capital Flow for a better deterministic output into Anata now. Training/model learning is explicitly deferred to a later stage.

V0 scoring semantics remain frozen unless a later versioned status explicitly changes them.

## V1 result

**Capital Flow V1 Anata-output upgrade passed user-machine validation on 2026-08-24.**

Implemented:

- `.local/capital_flow/anata_latest.json` with schema `cf-anata-handoff-v1`;
- explicit family availability/status for ETF, Exchange BTC, Stablecoin, Whale/LTH, Miner and Treasury;
- separate capital-inflow, BTC-to-liquid-venues and holder-accumulation axes;
- quality/missingness/dynamics kept separate from directional evidence;
- DefiLlama stablecoin composition context for configured major stablecoins;
- component supply, 1d/7d/30d supply changes and current peg-price context;
- component enrichment is context-only and excluded from frozen V0 scoring/freshness;
- optional strict Glassnode PIT adapter that rejects metrics unless metadata explicitly says `is_pit=true`;
- external JSONL adapter remains available for other approved point-in-time-safe/licensed sources;
- no training, future-return labels, confidence calibration, price prediction, BUY/SELL, leverage, sizing, risk or execution logic.

## Backward compatibility

- `.local/capital_flow/latest.json` remains `cf-output-v1`.
- `.local/capital_flow/audit_latest.json` remains the rich audit artifact.
- The existing CapitalFlowEngine scoring receives only scoring observations.
- Context-only enrichment may be archived for Anata/research but cannot silently refresh or alter the frozen score.

## User Windows validation — 2026-08-24

- Newest `part2+part1` fast-forwarded successfully.
- Full Capital Flow focused suite: **33/33 tests passed**.
- First V1 live run completed with `source_errors: []`.
- `cf-anata-handoff-v1` was written successfully.
- Stablecoin component context was populated separately from the scoring history.
- First upgraded run appended 26 genuinely new observations and loaded 3,864 scoring records separately from the larger archive.
- Second same-day live run had `appended_observations: 0`, proving unchanged component snapshots were deduplicated.
- Second run retained `source_errors: []`.
- Exchange BTC, Whale/LTH, Miner and Treasury remained explicit `MISSING` rather than being fabricated.

**V1 is frozen as the validated Anata-output baseline.**

## Current operational version

Capital Flow V1.1 free-source activation was completed and frozen on 2026-08-25.

V1.1 adds real free Exchange BTC, LTH and Miner evidence through the schema-locked Kote integration, keeps whale-to-exchange context-only, keeps Treasury missing until a clean source exists, preserves point-in-time rules, and keeps training deferred.

Final V1.1 user-machine validation passed **47/47 tests**, `source_errors=[]`, and an unchanged normal Kote run appended `0` observations. Core coverage is `1.0`, all three Capital Flow axes are populated, and the live handoff cleanly separates scoring support from context-only support.

See `V1_1_FREE_SOURCES.md` for the frozen V1.1 contracts, source semantics, live evidence, limitations and operating command.
