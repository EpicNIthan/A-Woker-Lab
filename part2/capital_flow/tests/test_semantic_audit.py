from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.engine import CapitalFlowEngine
from part2.capital_flow.features import FAMILY_METRICS, build_metric_feature
from part2.capital_flow.providers import SOURCE_CONTRACTS
from part2.capital_flow.runner import run_once

DAY = 86_400_000
HOUR = 3_600_000
BASE = 1_800_000_000_000


def row(family, metric, value, day, unit, *, quality=0.95, attr=None, cadence=86400, dependence=None):
    effective = BASE + day * DAY
    return FlowObservation(
        family=family,
        metric=metric,
        asset="BTC" if family != "stablecoin" else "USD_STABLECOINS",
        value=value,
        unit=unit,
        effective_at_ms=effective,
        available_at_ms=effective + HOUR,
        observed_at_ms=effective + HOUR,
        source=f"audit-{family}",
        source_record_id=f"{family}:{metric}:{day}",
        revision="1",
        cadence_seconds=cadence,
        attribution_status="MEDIUM" if attr is not None else "NOT_APPLICABLE",
        attribution_quality=attr,
        data_quality=quality,
        dependence_group=dependence,
    )


def synthetic(days=70, *, etf_sign=1, stable_sign=1, exchange_sign=-1):
    rows = []
    stable = 100_000_000_000.0
    reserve = 2_000_000.0
    for day in range(days):
        etf = etf_sign * (20_000_000 + (day % 11) * 3_000_000 + day * 500_000)
        stable += stable_sign * (80_000_000 + (day % 7) * 2_000_000)
        reserve += exchange_sign * (30 + day % 5)
        rows.append(row("etf", "net_flow_usd", etf, day, "USD"))
        rows.append(row("stablecoin", "supply_usd", stable, day, "USD"))
        rows.append(row("exchange_btc", "reserve_btc", reserve, day, "BTC", attr=0.8))
    return rows


class SemanticAuditTests(unittest.TestCase):
    def test_source_contracts_are_fully_documented(self):
        self.assertGreaterEqual(len(SOURCE_CONTRACTS), 3)
        for contract in SOURCE_CONTRACTS:
            payload = contract.to_dict()
            for key in (
                "units", "update_cadence", "historical_depth", "availability_rule",
                "revision_behavior", "rate_limits", "access_limits", "missing_periods",
                "attribution_assumptions", "storage_license_notes", "fallback_behavior",
            ):
                self.assertTrue(payload[key])

    def test_accumulation_biased_semantics(self):
        rows = synthetic(etf_sign=1, stable_sign=1, exchange_sign=-1)
        as_of = BASE + 69 * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertTrue(frame.known)
        self.assertGreater(frame.capital_inflow_score or 0, 0)
        self.assertLess(frame.btc_to_liquid_venues_score or 0, 0)
        self.assertEqual(frame.flow_state, "ACCUMULATION_BIASED")

    def test_distribution_biased_semantics(self):
        rows = synthetic(etf_sign=-1, stable_sign=-1, exchange_sign=1)
        as_of = BASE + 69 * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertTrue(frame.known)
        self.assertLess(frame.capital_inflow_score or 0, 0)
        self.assertGreater(frame.btc_to_liquid_venues_score or 0, 0)
        self.assertEqual(frame.flow_state, "DISTRIBUTION_BIASED")

    def test_mixed_semantics_preserves_conflict(self):
        rows = synthetic(etf_sign=1, stable_sign=1, exchange_sign=1)
        as_of = BASE + 69 * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertTrue(frame.known)
        self.assertGreater(frame.capital_inflow_score or 0, 0)
        self.assertGreater(frame.btc_to_liquid_venues_score or 0, 0)
        self.assertEqual(frame.flow_state, "MIXED")
        self.assertGreater(frame.family_conflict or 0, 0)

    def test_unattributed_large_transfer_is_not_automatically_whale_selling(self):
        rows = synthetic()
        day = 69
        large_unknown = row("whale_lth", "large_transfer_btc", 25_000, day, "BTC", attr=0.1)
        as_of = BASE + day * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows + [large_unknown], as_of_ms=as_of)
        self.assertIsNone(frame.family_scores["whale_lth"])

    def test_reversal_detected_after_sustained_opposite_flow(self):
        rows = []
        for day in range(20):
            value = 10_000_000 + day * 100_000
            if day == 19:
                value = -80_000_000
            rows.append(row("etf", "net_flow_usd", value, day, "USD"))
        as_of = BASE + 19 * DAY + 12 * HOUR
        feature = build_metric_feature("etf", FAMILY_METRICS["etf"][0], rows, as_of, "24h")
        self.assertEqual(feature.reversal_state, "REVERSAL")
        self.assertLess(feature.current_value or 0, 0)

    def test_stale_core_source_marks_output_unknown(self):
        rows = synthetic(days=70)
        as_of = BASE + 80 * DAY
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertFalse(frame.known)
        self.assertEqual(frame.flow_state, "UNKNOWN")
        self.assertIn("STALE_CORE_SOURCES", frame.unknown_reasons)

    def test_runner_no_network_writes_compact_and_audit_files(self):
        rows = synthetic(days=70)
        with tempfile.TemporaryDirectory() as tmp:
            external = Path(tmp) / "external.jsonl"
            external.write_text("".join(json.dumps(item.to_dict()) + "\n" for item in rows), encoding="utf-8")
            local = Path(tmp) / "local"
            as_of = BASE + 69 * DAY + 12 * HOUR
            result = run_once(local_dir=local, external_jsonl=[external], network=False, as_of_ms=as_of)
            self.assertTrue((local / "observations.jsonl").exists())
            self.assertTrue((local / "latest.json").exists())
            self.assertTrue((local / "audit_latest.json").exists())
            self.assertEqual(result["output"]["schema_version"], "cf-output-v1")


if __name__ == "__main__":
    unittest.main()
