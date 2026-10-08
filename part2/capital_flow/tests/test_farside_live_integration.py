from __future__ import annotations

from part2.capital_flow import runner
from part2.capital_flow.providers import FarsideEtfCollector
from part2.capital_flow.storage import load_observations

FARSIDE_HTML = """
<table>
  <tr><th>Date</th><th>IBIT</th><th>Total</th></tr>
  <tr><td>14 Aug 2026</td><td>(55.5)</td><td>(56.2)</td></tr>
  <tr><td>17 Aug 2026</td><td>111.9</td><td>137.3</td></tr>
</table>
"""


class _DummyCollector:
    def collect(self, **_kwargs):
        return []


def test_farside_live_scoring_integration(monkeypatch, tmp_path):
    as_of_ms = 1_787_054_400_000  # 18 Aug 2026 12:00 UTC
    expected_effective_ms = 1_786_924_800_000  # 17 Aug 2026 midnight UTC

    # Patch runner collectors: FarsideEtfCollector uses parse_html with clock/backfill, others return []
    class PatchedFarsideCollector:
        def collect(self, *, observed_at_ms: int | None = None, include_backfill: bool = False):
            observed = observed_at_ms if observed_at_ms is not None else as_of_ms
            return FarsideEtfCollector.parse_html(
                FARSIDE_HTML,
                observed_at_ms=observed,
                include_backfill=include_backfill,
            )

    monkeypatch.setattr(runner, "FarsideEtfCollector", PatchedFarsideCollector)
    for name in (
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "StrategyTreasuryCollector",
        "AmericanBitcoinTreasuryCollector",
        "CircleUsdcCirculationCollector",
        "DefiLlamaStablecoinCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, _DummyCollector)

    result = runner.run_once(
        local_dir=tmp_path,
        network=True,
        include_backfill=False,
        as_of_ms=as_of_ms,
    )

    # Assert farside_etf collection attempt
    attempt = next(
        item for item in result["collection_attempts"]
        if item["collector"] == "farside_etf"
    )
    assert attempt["status"] == "OK"
    assert attempt["observation_count"] == 1

    assert result["source_errors"] == []
    assert result["appended_observations"] == 1
    assert result["archive_records_loaded"] == 1
    assert result["scoring_records_loaded"] == 1

    # Read archive observations
    archive_rows = load_observations(result["paths"]["archive"])
    assert len(archive_rows) == 1
    obs = archive_rows[0]
    assert obs.source == "farside_btc_etf"
    assert obs.value == 137.3
    assert obs.unit == "USD_MILLIONS"
    assert obs.effective_at_ms == expected_effective_ms
    assert obs.available_at_ms == as_of_ms
    assert obs.observed_at_ms == as_of_ms
    assert obs.revision == str(as_of_ms)

    # Assert anata_output constraints
    anata = result["anata_output"]
    assert anata["families"]["etf"]["scoring_observation_count"] == 1
    assert anata["families"]["etf"]["context_observation_count"] == 0
    assert anata["families"]["etf"]["scoring_latest_effective_at_ms"] == expected_effective_ms

    # Assert source_evidence contains ETF farside_btc_etf role scoring with correct three clocks and revision
    farside_evidence = next(
        item for item in anata["source_evidence"]
        if item["family"] == "etf" and item["source"] == "farside_btc_etf"
    )
    assert farside_evidence["role"] == "scoring"
    assert farside_evidence["latest_effective_at_ms"] == expected_effective_ms
    assert farside_evidence["latest_available_at_ms"] == as_of_ms
    assert farside_evidence["latest_observed_at_ms"] == as_of_ms
    assert farside_evidence["clock_provenance"]["effective"]["revision"] == str(as_of_ms)
    assert farside_evidence["clock_provenance"]["availability"]["revision"] == str(as_of_ms)
    assert farside_evidence["clock_provenance"]["observed"]["revision"] == str(as_of_ms)

    # Assert evidence_health fields
    health_collection = anata["evidence_health"]["collection"]
    assert "farside_etf" in health_collection["successful_collectors"]

    health_etf = anata["evidence_health"]["families"]["etf"]
    assert health_etf["scoring_observation_count"] == 1
    assert health_etf["scoring_latest_effective_at_ms"] == expected_effective_ms
    assert health_etf["scoring_latest_available_at_ms"] == as_of_ms
    assert health_etf["scoring_effective_age_seconds"] == 129600.0
    assert health_etf["scoring_availability_age_seconds"] == 0.0

    # Read audit_latest JSON from result['paths']['audit_latest'] and assert audit['context_only_observation_count'] == 0
    audit_data = load_observations(result["paths"]["audit_latest"]) if False else {}
    import json
    with open(result["paths"]["audit_latest"], "r", encoding="utf-8") as f:
        audit = json.load(f)
    assert audit["context_only_observation_count"] == 0
