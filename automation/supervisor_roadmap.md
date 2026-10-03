# Anata Worker Lab Roadmap

## Current slice
Capital Flow / On-chain

## Promotion rule
Do NOT promote merely because GitHub Actions passes. Promotion requires:
1. exact current public `anata-local-hardening` HEAD = GitHub Actions PASS;
2. loop-A verdict = PLATEAU for that exact HEAD;
3. loop-B verdict = PLATEAU for that exact HEAD;
4. loop-C verdict = PLATEAU for that exact HEAD;
5. Supervisor independently agrees PLATEAU after reviewing source/data gaps, tests, contracts, recent diffs and blockers.

Any CONTINUE or BLOCKED verdict prevents promotion.

## Current roadmap
1. Repair the three known Capital Flow validation regressions without weakening PIT/provenance/no-future-leakage rules.
2. Once green, review remaining Capital Flow evidence gaps and practical first-party source opportunities.
3. Improve the highest-value non-overlapping gap one coherent batch at a time.
4. Supervisor actively investigates blockers, corrects worker direction, updates task ideas, and prevents duplicate/low-value work.
5. Only after independent A/B/C + Supervisor plateau consensus, promote the validated slice to private `anata-local-hardening`.
6. Then rotate the public lab to the next highest-value safe Specialist slice.
