from __future__ import annotations

import unittest
from unittest.mock import patch

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.engine_v1_1 import CapitalFlowEngineV11
from part2.capital_flow.providers_free import KoteFreeCollector
from part2.capital_flow.providers_kote_active import (
    ACTIVE_KOTE_SPECS,
    ActivatedKoteCollector,
    _closed_bucket_end,
)
from part2.capital_flow.runner import _scoring_history

DAY = 86_400_000


class KoteActivationTests(unittest.TestCase):
    def _spec(self, chart_id: str):
        return next(spec for spec in ACTIVE_KOTE_SPECS if spec.chart_id == chart_id)

    def test_locked_probe_fields_parse_exactly(self) -> None:
        cases = (
            ("exchange-netflow", "exNetBtc", -2747.5, "btc_netflow"),
            ("exchange-reserve", "exReserveBtc", 3_430_565.0, "reserve_btc"),
            ("lth-supply", "lthSupplyBtc", 16_576_262.0, "holder_balance_btc"),
            ("whale-to-exchange", "whaleToExBtc", 1965.0, "holder_exchange_inflow_btc"),
            ("miner-flows", "minerReserveBtc", 1_772_786.0, "miner_reserve_btc"),
        )
        for chart_id, field, value, metric in cases:
            payload = {
                "success": True,
                "data": {
                    "chart": chart_id,
                    "series": [{"t": "2026-08-23", field: value}],
                },
            }
            rows = KoteFreeCollector.parse_payload(
                payload,
                spec=self._spec(chart_id),
                observed_at_ms=1_787_600_000_000,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].metric, metric)
            self.assertEqual(rows[0].value, value)

    def test_closed_daily_bucket_becomes_effective_at_period_end(self) -> None:
        payload = {
            "success": True,
            "data": {
                "chart": "exchange-netflow",
                "series": [{"t": "2026-08-23", "exNetBtc": -100.0}],
            },
        }
        observed = 1_787_600_000_000
        row = KoteFreeCollector.parse_payload(
            payload,
            spec=self._spec("exchange-netflow"),
            observed_at_ms=observed,
        )[0]
        shifted = _closed_bucket_end(row)
        self.assertEqual(shifted.effective_at_ms, row.effective_at_ms + DAY)
        self.assertEqual(shifted.provenance["source_bucket_start_ms"], row.effective_at_ms)
        self.assertIn("EFFECTIVE_AT_CLOSED_BUCKET_END", shifted.quality_flags)

    def test_whale_exchange_inflow_stays_context_only(self) -> None:
        spec = self._spec("whale-to-exchange")
        self.assertTrue(spec.context_only)
        payload = {
            "success": True,
            "data": {
                "chart": "whale-to-exchange",
                "series": [{"t": "2026-08-23", "whaleToExBtc": 1500.0}],
            },
        }
        row = KoteFreeCollector.parse_payload(
            payload,
            spec=spec,
            observed_at_ms=1_787_600_000_000,
        )[0]
        self.assertTrue(row.provenance["context_only"])
        self.assertEqual(_scoring_history([row]), [])

    def test_daily_exchange_source_gets_cadence_aware_freshness(self) -> None:
        as_of = 1_787_600_000_000
        row = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=-100.0,
            unit="BTC",
            effective_at_ms=as_of - 31 * 3600 * 1000,
            available_at_ms=as_of,
            observed_at_ms=as_of,
            source="kote_exchange_netflow",
            source_record_id="test",
            cadence_seconds=86400,
            attribution_status="HIGH",
            attribution_quality=0.75,
            data_quality=0.82,
        )
        freshness, stale = CapitalFlowEngineV11._freshness([row], as_of)
        self.assertFalse(stale)
        self.assertIsNotNone(freshness)
        self.assertGreater(freshness or 0.0, 0.0)

    def test_fast_exchange_source_keeps_original_twelve_hour_limit(self) -> None:
        as_of = 1_787_600_000_000
        row = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=100.0,
            unit="BTC",
            effective_at_ms=as_of - 13 * 3600 * 1000,
            available_at_ms=as_of,
            observed_at_ms=as_of,
            source="fast_exchange",
            source_record_id="test",
            cadence_seconds=3600,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.9,
        )
        _, stale = CapitalFlowEngineV11._freshness([row], as_of)
        self.assertTrue(stale)

    def test_backfill_is_locally_bounded_with_date_range_request(self) -> None:
        spec = self._spec("exchange-netflow")
        payload = {
            "success": True,
            "data": {
                "chart": "exchange-netflow",
                "series": [
                    {"t": f"2026-08-{day:02d}", "exNetBtc": float(day)}
                    for day in range(1, 11)
                ],
            },
        }
        collector = ActivatedKoteCollector(
            api_key="test",
            specs=(spec,),
            backfill_limit=3,
        )
        with patch.object(
            ActivatedKoteCollector,
            "_get_chart_from_date",
            return_value=payload,
        ) as get_range:
            rows = collector.collect_spec(
                spec,
                observed_at_ms=1_788_000_000_000,
                include_backfill=True,
            )
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.value for row in rows], [8.0, 9.0, 10.0])
        kwargs = get_range.call_args.kwargs
        self.assertRegex(kwargs["from_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_normal_collection_keeps_small_limit_path(self) -> None:
        spec = self._spec("exchange-netflow")
        payload = {
            "success": True,
            "data": {
                "chart": "exchange-netflow",
                "series": [{"t": "2026-08-23", "exNetBtc": -100.0}],
            },
        }
        collector = ActivatedKoteCollector(api_key="test", specs=(spec,))
        with patch.object(ActivatedKoteCollector, "_get_chart", return_value=payload) as get_small:
            rows = collector.collect_spec(
                spec,
                observed_at_ms=1_788_000_000_000,
                include_backfill=False,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(get_small.call_args.kwargs["limit"], 5)


if __name__ == "__main__":
    unittest.main()
