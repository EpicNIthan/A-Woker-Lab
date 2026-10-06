from __future__ import annotations

from datetime import datetime

from part2.capital_flow.providers_abtc import AmericanBitcoinTreasuryCollector
from part2.capital_flow.providers_circle import CircleUsdcCirculationCollector


def _ms(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def _submissions(*rows):
    return {
        "filings": {
            "recent": {
                "accessionNumber": [r[0] for r in rows],
                "form": [r[1] for r in rows],
                "acceptanceDateTime": [r[2] for r in rows],
                "primaryDocument": [r[3] for r in rows],
            }
        }
    }


def test_american_bitcoin_uses_sec_acceptance_and_explicit_scope():
    submissions = _submissions(
        ("0001755953-26-000001", "10-Q", "2026-10-01T10:00:00-04:00", "abtc.htm"),
    )
    html = (
        "<p>American Bitcoin Corp, as a standalone entity, accumulated "
        "4,000 bitcoin as of September 30, 2026.</p>"
    )
    collector = AmericanBitcoinTreasuryCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda _: html,
    )
    row = list(collector.collect(observed_at_ms=_ms("2026-10-01T15:00:00Z")))[0]

    assert row.family == "treasury"
    assert row.metric == "corporate_holdings_btc_context"
    assert row.value == 4000
    assert row.available_at_ms == _ms("2026-10-01T14:00:00Z")
    assert row.provenance["entity_scope"] == "American Bitcoin Corp standalone entity"
    assert row.provenance["context_only"] is True
    assert row.revision == "0001755953-26-000001"


def test_circle_usdc_uses_sec_acceptance_and_explicit_as_of_date():
    submissions = _submissions(
        ("0001876042-26-000001", "10-Q", "2026-10-02T09:30:00-04:00", "circle.htm"),
    )
    html = (
        "<p>Circle Internet Group reported that as of September 30, 2026, "
        "USDC in circulation was $75.5 billion.</p>"
    )
    collector = CircleUsdcCirculationCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda _: html,
    )
    row = list(collector.collect(observed_at_ms=_ms("2026-10-02T14:00:00Z")))[0]

    assert row.family == "stablecoin"
    assert row.metric == "issuer_usdc_circulation_context"
    assert row.value == 75_500_000_000
    assert row.available_at_ms == _ms("2026-10-02T13:30:00Z")
    assert row.provenance["entity_scope"] == "Circle Internet Group Inc and subsidiaries"
    assert row.provenance["context_only"] is True
    assert row.revision == "0001876042-26-000001"


def test_new_sec_context_collectors_are_live_and_excluded_from_scoring(monkeypatch, tmp_path):
    from part2.capital_flow import runner
    from part2.capital_flow.storage import load_observations

    observed = _ms("2026-10-02T14:00:00Z")
    abtc = AmericanBitcoinTreasuryCollector(
        fetch_json=lambda _: _submissions(
            ("0001755953-26-000001", "10-Q", "2026-10-01T10:00:00-04:00", "abtc.htm"),
        ),
        fetch_text=lambda _: (
            "<p>American Bitcoin Corp, as a standalone entity, accumulated "
            "4,000 bitcoin as of September 30, 2026.</p>"
        ),
    )
    circle = CircleUsdcCirculationCollector(
        fetch_json=lambda _: _submissions(
            ("0001876042-26-000001", "10-Q", "2026-10-02T09:30:00-04:00", "circle.htm"),
        ),
        fetch_text=lambda _: (
            "<p>Circle Internet Group reported that as of September 30, 2026, "
            "USDC in circulation was $75.5 billion.</p>"
        ),
    )

    class EmptyCollector:
        def collect(self, **_kwargs):
            return ()

    for name in (
        "FarsideEtfCollector",
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "StrategyTreasuryCollector",
        "DefiLlamaStablecoinCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, EmptyCollector)
    monkeypatch.setattr(runner, "AmericanBitcoinTreasuryCollector", lambda: abtc)
    monkeypatch.setattr(runner, "CircleUsdcCirculationCollector", lambda: circle)

    result = runner.run_once(local_dir=tmp_path, network=True, as_of_ms=observed)

    attempts = {item["collector"]: item for item in result["collection_attempts"]}
    assert attempts["american_bitcoin_treasury"]["status"] == "OK"
    assert attempts["circle_usdc_circulation"]["status"] == "OK"

    archived = load_observations(result["paths"]["archive"])
    assert {row.metric for row in archived} == {
        "corporate_holdings_btc_context",
        "issuer_usdc_circulation_context",
    }
    assert all(row.provenance["context_only"] is True for row in archived)
    assert result["archive_records_loaded"] == 2
    assert result["scoring_records_loaded"] == 0

    successful = result["anata_output"]["evidence_health"]["collection"]["successful_collectors"]
    assert "american_bitcoin_treasury" in successful
    assert "circle_usdc_circulation" in successful

    families = result["anata_output"]["families"]
    assert families["treasury"]["status"] == "CONTEXT_ONLY"
    assert families["treasury"]["context_observation_count"] == 1
    assert families["treasury"]["scoring_observation_count"] == 0
    assert families["stablecoin"]["context_observation_count"] == 1
    assert families["stablecoin"]["scoring_observation_count"] == 0

    evidence_by_source = {item["source"]: item for item in result["anata_output"]["source_evidence"]}
    assert evidence_by_source["SEC EDGAR American Bitcoin Corp filings"]["role"] == "context"
    assert evidence_by_source["SEC EDGAR Circle Internet Group filings"]["role"] == "context"

    health = result["anata_output"]["evidence_health"]["families"]
    assert health["treasury"]["visible_observation_count"] == 1
    assert health["treasury"]["scoring_observation_count"] == 0
    assert health["stablecoin"]["visible_observation_count"] == 1
    assert health["stablecoin"]["scoring_observation_count"] == 0
