from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.evidence_health import build_evidence_health
from part2.capital_flow.runner import run_once


class CapitalFlowEvidenceHealthTests(unittest.TestCase):
    def _obs(self, *, family: str = "exchange_btc", observed_at: int = 2_000_000, available_at: int | None = 1_900_000, effective_at: int = 1_800_000, context_only: bool = False) -> FlowObservation:
        return FlowObservation(family=family, metric="btc_netflow" if family == "exchange_btc" else "net_flow_usd", asset="BTC" if family == "exchange_btc" else "USD", value=12.0, unit="BTC" if family == "exchange_btc" else "USD", effective_at_ms=effective_at, available_at_ms=available_at, observed_at_ms=observed_at, source="fixture_source", source_record_id=f"{family}:{effective_at}", cadence_seconds=300, provenance={"context_only": context_only})

    def test_family_health_preserves_three_clocks_and_missingness(self) -> None:
        health = build_evidence_health([self._obs()], as_of_ms=2_100_000)
        family = health["families"]["exchange_btc"]
        self.assertEqual(family["latest_effective_at_ms"], 1_800_000)
        self.assertEqual(family["latest_available_at_ms"], 1_900_000)
        self.assertEqual(family["latest_observed_at_ms"], 2_000_000)
        self.assertEqual(family["effective_age_seconds"], 300.0)
        self.assertEqual(family["availability_age_seconds"], 200.0)
        self.assertEqual(family["observation_age_seconds"], 100.0)
        self.assertFalse(family["missing"])
        self.assertTrue(health["families"]["miner"]["missing"])

    def test_future_or_not_yet_available_rows_are_not_visible(self) -> None:
        future = self._obs(observed_at=2_200_000, available_at=2_200_000)
        health = build_evidence_health([future], as_of_ms=2_100_000)
        self.assertTrue(health["families"]["exchange_btc"]["missing"])

    def test_context_only_evidence_is_not_scoring_support(self) -> None:
        health = build_evidence_health([self._obs(family="whale_lth", context_only=True)], as_of_ms=2_100_000)
        family = health["families"]["whale_lth"]
        self.assertFalse(family["missing"])
        self.assertTrue(family["scoring_missing"])

    def test_context_only_does_not_refresh_scoring_freshness(self) -> None:
        scoring = self._obs(
            observed_at=1_600_000,
            available_at=1_500_000,
            effective_at=1_400_000,
            context_only=False,
        )
        context = self._obs(
            observed_at=2_050_000,
            available_at=2_040_000,
            effective_at=2_030_000,
            context_only=True,
        )
        health = build_evidence_health([scoring, context], as_of_ms=2_100_000)
        family = health["families"]["exchange_btc"]

        assert family["latest_effective_at_ms"] == 2_030_000
        assert family["effective_age_seconds"] == 70.0
        assert family["scoring_latest_effective_at_ms"] == 1_400_000
        assert family["scoring_effective_age_seconds"] == 700.0
        assert family["scoring_latest_available_at_ms"] == 1_500_000
        assert family["scoring_availability_age_seconds"] == 600.0
        assert family["scoring_latest_observed_at_ms"] == 1_600_000
        assert family["scoring_observation_age_seconds"] == 500.0
        assert health["semantics"]["context_only_does_not_refresh_scoring_freshness"] is True

    def test_collection_attempts_separate_transport_health_from_economic_freshness(self) -> None:
        health = build_evidence_health([self._obs()], as_of_ms=2_100_000, source_errors=["kote: TimeoutError: timed out"], collection_attempts=[{"collector": "farside_etf", "status": "OK", "attempted_at_ms": 2_100_000, "observation_count": 1, "error_count": 0}, {"collector": "kote", "status": "FAILED", "attempted_at_ms": 2_100_000, "observation_count": 0, "error_count": 1}])
        collection = health["collection"]
        self.assertTrue(collection["attempted"])
        self.assertEqual(collection["successful_collectors"], ["farside_etf"])
        self.assertEqual(collection["failed_or_partial_collectors"], ["kote"])
        self.assertEqual(collection["attempts"][0]["attempt_age_seconds"], 0.0)
        self.assertEqual(health["families"]["exchange_btc"]["effective_age_seconds"], 300.0)
        self.assertTrue(health["semantics"]["collector_success_does_not_imply_fresh_economic_data"])

    def test_no_network_run_does_not_claim_collection_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_once(local_dir=Path(tmp), network=False, as_of_ms=2_100_000)
            health = result["anata_output"]["evidence_health"]
            self.assertEqual(health["schema_version"], "cf-evidence-health-v2")
            self.assertFalse(health["collection"]["attempted"])
            self.assertEqual(health["collection"]["successful_collectors"], [])
            self.assertEqual(result["collection_attempts"], [])
            self.assertTrue(all(item["missing"] for item in health["families"].values()))


if __name__ == "__main__":
    unittest.main()
