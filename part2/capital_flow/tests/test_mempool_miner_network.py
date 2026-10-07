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


def test_mempool_is_live_archived_handoff_visible_and_context_only(monkeypatch, tmp_path):
    from part2.capital_flow import runner
    from part2.capital_flow.storage import load_observations

    observed = 1_790_900_000_000
    collector = MempoolMinerNetworkCollector(fetch_text=lambda _: json.dumps(PAYLOAD))

    class EmptyCollector:
        def collect(self, **_kwargs):
            return ()

    for name in (
        "FarsideEtfCollector",
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "StrategyTreasuryCollector",
        "AmericanBitcoinTreasuryCollector",
        "CircleUsdcCirculationCollector",
        "DefiLlamaStablecoinCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, EmptyCollector)
    monkeypatch.setattr(runner, "MempoolMinerNetworkCollector", lambda: collector)

    result = runner.run_once(local_dir=tmp_path, network=True, as_of_ms=observed)

    attempt = next(
        item for item in result["collection_attempts"]
        if item["collector"] == "mempool_miner_network"
    )
    assert attempt["status"] == "OK"
    assert attempt["observation_count"] == 2
    assert "mempool_miner_network" in result["anata_output"]["evidence_health"]["collection"]["successful_collectors"]

    archived = load_observations(result["paths"]["archive"])
    assert len(archived) == 2
    assert all(obs.family == "miner" for obs in archived)
    assert all(obs.provenance["context_only"] is True for obs in archived)
    assert all(obs.available_at_ms == observed for obs in archived)
    assert all(obs.observed_at_ms == observed for obs in archived)
    assert archived[0].effective_at_ms == 1_790_832_000_000
    assert archived[1].effective_at_ms == 1_790_832_000_000

    miner = result["anata_output"]["families"]["miner"]
    assert miner["status"] == "CONTEXT_ONLY"
    assert miner["context_observation_count"] == 2
    assert miner["scoring_observation_count"] == 0

    evidence = next(
        item for item in result["anata_output"]["source_evidence"]
        if item["source"] == "mempool.space official API"
    )
    assert evidence["role"] == "context"
    assert evidence["latest_effective_at_ms"] == archived[0].effective_at_ms
    assert evidence["latest_available_at_ms"] == archived[0].available_at_ms

    health = result["anata_output"]["evidence_health"]["families"]["miner"]
    assert health["visible_observation_count"] == 2
    assert health["scoring_observation_count"] == 0
    assert health["scoring_missing"] is True
    assert result["archive_records_loaded"] == 2
    assert result["scoring_records_loaded"] == 0
