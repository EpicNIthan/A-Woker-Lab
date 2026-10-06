from part2.capital_flow.providers_ibit import IbitHoldingsCollector


CSV = '''iShares Bitcoin Trust ETF
Fund Holdings as of,"Sep 25, 2026"
Inception Date,"Jan 05, 2024"

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Market Currency,Accrual Date
"BTC","BITCOIN","-","Alternative","67004440920.46","100.00","67004440920.46","799878.62850","BTC","-"
"USD","USD CASH","-","Cash","21827.32","0.00","21827.32","21827.32000","USD","-"
'''


def test_ibit_holdings_are_first_party_context_not_cash_flow():
    observed_at_ms = 1_790_380_800_000  # after the source holdings date
    rows = list(IbitHoldingsCollector(fetch_text=lambda _: CSV).collect(observed_at_ms=observed_at_ms))

    assert len(rows) == 1
    row = rows[0]
    assert row.family == "etf"
    assert row.metric == "issuer_holdings_btc"
    assert row.value == 799878.6285
    assert row.unit == "BTC"
    assert row.available_at_ms == observed_at_ms
    assert row.observed_at_ms == observed_at_ms
    assert row.attribution_status == "DIRECT"
    assert row.provenance["context_only"] is True
    assert row.provenance["semantic_guard"] == "issuer_btc_holdings_not_etf_cash_flow"
    assert row.provenance["availability_basis"] == "collector_receipt_first_known"
    assert "NO_SOURCE_NATIVE_PUBLICATION_TIMESTAMP" in row.quality_flags


def test_ibit_holdings_rejects_missing_btc_row():
    broken = CSV.replace('"BTC","BITCOIN"', '"ETH","BITCOIN"')
    collector = IbitHoldingsCollector(fetch_text=lambda _: broken)
    try:
        list(collector.collect(observed_at_ms=1_790_380_800_000))
    except ValueError as exc:
        assert "BTC holding row" in str(exc)
    else:
        raise AssertionError("collector must fail closed when the BTC row disappears")


def test_ibit_is_live_archived_handoff_visible_and_context_only(monkeypatch, tmp_path):
    from part2.capital_flow import runner
    from part2.capital_flow.storage import load_observations

    observed = 1_790_380_800_000
    ibit = IbitHoldingsCollector(fetch_text=lambda _: CSV)

    class EmptyCollector:
        def collect(self, **_kwargs):
            return ()

    for name in (
        "FarsideEtfCollector",
        "BitmexReserveCollector",
        "MempoolMinerNetworkCollector",
        "StrategyTreasuryCollector",
        "AmericanBitcoinTreasuryCollector",
        "CircleUsdcCirculationCollector",
        "DefiLlamaStablecoinCollector",
        "DefiLlamaStablecoinCompositionCollector",
    ):
        monkeypatch.setattr(runner, name, EmptyCollector)
    monkeypatch.setattr(runner, "IbitHoldingsCollector", lambda: ibit)

    result = runner.run_once(local_dir=tmp_path, network=True, as_of_ms=observed)

    attempt = next(
        item for item in result["collection_attempts"]
        if item["collector"] == "ishares_ibit_holdings"
    )
    assert attempt["status"] == "OK"
    assert attempt["observation_count"] == 1
    assert "ishares_ibit_holdings" in result["anata_output"]["evidence_health"]["collection"]["successful_collectors"]

    archived = load_observations(result["paths"]["archive"])
    assert len(archived) == 1
    assert archived[0].metric == "issuer_holdings_btc"
    assert archived[0].effective_at_ms < archived[0].available_at_ms
    assert archived[0].available_at_ms == observed
    assert archived[0].observed_at_ms == observed
    assert archived[0].provenance["context_only"] is True

    etf = result["anata_output"]["families"]["etf"]
    assert etf["context_observation_count"] == 1
    assert etf["scoring_observation_count"] == 0

    evidence = next(
        item for item in result["anata_output"]["source_evidence"]
        if item["source"] == "iShares IBIT official holdings"
    )
    assert evidence["role"] == "context"
    assert evidence["latest_effective_at_ms"] == archived[0].effective_at_ms
    assert evidence["latest_available_at_ms"] == archived[0].available_at_ms

    health = result["anata_output"]["evidence_health"]["families"]["etf"]
    assert health["visible_observation_count"] == 1
    assert health["scoring_observation_count"] == 0
    assert result["archive_records_loaded"] == 1
    assert result["scoring_records_loaded"] == 0
