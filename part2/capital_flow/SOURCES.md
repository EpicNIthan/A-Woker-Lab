# Capital Flow V0 source contracts

This note records what the built-in V0 sources actually provide. It is not permission to treat similarly named provider metrics as interchangeable.

## Availability rule used by V0

`available_at` means the earliest time **this Anata installation may legally use the stored revision**.

- A value first seen by the collector at time `C` is never replayable before `C`.
- When a provider exposes an older historical row but no trustworthy original publication timestamp, a bootstrap scrape stores that row as first-known at the bootstrap collection time. This makes it usable for the current/future state, but **not** for a replay earlier than the bootstrap.
- If a historical value later changes, the new value is appended as a later revision. Earlier replay continues to see the earlier stored revision.
- Re-observing an unchanged row does not create a fake new revision.
- `effective_at` still records the economic period/date the value belongs to. Freshness is based on effective data age, not on how recently the web page was re-downloaded.

This is conservative point-in-time behavior. It does not claim to recover a provider's historical database exactly as it looked before Anata began collecting it.

## Farside Investors — US spot-BTC ETF daily net flow

Built-in source: `https://farside.co.uk/bitcoin-etf-flow-all-data/`

Metric used:

- family: `etf`
- metric: `net_flow_usd`
- source units: US$ millions
- normalized units: USD
- cadence: trading-day data

What the source represents:

- aggregate reported flow across US spot-BTC investment products in the Farside table;
- not exact exchange execution time and not proof of the exact time BTC was purchased/sold by a custodian.

Availability/revisions:

- Farside says the table is automatically generated/updated, but the table does not expose a per-row first-publication timestamp;
- first collector observation becomes the legal `available_at` for that stored revision;
- bootstrap history is tagged `NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY`;
- changed values are stored as later revisions instead of replacing the earlier archive row.

Access/rate/storage:

- public web table; no API key;
- no machine API SLA/rate limit is assumed, so V0 fetches it only at low frequency;
- Capital Flow stores compact derived observations/provenance, not raw page dumps for redistribution.

Missing/fallback:

- non-trading days stay missing;
- a dash is missing, not zero;
- fetch/parse failure leaves ETF missing/stale and is surfaced as a source error.

## DefiLlama — aggregate stablecoin supply

Built-in source: `https://stablecoins.llama.fi/stablecoincharts/all`

Metric used:

- family: `stablecoin`
- metric: `supply_usd`
- units: USD
- cadence used by V0: daily chart observations

What the source represents:

- aggregate stablecoin circulating supply / cash-like crypto liquidity proxy;
- it is **potential purchasing capital**, not proof that stablecoins will buy BTC.

Availability/revisions:

- historical chart rows do not provide a trustworthy original publication timestamp to this collector;
- first collector observation becomes legal `available_at` for the stored revision;
- bootstrap rows cannot be replayed before bootstrap time;
- no forward fill is performed.

Access/rate/storage:

- V0 uses a public endpoint with no key and makes no promise that the endpoint is a permanent supported API contract;
- DefiLlama also offers paid Pro/API datasets, but V0 does not assume they are available;
- failures degrade to missing/stale rather than inventing a replacement.

## Exchange BTC flows/reserves — no fake default provider

V0 deliberately does **not** pretend a premium/revision-sensitive exchange-flow metric is freely point-in-time safe.

Research notes relevant to this decision:

- CryptoQuant's BTC exchange-flow API requires a bearer token and its documentation directs users to Professional/Premium access for the API.
- CryptoQuant documents that entity/wallet clustering is updated and explicitly states that several entity/exchange flow histories do **not** support Point-In-Time accuracy; historical values may change as wallets are discovered/reclassified.
- Glassnode exposes rich live/historical on-chain metrics, but normal API access is a Professional-plan add-on. Glassnode metadata can identify Point-in-Time metrics, and its pricing documentation distinguishes immutable PIT data from retrospectively updated data.

Therefore the built-in exchange family is supplied through the strict `JsonlFlowAdapter` until a provider/metric is selected whose semantics, licensing and revision timing are acceptable. A supplied record must preserve source, record ID, revision, units and `available_at`; attribution quality should be present for entity-labelled data.

Missing exchange data remains `null`; it is never replaced by zero.

## Whale/LTH, miner, treasury/institutional — Phase B

No free metric is silently promoted to these families merely because it has an attractive label.

V0 already supports their schemas/features through the same explicit JSONL observation contract, but the live built-in collector leaves them missing until a reliable provider/metric is chosen and documented. In particular:

- large transfer != whale selling;
- miner/entity histories that can be retrospectively re-clustered must not be backtested as though the final labels were known earlier;
- treasury announcements must preserve announcement/availability time separately from effective holding time;
- ETF holdings/flows and corporate treasury holdings are different families/economic events and are not automatically independent evidence.

## External JSONL contract

The adapter accepts `cf-observation-v1`-compatible JSONL. Important fields include:

```text
family
metric
asset
value
unit
effective_at / effective_at_ms
available_at / available_at_ms
observed_at / observed_at_ms
source
source_record_id
revision
cadence_seconds
attribution_status
attribution_quality
data_quality
economic_event_id
dependence_group
provenance
quality_flags
```

If `available_at` is absent/unknown, the observation is archived but excluded from causal state/replay.

`economic_event_id` and `dependence_group` are explicit hints for duplicate/overlap control. V0 does not invent causal equivalence from similar timestamps or amounts.


## mempool.space — Bitcoin network mining context (context-only)

Built-in first-party source: `https://mempool.space/api/v1/mining/hashrate/1m`

Metrics: miner-family `network_hashrate_hs` and `network_difficulty`. These are context-only and excluded from frozen miner scoring.

Point-in-time contract: source measurement time is `effective_at`; collector receipt is the legal `available_at` because the endpoint exposes no trustworthy per-revision publication timestamp. Historical rows are not backdated into replay, including bootstrap/backfill. Rolling hashrate estimates may be revised, so this source is not point-in-time-backfill-safe.

Semantic boundary: hashrate/difficulty describe network mining capacity, not miner BTC transfers, miner selling, exchange deposits, purchasing capital, or BTC price direction. No bullish/bearish inference is produced. Empty, malformed, or non-positive evidence fails closed to explicit missing/stale context.

Access/storage: public HTTPS API with no key and no assumed rate-limit/SLA. Capital Flow stores compact normalized observations/provenance rather than raw response dumps.
