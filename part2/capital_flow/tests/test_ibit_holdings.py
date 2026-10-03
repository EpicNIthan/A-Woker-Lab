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
