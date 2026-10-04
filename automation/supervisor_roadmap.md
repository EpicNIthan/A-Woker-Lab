# Anata Worker Lab Roadmap

## Current slice
Capital Flow / On-chain

## Exact validated public state
- public branch: `anata-local-hardening`
- exact HEAD: `1ebdc70600405d2451e13d175f45bd2da9303635`
- GitHub Actions: PASS
- BitMEX date-prefixed reserve regression: fixed

## Promotion rule
Do NOT promote merely because GitHub Actions passes. Promotion requires:
1. exact current public `anata-local-hardening` HEAD = GitHub Actions PASS;
2. loop-A verdict = PLATEAU for that exact HEAD;
3. loop-B verdict = PLATEAU for that exact HEAD;
4. loop-C verdict = PLATEAU for that exact HEAD;
5. Supervisor independently agrees PLATEAU after reviewing source/data gaps, tests, contracts, recent diffs and blockers.

Any CONTINUE or BLOCKED verdict prevents promotion.

## Current roadmap
1. Re-assess Capital Flow from the new exact PASS HEAD; do not reapply the BitMEX regex fix.
2. Independently review remaining worthwhile evidence/data gaps before PLATEAU.
3. Highest-value review order:
   - first-party corporate BTC treasury evidence with defensible PIT publication timing and explicit entity scope;
   - independent exchange reserve / custody transparency redundancy that is genuinely non-overlapping;
   - any concrete freshness/revision/provenance defect in current ETF, stablecoin, miner/network or exchange evidence;
   - handoff missingness/quality/coverage defects supported by tests.
4. A blocked source is not a plateau. Rotate to another trustworthy gap before concluding no work remains.
5. Supervisor should actively research blockers and give concrete source-contract/test ideas, not merely report status.
6. Only after A+B+C+Supervisor independently conclude PLATEAU for the same exact PASS HEAD, promote the validated slice to private `anata-local-hardening`.
7. Then rotate the public lab to the next highest-value safe Specialist slice.

## Current supervisor note
The old worker BLOCKED statuses reference the pre-fix HEAD `9da4877...` and are stale. Each worker must reassess `1ebdc706...` and write a fresh verdict for that exact HEAD.
