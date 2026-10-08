from __future__ import annotations

import json
from part2.capital_flow import runner
from part2.capital_flow.providers import DefiLlamaStablecoinCollector
from part2.capital_flow.storage import load_observations

DEFILLAMA_CHART_FIXTURE = [
    {"date": 1786665600, "totalCirculatingUSD": {"peggedUSD": 100000000000}},
    {"date": 1786924800, "totalCirculatingUSD": {"peggedUSD": 101000000000}}
]


class _DummyCollector:
    def collect(self, **_kwargs):
        return []


def test_defillama_live_scoring_integration(monkeypatch, tmp_path):
    as_of_ms = 1_787_054_400_000  # 2026-08-18 12:00 UTC
    expected_effective_ms = 1_786_924_800_000  # 2026-08-17 00:00 UTC

    class PatchedDefiLlamaCollector:
        def collect(self, *, observed_at_ms: int | None = None, include_backfill: bool = False):
            observed = observed_at_ms if observed_at_ms is not None else as_of_ms
            return DefiLlamaStablecoinCollector.parse_json(
                json.dumps(DEFILLAMA_CHART_FIXTURE),
                observed_at_ms=observed,
                include_backfill=include_backfill,
            )

    monkeypatch.setattr(runner, "DefiLlamaStablecoinCollector", PatchedDefiLlamaCollector)
    for name in (
        "FarsideEtfCollector",
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "StrategyTreasuryCollector",
        "AmericanBitcoinTreasuryCollector",
        "CircleUsdcCirculationCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, _DummyCollector)

    result = runner.run_once(
        local_dir=tmp_path,
        network=True,
        include_backfill=False,
        as_of_ms=as_of_ms,
    )

    attempt = next(
        item for item in result["collection_attempts"]
        if item["collector"] == "defillama_stablecoin"
    )
    assert attempt["status"] == "OK"
    assert attempt["observation_count"] == 1

    assert result["source_errors"] == []
    assert result["appended_observations"] == 1
    assert result["archive_records_loaded"] == 1
    assert result["scoring_records_loaded"] == 1

    archive_rows = load_observations(result["paths"]["archive"])
    assert len(archive_rows) == 1
    obs = archive_rows[0]
    assert obs.family == "stablecoin"
    assert obs.metric == "supply_usd"
    assert obs.source == "defillama_stablecoins"
    assert obs.value == 101000000000.0
    assert obs.unit == "USD"
    assert obs.asset == "USD_STABLECOINS"
    assert obs.effective_at_ms == expected_effective_ms
    assert obs.available_at_ms == as_of_ms
    assert obs.observed_at_ms == as_of_ms
    assert obs.revision == str(as_of_ms)
    assert not bool(dict(obs.provenance).get("context_only", False))

    anata = result["anata_output"]
    assert anata["families"]["stablecoin"]["scoring_observation_count"] == 1
    assert anata["families"]["stablecoin"]["context_observation_count"] == 0
    assert anata["families"]["stablecoin"]["scoring_latest_effective_at_ms"] == expected_effective_ms
    assert anata["families"]["stablecoin"]["scoring_latest_available_at_ms"] == as_of_ms

    stablecoin_evidence = next(
        item for item in anata["source_evidence"]
        if item["family"] == "stablecoin" and item["source"] == "defillama_stablecoins"
    )
    assert stablecoin_evidence["role"] == "scoring"
    assert stablecoin_evidence["latest_effective_at_ms"] == expected_effective_ms
    assert stablecoin_evidence["latest_available_at_ms"] == as_of_ms
    assert stablecoin_evidence["latest_observed_at_ms"] == as_of_ms
    assert stablecoin_evidence["clock_provenance"]["effective"]["revision"] == str(as_of_ms)
    assert stablecoin_evidence["clock_provenance"]["availability"]["revision"] == str(as_of_ms)
    assert stablecoin_evidence["clock_provenance"]["observed"]["revision"] == str(as_of_ms)

    health_collection = anata["evidence_health"]["collection"]
    assert "defillama_stablecoin" in health_collection["successful_collectors"]

    health_stablecoin = anata["evidence_health"]["families"]["stablecoin"]
    assert health_stablecoin["scoring_observation_count"] == 1
    assert health_stablecoin["scoring_latest_effective_at_ms"] == expected_effective_ms
    assert health_stablecoin["scoring_latest_available_at_ms"] == as_of_ms
    assert health_stablecoin["scoring_effective_age_seconds"] == 129600.0
    assert health_stablecoin["scoring_availability_age_seconds"] == 0.0

    with open(result["paths"]["audit_latest"], "r", encoding="utf-8") as f:
        audit = json.load(f)
    assert audit["context_only_observation_count"] == 0
    assert "context_only_observation_count" not in anata

    # Optional PIT guard: run with as_of_ms prior to observation available_at_ms
    guard_as_of_ms = 1_787_054_399_999
    guard_result = runner.run_once(
        local_dir=tmp_path,
        network=False,
        as_of_ms=guard_as_of_ms,
    )
    guard_anata = guard_result["anata_output"]
    assert guard_anata["families"]["stablecoin"]["scoring_observation_count"] == 0
    assert not any(
        item["family"] == "stablecoin" and item["source"] == "defillama_stablecoins"
        for item in guard_anata["source_evidence"]
    )
    assert guard_result["archive_records_loaded"] == 1
