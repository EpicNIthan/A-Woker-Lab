from __future__ import annotations

import json
from part2.capital_flow import runner
from part2.capital_flow.providers_v1 import DefiLlamaStablecoinCompositionCollector
from part2.capital_flow.storage import load_observations

DEFILLAMA_COMPONENT_FIXTURE = {
    "peggedAssets": [
        {
            "id": "2",
            "symbol": "USDT",
            "pegType": "peggedUSD",
            "pegMechanism": "fiat-backed",
            "price": 1.0001,
            "circulating": {"peggedUSD": 1000.0},
            "circulatingPrevDay": {"peggedUSD": 900.0},
            "circulatingPrevWeek": {"peggedUSD": 800.0},
            "circulatingPrevMonth": {"peggedUSD": 700.0},
        },
        {
            "id": "1",
            "symbol": "USDC",
            "pegType": "peggedUSD",
            "pegMechanism": "fiat-backed",
            "price": 0.9999,
            "circulating": {"peggedUSD": 500.0},
            "circulatingPrevDay": {"peggedUSD": 525.0},
            "circulatingPrevWeek": {"peggedUSD": 510.0},
        },
    ]
}


class _DummyCollector:
    def collect(self, **_kwargs):
        return []


def test_defillama_components_live_context_integration(monkeypatch, tmp_path) -> None:
    as_of_ms = 1_787_520_123_456
    expected_effective_ms = (as_of_ms // 86_400_000) * 86_400_000

    class PatchedDefiLlamaComponentsCollector:
        def collect(self, *, observed_at_ms: int | None = None, **_kwargs):
            observed = observed_at_ms if observed_at_ms is not None else as_of_ms
            return DefiLlamaStablecoinCompositionCollector.parse_payload(
                DEFILLAMA_COMPONENT_FIXTURE,
                observed_at_ms=observed,
                symbols=("USDT", "USDC"),
            )

    monkeypatch.setattr(runner, "DefiLlamaStablecoinCompositionCollector", PatchedDefiLlamaComponentsCollector)

    for name in (
        "FarsideEtfCollector",
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "StrategyTreasuryCollector",
        "AmericanBitcoinTreasuryCollector",
        "DefiLlamaStablecoinCollector",
        "CircleUsdcCirculationCollector",
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
        if item["collector"] == "defillama_stablecoin_components"
    )
    assert attempt["status"] == "OK"
    assert attempt["observation_count"] == 9

    assert result["source_errors"] == []
    assert result["appended_observations"] == 9
    assert result[
        "archive_records_loaded"
    ] == 9
    assert result["scoring_records_loaded"] == 0

    archive_rows = load_observations(result["paths"]["archive"])
    assert len(archive_rows) == 9
    for obs in archive_rows:
        assert bool(dict(obs.provenance).get("context_only", False)) is True
        assert obs.family == "stablecoin"
        assert obs.asset in ("USDT", "USDC")
        assert obs.metric in (
            "component_supply_usd",
            "component_supply_change_1d_usd",
            "component_supply_change_7d_usd",
            "component_supply_change_30d_usd",
            "component_price_usd",
        )
        assert obs.effective_at_ms == expected_effective_ms
        assert obs.available_at_ms == as_of_ms
        assert obs.observed_at_ms == as_of_ms
        assert obs.revision == str(as_of_ms)

    usdc_30d = [obs for obs in archive_rows if obs.asset == "USDC" and obs.metric == "component_supply_change_30d_usd"]
    assert len(usdc_30d) == 0

    anata = result["anata_output"]
    stablecoin_ctx = anata["stablecoin_context"]
    assert stablecoin_ctx["known"] is True
    assert stablecoin_ctx["tracked_component_count"] == 2
    assert stablecoin_ctx["tracked_supply_usd"] == 1500.0
    assert stablecoin_ctx["tracked_change_1d_usd"] == 75.0
    assert stablecoin_ctx["peg_price_coverage"] == 1.0
    assert stablecoin_ctx["change_coverage"]["30d"] == 0.5

    usdc_meta = next(item for item in stablecoin_ctx["components"] if item["symbol"].upper() == "USDC")
    assert usdc_meta["change_30d_usd"] is None
    assert "change_30d_usd" in usdc_meta["missing_fields"]

    fam_stablecoin = anata["families"]["stablecoin"]
    assert fam_stablecoin["context_observation_count"] == 9
    assert fam_stablecoin["scoring_observation_count"] == 0
    assert fam_stablecoin["scoring_latest_available_at_ms"] is None
    assert fam_stablecoin["scoring_latest_effective_at_ms"] is None

    source_evidence_entry = next(
        item for item in anata["source_evidence"]
        if item["family"] == "stablecoin" and item["source"] == "defillama_stablecoin_components"
    )
    assert source_evidence_entry["role"] == "context"
    assert source_evidence_entry["clock_provenance"]["effective"] is not None
    assert source_evidence_entry["clock_provenance"]["availability"] is not None
    assert source_evidence_entry["clock_provenance"]["observed"] is not None
    assert source_evidence_entry["clock_provenance"]["effective"]["revision"] == str(as_of_ms)

    evidence_health = anata["evidence_health"]
    assert "defillama_stablecoin_components" in evidence_health["collection"]["successful_collectors"]
    health_fam = evidence_health["families"]["stablecoin"]
    assert health_fam["visible_observation_count"] == 9
    assert health_fam["scoring_observation_count"] == 0
    assert health_fam["scoring_missing"] is True
    assert health_fam["scoring_latest_available_at_ms"] is None
    assert health_fam["scoring_latest_effective_at_ms"] is None

    with open(result["paths"]["audit_latest"], "r", encoding="utf-8") as f:
        audit = json.load(f)
    assert audit["context_only_observation_count"] == 9
    assert "context_only_observation_count" not in anata

    guard_as_of_ms = 1_787_520_123_455
    guard_result = runner.run_once(
        local_dir=tmp_path,
        network=False,
        as_of_ms=guard_as_of_ms,
    )
    guard_anata = guard_result["anata_output"]
    assert guard_anata["families"]["stablecoin"]["context_observation_count"] == 0
    assert not any(
        item["family"] == "stablecoin" and item["source"] == "defillama_stablecoin_components"
        for item in guard_anata["source_evidence"]
    )
    assert guard_anata["stablecoin_context"]["known"] is False
    assert guard_result["archive_records_loaded"] == 9
    assert guard_result["scoring_records_loaded"] == 0
