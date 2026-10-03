from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from part2.capital_flow.providers_free import (
    KOTE_CHART_SPECS,
    KOTE_SOURCE_CONTRACTS,
    KoteFreeCollector,
)
from part2.capital_flow.runner import run_kote_probe


class FreeSourceTests(unittest.TestCase):
    def _spec(self, chart_id: str):
        return next(spec for spec in KOTE_CHART_SPECS if spec.chart_id == chart_id)

    def test_exchange_netflow_parse_is_first_known_now_and_excludes_partial(self) -> None:
        payload = {
            "success": True,
            "data": {
                "chart": "exchange-netflow",
                "series": [
                    {"t": "2026-08-22", "netflow": -1200.0, "price": 65000.0},
                    {"t": "2026-08-23", "netflow": 400.0, "price": 66000.0},
                    {"t": "2026-08-24", "netflow": 999.0, "partial": True},
                ],
            },
        }
        observed = 1_787_580_000_000
        rows = KoteFreeCollector.parse_payload(
            payload,
            spec=self._spec("exchange-netflow"),
            observed_at_ms=observed,
            include_backfill=True,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1].metric, "btc_netflow")
        self.assertEqual(rows[-1].value, 400.0)
        self.assertTrue(all(row.available_at_ms == observed for row in rows))
        self.assertIn("NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY", rows[0].quality_flags)

    def test_unknown_live_schema_fails_with_numeric_key_diagnostics(self) -> None:
        payload = {
            "success": True,
            "data": {
                "chart": "exchange-reserve",
                "series": [{"t": "2026-08-23", "mystery_btc": 123.0, "usd": 456.0}],
            },
        }
        with self.assertRaisesRegex(ValueError, "mystery_btc"):
            KoteFreeCollector.parse_payload(
                payload,
                spec=self._spec("exchange-reserve"),
                observed_at_ms=1_787_580_000_000,
            )

    def test_mixed_fund_custody_chart_is_context_only(self) -> None:
        payload = {
            "success": True,
            "data": {
                "chart": "fund-flows",
                "series": [{"t": "2026-08-23", "reserve": 250000.0}],
            },
        }
        row = KoteFreeCollector.parse_payload(
            payload,
            spec=self._spec("fund-flows"),
            observed_at_ms=1_787_580_000_000,
        )[0]
        self.assertTrue(row.provenance["context_only"])
        self.assertIn("CONTEXT_ONLY_NOT_SCORING", row.quality_flags)
        self.assertEqual(row.metric, "fund_custody_reserve_btc")

    def test_kote_source_contracts_document_free_key_and_pit_limitations(self) -> None:
        self.assertEqual(len(KOTE_SOURCE_CONTRACTS), 4)
        for contract in KOTE_SOURCE_CONTRACTS:
            data = contract.to_dict()
            self.assertFalse(data["point_in_time_backfill_safe"])
            self.assertTrue(data["availability_rule"])
            self.assertTrue(data["revision_behavior"])
            self.assertTrue(data["fallback_behavior"])
        exchange = KOTE_SOURCE_CONTRACTS[0].to_dict()
        self.assertIn("3 requests/second", exchange["rate_limits"])
        self.assertIn("free", exchange["access_limits"].lower())

    def test_probe_writes_schema_only_and_does_not_create_archive(self) -> None:
        fake_probe = {
            "provider": "Kote Charts",
            "probe_only": True,
            "api_key_included": False,
            "charts": [
                {
                    "chart_id": "exchange-netflow",
                    "sample_keys": ["t", "netflow"],
                    "numeric_keys": ["netflow"],
                }
            ],
        }
        fake_collector = SimpleNamespace(probe=lambda: fake_probe)
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "part2.capital_flow.runner.KoteFreeCollector.from_env",
                return_value=fake_collector,
            ):
                result = run_kote_probe(local_dir=tmp)
            probe_path = Path(tmp) / "kote_probe.json"
            self.assertTrue(probe_path.exists())
            stored = json.loads(probe_path.read_text(encoding="utf-8"))
            self.assertTrue(stored["probe_only"])
            self.assertFalse(stored["api_key_included"])
            self.assertFalse((Path(tmp) / "observations.jsonl").exists())
            self.assertEqual(result["charts"][0]["numeric_keys"], ["netflow"])


if __name__ == "__main__":
    unittest.main()
