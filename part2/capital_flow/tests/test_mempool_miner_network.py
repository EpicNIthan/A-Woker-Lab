import json

import pytest

from part2.capital_flow.providers_mempool import MempoolMinerNetworkCollector


PAYLOAD = {
    "hashrates": [
        {"timestamp": 1790745600, "avgHashrate": 9.21e20},
        {"timestamp": 1790832000, "avgHashrate": 9.35e20},
    ],
    "currentHashrate": 9.34e20,
    "currentDifficulty": 132760000000000,
}


def test_mempool_miner_network_is_receipt_bounded_context_only():
    observed_at_ms = 1_790_900_000_000
    collector = MempoolMinerNetworkCollector(fetch_text=lambda _: json.dumps(PAYLOAD))
    rows = list(collector.collect(observed_at_ms=observed_at_ms))

    assert [row.metric for row in rows] == ["network_hashrate_hs", "network_difficulty"]
    assert all(row.family == "miner" for row in rows)
    assert all(row.available_at_ms == observed_at_ms for row in rows)
    assert all(row.observed_at_ms == observed_at_ms for row in rows)
    assert all(row.provenance["context_only"] is True for row in rows)
    assert all(row.provenance["availability_basis"] == "collector_receipt_first_known" for row in rows)
    assert all("NO_SOURCE_NATIVE_PUBLICATION_TIMESTAMP" in row.quality_flags for row in rows)
    assert rows[0].value == 9.35e20
    assert rows[0].effective_at_ms == 1_790_832_000_000
    assert rows[0].provenance["semantic_guard"] == "network_mining_context_not_miner_btc_flow_or_price_direction"


def test_mempool_historical_rows_are_not_backdated_when_backfill_requested():
    observed_at_ms = 1_790_900_000_000
    collector = MempoolMinerNetworkCollector(fetch_text=lambda _: json.dumps(PAYLOAD))
    rows = list(collector.collect(observed_at_ms=observed_at_ms, include_backfill=True))

    assert len(rows) == 2
    assert {row.available_at_ms for row in rows} == {observed_at_ms}
    assert all(row.source_record_id.endswith(str(row.effective_at_ms)) for row in rows)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hashrates": []},
        {"hashrates": [{"timestamp": 1790832000, "avgHashrate": 0}]},
    ],
)
def test_mempool_miner_network_fails_closed_on_missing_or_invalid_evidence(payload):
    collector = MempoolMinerNetworkCollector(fetch_text=lambda _: json.dumps(payload))
    with pytest.raises(ValueError):
        list(collector.collect(observed_at_ms=1_790_900_000_000))
