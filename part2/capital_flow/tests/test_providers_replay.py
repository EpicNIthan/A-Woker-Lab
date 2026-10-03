from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.providers import DefiLlamaStablecoinCollector, FarsideEtfCollector, JsonlFlowAdapter
from part2.capital_flow.replay import CapitalFlowReplay
from part2.capital_flow.storage import append_observations, load_observations

DAY = 86_400_000


class ProviderReplayTests(unittest.TestCase):
    def test_farside_bootstrap_history_is_known_only_from_bootstrap_time(self):
        html = """
        <table>
          <tr><th>Date</th><th>IBIT</th><th>Total</th></tr>
          <tr><td>14 Aug 2026</td><td>(55.5)</td><td>(56.2)</td></tr>
          <tr><td>17 Aug 2026</td><td>111.9</td><td>137.3</td></tr>
        </table>
        """
        observed = 1_800_000_000_000
        latest_only = FarsideEtfCollector.parse_html(html, observed_at_ms=observed)
        self.assertEqual(len(latest_only), 1)
        self.assertEqual(latest_only[0].value, 137.3)
        self.assertEqual(latest_only[0].available_at_ms, observed)

        all_rows = FarsideEtfCollector.parse_html(html, observed_at_ms=observed, include_backfill=True)
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(all_rows[0].available_at_ms, observed)
        self.assertEqual(all_rows[1].available_at_ms, observed)
        self.assertEqual(all_rows[0].value, -56.2)
        self.assertFalse(all_rows[0].visible_at(observed - 1))
        self.assertTrue(all_rows[0].visible_at(observed))
        self.assertIn("NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY", all_rows[0].quality_flags)

    def test_defillama_bootstrap_history_is_known_only_from_bootstrap_time(self):
        payload = json.dumps(
            [
                {"date": 1_700_000_000, "totalCirculatingUSD": {"peggedUSD": 100_000_000_000}},
                {"date": 1_700_086_400, "totalCirculatingUSD": {"peggedUSD": 101_000_000_000}},
            ]
        )
        observed = 1_800_000_000_000
        rows = DefiLlamaStablecoinCollector.parse_json(payload, observed_at_ms=observed, include_backfill=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].available_at_ms, observed)
        self.assertEqual(rows[1].available_at_ms, observed)
        self.assertFalse(rows[0].visible_at(observed - 1))
        self.assertTrue(rows[0].visible_at(observed))

    def test_jsonl_adapter_requires_no_secret_and_preserves_missing_availability(self):
        payload = {
            "family": "exchange_btc",
            "metric": "btc_netflow",
            "asset": "BTC",
            "value": 10,
            "unit": "BTC",
            "effective_at": "2026-08-20T00:00:00Z",
            "available_at": None,
            "observed_at": "2026-08-21T00:00:00Z",
            "source": "licensed-test",
            "source_record_id": "x1",
            "revision": "1",
            "attribution_status": "MEDIUM",
            "attribution_quality": 0.6,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            rows = JsonlFlowAdapter(path).collect()
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0].available_at_ms)

    def test_archive_is_append_only_and_dedups_identical_observation_id(self):
        row = FlowObservation(
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            value=1,
            unit="USD",
            effective_at_ms=DAY,
            available_at_ms=DAY + 1,
            observed_at_ms=DAY + 1,
            source="test",
            source_record_id="1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            self.assertEqual(append_observations(path, [row]), 1)
            self.assertEqual(append_observations(path, [row]), 0)
            self.assertEqual(len(load_observations(path)), 1)

    def test_bounded_archive_load_keeps_only_latest_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            rows = [
                FlowObservation(
                    family="etf", metric="net_flow_usd", asset="BTC", value=i, unit="USD",
                    effective_at_ms=(i + 1) * DAY, available_at_ms=(i + 1) * DAY + 1,
                    observed_at_ms=(i + 1) * DAY + 1, source="source", source_record_id=str(i),
                )
                for i in range(5)
            ]
            self.assertEqual(append_observations(path, rows), 5)
            loaded = load_observations(path, max_records=2)
            self.assertEqual([item.value for item in loaded], [3.0, 4.0])

    def test_archive_skips_unchanged_reobservation_but_keeps_real_revision(self):
        base = FlowObservation(
            family="etf", metric="net_flow_usd", asset="BTC", value=10, unit="USD",
            effective_at_ms=DAY, available_at_ms=10 * DAY, observed_at_ms=10 * DAY,
            source="source", source_record_id="day1", revision="r1",
        )
        unchanged = FlowObservation(
            family="etf", metric="net_flow_usd", asset="BTC", value=10, unit="USD",
            effective_at_ms=DAY, available_at_ms=11 * DAY, observed_at_ms=11 * DAY,
            source="source", source_record_id="day1", revision="r2",
        )
        changed = FlowObservation(
            family="etf", metric="net_flow_usd", asset="BTC", value=12, unit="USD",
            effective_at_ms=DAY, available_at_ms=12 * DAY, observed_at_ms=12 * DAY,
            source="source", source_record_id="day1", revision="r3",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            self.assertEqual(append_observations(path, [base]), 1)
            self.assertEqual(append_observations(path, [unchanged]), 0)
            self.assertEqual(append_observations(path, [changed]), 1)
            self.assertEqual(len(load_observations(path)), 2)

    def test_replay_excludes_revision_until_available(self):
        original = FlowObservation(
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            value=10,
            unit="USD",
            effective_at_ms=DAY,
            available_at_ms=DAY + 100,
            observed_at_ms=DAY + 100,
            source="test",
            source_record_id="day1",
            revision="1",
            cadence_seconds=86400,
        )
        revised = FlowObservation(
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            value=-100,
            unit="USD",
            effective_at_ms=DAY,
            available_at_ms=DAY * 2,
            observed_at_ms=DAY * 2,
            source="test",
            source_record_id="day1",
            revision="2",
            cadence_seconds=86400,
        )
        replay = CapitalFlowReplay()
        early = replay.at([original, revised], as_of_ms=DAY + 1000)
        late = replay.at([original, revised], as_of_ms=DAY * 3)
        early_values = [
            f.current_value
            for f in early.frame.family_states["etf"]["24h"].metric_features
            if f.current_value is not None
        ]
        self.assertEqual(early.frame.normalized_observation_count, 1)
        self.assertEqual(late.frame.normalized_observation_count, 1)
        self.assertEqual(early.frame.visible_observation_count, 1)
        self.assertEqual(late.frame.visible_observation_count, 2)


if __name__ == "__main__":
    unittest.main()
