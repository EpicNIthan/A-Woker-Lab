from __future__ import annotations

from datetime import datetime, timezone

import pytest

from part2.capital_flow.providers_strategy import StrategyTreasuryCollector


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


def test_strategy_uses_sec_acceptance_as_pit_and_explicit_entity_scope():
    submissions = _submissions(
        ("0001193125-26-396093", "8-K", "2026-09-21T08:05:00-04:00", "mstr-20260914.htm"),
    )
    html = "<p>As of September 20, 2026, Strategy holds approximately 846,000 bitcoin.</p>"
    collector = StrategyTreasuryCollector(fetch_json=lambda _: submissions, fetch_text=lambda _: html)
    observed = _ms("2026-09-21T13:00:00Z")
    obs = list(collector.collect(observed_at_ms=observed))[0]

    assert obs.family == "treasury"
    assert obs.metric == "corporate_holdings_btc_context"
    assert obs.value == 846000
    assert obs.available_at_ms == _ms("2026-09-21T12:05:00Z")
    assert obs.available_at_ms < observed
    assert obs.provenance["entity_scope"] == "Strategy Inc"
    assert obs.provenance["availability_basis"] == "sec_acceptance_datetime"
    assert obs.provenance["context_only"] is True
    assert "CONTEXT_ONLY" in obs.quality_flags


def test_strategy_future_filing_is_invisible_and_older_eligible_revision_is_used():
    submissions = _submissions(
        ("0001193125-26-403417", "8-K", "2026-09-28T08:05:00-04:00", "new.htm"),
        ("0001193125-26-396093", "8-K", "2026-09-21T08:05:00-04:00", "old.htm"),
    )
    docs = {
        "new.htm": "<p>As of September 27, 2026, Strategy holds approximately 847,666 bitcoin.</p>",
        "old.htm": "<p>As of September 20, 2026, Strategy holds approximately 846,000 bitcoin.</p>",
    }
    collector = StrategyTreasuryCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda url: docs[url.rsplit("/", 1)[-1]],
    )
    obs = list(collector.collect(observed_at_ms=_ms("2026-09-22T00:00:00Z")))[0]
    assert obs.value == 846000
    assert obs.revision == "0001193125-26-396093"


def test_strategy_amendment_is_later_revision_not_retroactive_overwrite():
    submissions = _submissions(
        ("0001193125-26-400002", "8-K/A", "2026-09-22T10:00:00-04:00", "amended.htm"),
        ("0001193125-26-400001", "8-K", "2026-09-21T08:05:00-04:00", "original.htm"),
    )
    docs = {
        "amended.htm": "<p>As of September 20, 2026, Strategy holds approximately 846,100 bitcoin.</p>",
        "original.htm": "<p>As of September 20, 2026, Strategy holds approximately 846,000 bitcoin.</p>",
    }
    collector = StrategyTreasuryCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda url: docs[url.rsplit("/", 1)[-1]],
    )
    before = list(collector.collect(observed_at_ms=_ms("2026-09-22T12:00:00Z")))[0]
    after = list(collector.collect(observed_at_ms=_ms("2026-09-22T15:00:00Z")))[0]
    assert before.value == 846000
    assert after.value == 846100
    assert before.source_record_id == after.source_record_id
    assert before.revision != after.revision
    assert before.available_at_ms < after.available_at_ms


def test_strategy_fails_closed_without_explicit_entity_scope_or_as_of_date():
    submissions = _submissions(
        ("0001193125-26-396093", "8-K", "2026-09-21T08:05:00-04:00", "mstr.htm"),
    )
    collector = StrategyTreasuryCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda _: "<p>Bitcoin holdings were approximately 846,000.</p>",
    )
    with pytest.raises(ValueError, match="no eligible Strategy BTC holdings filing"):
        list(collector.collect(observed_at_ms=_ms("2026-09-22T00:00:00Z")))


def test_strategy_is_live_archived_handoff_visible_and_context_only(monkeypatch, tmp_path):
    from part2.capital_flow import runner
    from part2.capital_flow.storage import load_observations

    observed = _ms("2026-09-21T13:00:00Z")
    submissions = _submissions(
        ("0001193125-26-396093", "8-K", "2026-09-21T08:05:00-04:00", "mstr-20260914.htm"),
    )
    strategy = StrategyTreasuryCollector(
        fetch_json=lambda _: submissions,
        fetch_text=lambda _: "<p>As of September 20, 2026, Strategy holds approximately 846,000 bitcoin.</p>",
    )

    class EmptyCollector:
        def collect(self, **_kwargs):
            return ()

    for name in (
        "FarsideEtfCollector",
        "IbitHoldingsCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "AmericanBitcoinTreasuryCollector",
        "CircleUsdcCirculationCollector",
        "DefiLlamaStablecoinCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, EmptyCollector)
    monkeypatch.setattr(runner, "StrategyTreasuryCollector", lambda: strategy)

    result = runner.run_once(local_dir=tmp_path, network=True, as_of_ms=observed)

    strategy_attempt = next(
        attempt for attempt in result["collection_attempts"]
        if attempt["collector"] == "strategy_treasury"
    )
    assert strategy_attempt["status"] == "OK"
    assert strategy_attempt["observation_count"] == 1
    assert "strategy_treasury" in result["anata_output"]["evidence_health"]["collection"]["successful_collectors"]

    archived = load_observations(result["paths"]["archive"])
    assert len(archived) == 1
    assert archived[0].metric == "corporate_holdings_btc_context"
    assert archived[0].effective_at_ms == _ms("2026-09-20T23:59:59Z")
    assert archived[0].available_at_ms == _ms("2026-09-21T12:05:00Z")
    assert archived[0].provenance["context_only"] is True

    treasury = result["anata_output"]["families"]["treasury"]
    assert treasury["status"] == "CONTEXT_ONLY"
    assert treasury["context_observation_count"] == 1
    assert treasury["scoring_observation_count"] == 0

    evidence = next(
        item for item in result["anata_output"]["source_evidence"]
        if item["source"] == "SEC EDGAR Strategy filings"
    )
    assert evidence["role"] == "context"
    assert evidence["latest_effective_at_ms"] == archived[0].effective_at_ms
    assert evidence["latest_available_at_ms"] == archived[0].available_at_ms

    health = result["anata_output"]["evidence_health"]["families"]["treasury"]
    assert health["visible_observation_count"] == 1
    assert health["scoring_observation_count"] == 0
    assert health["scoring_missing"] is True
    assert result["archive_records_loaded"] == 1
    assert result["scoring_records_loaded"] == 0
