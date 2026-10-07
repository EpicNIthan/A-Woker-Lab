from __future__ import annotations

from types import SimpleNamespace
import unittest

from part2.capital_flow.contracts import FAMILIES, FlowObservation
from part2.capital_flow.handoff import build_anata_handoff, build_stablecoin_context
from part2.capital_flow.providers_v1 import (
    DefiLlamaStablecoinCompositionCollector,
    GlassnodeMetricConfig,
    GlassnodePitCollector,
    validate_glassnode_metadata,
)
from part2.capital_flow.runner import _scoring_history


class CapitalFlowV1Tests(unittest.TestCase):
    def test_defillama_component_snapshot_preserves_missing_and_changes(self) -> None:
        payload = {
            "peggedAssets": [
                {
                    "id": "2",
                    "symbol": "USDT",
                    "pegType": "peggedUSD",
                    "pegMechanism": "fiat-backed",
                    "price": 1.0001,
                    "circulating": {"peggedUSD": 1000.0},
                    "circulatingPrevDay": {"peggedUSD": 900.0},
                    "circulatingPrevWeek": {"peggedUSD": 800.0},
                    "circulatingPrevMonth": {"peggedUSD": 700.0},
                },
                {
                    "id": "1",
                    "symbol": "USDC",
                    "pegType": "peggedUSD",
                    "pegMechanism": "fiat-backed",
                    "price": 0.9999,
                    "circulating": {"peggedUSD": 500.0},
                    "circulatingPrevDay": {"peggedUSD": 525.0},
                    "circulatingPrevWeek": {"peggedUSD": 510.0},
                },
            ]
        }
        observed = 1_787_520_123_456
        observations = DefiLlamaStablecoinCompositionCollector.parse_payload(
            payload,
            observed_at_ms=observed,
            symbols=("USDT", "USDC", "DAI"),
        )
        self.assertTrue(observations)
        self.assertTrue(all(obs.available_at_ms == observed for obs in observations))
        self.assertTrue(
            all(obs.effective_at_ms == (observed // 86_400_000) * 86_400_000 for obs in observations)
        )

        context = build_stablecoin_context(observations, as_of_ms=observed)
        self.assertTrue(context["known"])
        self.assertEqual(context["tracked_component_count"], 2)
        self.assertEqual(context["tracked_supply_usd"], 1500.0)
        self.assertEqual(context["tracked_change_1d_usd"], 75.0)
        self.assertAlmostEqual(context["composition_hhi"], (2 / 3) ** 2 + (1 / 3) ** 2)
        self.assertAlmostEqual(context["top_component_share"], 2 / 3)
        self.assertEqual(context["top_two_component_share"], 1.0)
        self.assertEqual(context["peg_price_coverage"], 1.0)
        self.assertAlmostEqual(context["weighted_abs_peg_deviation_bps"], 1.0)
        self.assertAlmostEqual(context["max_abs_peg_deviation_bps"], 1.0)
        self.assertEqual(context["change_coverage"]["1d"], 1.0)
        self.assertEqual(context["change_coverage"]["30d"], 0.5)
        self.assertIn("COMPONENT_CONTEXT_EXCLUDED_FROM_FROZEN_SCORING", context["quality_flags"])

        usdc = next(item for item in context["components"] if item["symbol"] == "USDC")
        self.assertIsNone(usdc["change_30d_usd"])
        self.assertIn("change_30d_usd", usdc["missing_fields"])
        self.assertAlmostEqual(usdc["supply_share_of_tracked"], 1 / 3)
        self.assertAlmostEqual(usdc["peg_deviation_bps"], -1.0)
        self.assertGreaterEqual(usdc["economic_age_ms"], 0)
        self.assertEqual(usdc["availability_age_ms"], 0)
        self.assertEqual(_scoring_history(observations), [])

    def test_stablecoin_context_preserves_partial_price_and_change_coverage(self) -> None:
        observed = 1_787_520_123_456
        payload = {
            "peggedAssets": [
                {
                    "id": "2", "symbol": "USDT",
                    "circulating": {"peggedUSD": 1000.0},
                    "circulatingPrevDay": {"peggedUSD": 990.0},
                    "price": 0.999,
                },
                {
                    "id": "1", "symbol": "USDC",
                    "circulating": {"peggedUSD": 500.0},
                },
            ]
        }
        observations = DefiLlamaStablecoinCompositionCollector.parse_payload(
            payload, observed_at_ms=observed, symbols=("USDT", "USDC")
        )
        context = build_stablecoin_context(observations, as_of_ms=observed)
        self.assertEqual(context["peg_price_coverage"], 0.5)
        self.assertEqual(context["change_coverage"]["1d"], 0.5)
        self.assertEqual(context["change_coverage"]["7d"], 0.0)
        self.assertAlmostEqual(context["weighted_abs_peg_deviation_bps"], 10.0)
        usdc = next(item for item in context["components"] if item["symbol"] == "USDC")
        self.assertIsNone(usdc["peg_deviation_bps"])
        self.assertIn("price_usd", usdc["missing_fields"])

    def test_glassnode_metadata_must_be_explicit_pit(self) -> None:
        validate_glassnode_metadata({"is_pit": True}, metric_path="/v1/metrics/test")
        with self.assertRaises(ValueError):
            validate_glassnode_metadata({"is_pit": False}, metric_path="/v1/metrics/test")
        with self.assertRaises(ValueError):
            validate_glassnode_metadata({}, metric_path="/v1/metrics/test")

    def test_glassnode_parser_bootstrap_never_claims_old_availability(self) -> None:
        config = GlassnodeMetricConfig(
            path="/v1/metrics/test",
            family="exchange_btc",
            metric="btc_netflow",
            unit="BTC",
            cadence_seconds=3600,
        )
        observed = 1_787_520_123_456
        rows = [{"t": 1_787_000_000, "v": 10.0}, {"t": 1_787_003_600, "v": -5.0}]
        observations = GlassnodePitCollector.parse_metric_payload(
            rows,
            config=config,
            observed_at_ms=observed,
            include_backfill=True,
        )
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(obs.available_at_ms == observed for obs in observations))
        self.assertIn(
            "NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY",
            observations[0].quality_flags,
        )
        self.assertEqual(_scoring_history(observations), observations)

    def _frame(self):
        family_states = {
            family: {
                "24h": SimpleNamespace(known=(family in {"etf", "stablecoin"})),
                "7d": SimpleNamespace(known=(family in {"etf", "stablecoin"})),
            }
            for family in FAMILIES
        }
        return SimpleNamespace(
            as_of_ms=1_787_520_123_456,
            family_states=family_states,
            family_scores={
                "etf": 0.8,
                "exchange_btc": None,
                "stablecoin": 0.5,
                "whale_lth": None,
                "miner": None,
                "treasury": None,
            },
            horizon_axes={
                "24h": {
                    "capital_inflow_score": 0.4,
                    "btc_to_liquid_venues_score": None,
                    "holder_accumulation_score": None,
                    "flow_strength": 0.4,
                },
                "7d": {
                    "capital_inflow_score": 0.7,
                    "btc_to_liquid_venues_score": None,
                    "holder_accumulation_score": None,
                    "flow_strength": 0.7,
                },
            },
            capital_inflow_score=0.7,
            btc_to_liquid_venues_score=None,
            holder_accumulation_score=None,
            flow_state="ACCUMULATION_BIASED",
            flow_strength=0.65,
            flow_change=0.1,
            flow_persistence=0.8,
            family_agreement=1.0,
            source_agreement=1.0,
            evidence_independence=1.0,
            coverage=2 / 3,
            data_quality=0.9,
            freshness=0.8,
            attribution_quality=None,
            flow_clarity=0.85,
            known=True,
            unknown_reasons=(),
            audit_flags=("DEPENDENCE_ONLY_EXPLICIT",),
        )

    def test_anata_handoff_is_evidence_not_trade_output(self) -> None:
        handoff = build_anata_handoff(self._frame(), [], source_errors=[])
        self.assertEqual(handoff["schema_version"], "cf-anata-handoff-v1")
        self.assertTrue(handoff["semantics"]["evidence_only"])
        self.assertFalse(handoff["semantics"]["is_trade_signal"])
        self.assertFalse(handoff["semantics"]["is_price_forecast"])
        self.assertEqual(handoff["families"]["exchange_btc"]["status"], "MISSING")

        forbidden = {"buy", "sell", "leverage", "position_size", "confidence", "price_target"}

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).lower()
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        self.assertFalse(forbidden.intersection(set(keys(handoff))))

    def test_handoff_splits_context_only_from_scoring_support(self) -> None:
        observed = self._frame().as_of_ms
        scoring = FlowObservation(
            family="whale_lth",
            metric="holder_balance_btc",
            asset="BTC",
            value=10.0,
            unit="BTC",
            effective_at_ms=observed - 86_400_000,
            available_at_ms=observed,
            observed_at_ms=observed,
            source="kote_lth_supply",
            source_record_id="lth:1",
            cadence_seconds=86400,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.85,
        )
        context = FlowObservation(
            family="whale_lth",
            metric="holder_exchange_inflow_btc",
            asset="BTC",
            value=5.0,
            unit="BTC",
            effective_at_ms=observed - 86_400_000,
            available_at_ms=observed,
            observed_at_ms=observed,
            source="kote_whale_to_exchange",
            source_record_id="whale:1",
            cadence_seconds=86400,
            attribution_status="MEDIUM",
            attribution_quality=0.65,
            data_quality=0.78,
            provenance={"context_only": True},
        )

        handoff = build_anata_handoff(self._frame(), [scoring, context], source_errors=[])
        whale = handoff["families"]["whale_lth"]
        self.assertEqual(whale["status"], "OBSERVED_INSUFFICIENT_HISTORY")
        self.assertEqual(whale["observation_count"], 2)
        self.assertEqual(whale["source_count"], 2)
        self.assertEqual(whale["scoring_observation_count"], 1)
        self.assertEqual(whale["scoring_source_count"], 1)
        self.assertEqual(whale["context_observation_count"], 1)
        self.assertEqual(whale["context_source_count"], 1)
        self.assertTrue(whale["has_context_only_evidence"])

    def test_handoff_scoring_freshness_regression(self) -> None:
        as_of = self._frame().as_of_ms
        older_effective = as_of - 100_000
        older_available = as_of - 80_000
        older_observed = as_of - 60_000

        newer_effective = as_of - 10_000
        newer_available = as_of - 5_000
        newer_observed = as_of - 1_000

        scoring_obs = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=10.0,
            unit="BTC",
            effective_at_ms=older_effective,
            available_at_ms=older_available,
            observed_at_ms=older_observed,
            source="glassnode",
            source_record_id="score:1",
            cadence_seconds=3600,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.9,
            provenance={"context_only": False},
        )

        context_obs = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=20.0,
            unit="BTC",
            effective_at_ms=newer_effective,
            available_at_ms=newer_available,
            observed_at_ms=newer_observed,
            source="glassnode",
            source_record_id="context:1",
            cadence_seconds=3600,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.9,
            provenance={"context_only": True},
        )

        handoff = build_anata_handoff(self._frame(), [scoring_obs, context_obs], source_errors=[])
        exchange_family = handoff["families"]["exchange_btc"]

        self.assertEqual(exchange_family["observation_count"], 2)
        self.assertEqual(exchange_family["scoring_observation_count"], 1)
        self.assertEqual(exchange_family["context_observation_count"], 1)
        self.assertTrue(exchange_family["has_context_only_evidence"])

        self.assertEqual(exchange_family["scoring_latest_effective_at_ms"], older_effective)
        self.assertEqual(exchange_family["scoring_latest_available_at_ms"], older_available)
        self.assertEqual(exchange_family["scoring_latest_observed_at_ms"], older_observed)
        self.assertEqual(exchange_family["scoring_economic_age_ms"], as_of - older_effective)
        self.assertEqual(exchange_family["scoring_availability_age_ms"], as_of - older_available)
        self.assertEqual(exchange_family["scoring_collector_age_ms"], as_of - older_observed)

    def test_source_evidence_revision_freshness_independent_clocks(self) -> None:
        as_of = self._frame().as_of_ms

        # Row A: newer economic effective_at_ms, but older available/observed clocks.
        row_a = FlowObservation(
            family="etf",
            metric="etf_netflow_btc",
            asset="BTC",
            value=50.0,
            unit="BTC",
            effective_at_ms=as_of - 10_000,
            available_at_ms=as_of - 50_000,
            observed_at_ms=as_of - 40_000,
            source="glassnode",
            source_record_id="row:a",
            cadence_seconds=3600,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.9,
            provenance={"context_only": False},
        )

        # Row B: older-effective revision, but arrived/observed later (newer available/observed).
        row_b = FlowObservation(
            family="etf",
            metric="etf_netflow_btc",
            asset="BTC",
            value=45.0,
            unit="BTC",
            effective_at_ms=as_of - 200_000,
            available_at_ms=as_of - 5_000,
            observed_at_ms=as_of - 2_000,
            source="glassnode",
            source_record_id="row:b",
            cadence_seconds=3600,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.9,
            provenance={"context_only": False},
        )

        handoff = build_anata_handoff(self._frame(), [row_a, row_b], source_errors=[])
        sources = handoff["source_evidence"]
        scoring_source = next(s for s in sources if s["family"] == "etf" and s["role"] == "scoring")

        self.assertEqual(scoring_source["latest_effective_at_ms"], row_a.effective_at_ms)
        self.assertEqual(scoring_source["economic_age_ms"], as_of - row_a.effective_at_ms)
        self.assertEqual(scoring_source["latest_available_at_ms"], row_b.available_at_ms)
        self.assertEqual(scoring_source["availability_age_ms"], as_of - row_b.available_at_ms)
        self.assertEqual(scoring_source["latest_observed_at_ms"], row_b.observed_at_ms)
        self.assertEqual(scoring_source["collector_age_ms"], as_of - row_b.observed_at_ms)

    def test_context_only_family_remains_missing_for_scoring_availability(self) -> None:
        observed = self._frame().as_of_ms
        context = FlowObservation(
            family="treasury",
            metric="fund_custody_reserve_btc",
            asset="BTC",
            value=100.0,
            unit="BTC",
            effective_at_ms=observed - 86_400_000,
            available_at_ms=observed,
            observed_at_ms=observed,
            source="kote_fund_flows",
            source_record_id="fund:1",
            cadence_seconds=86400,
            attribution_status="MEDIUM",
            attribution_quality=0.6,
            data_quality=0.72,
            provenance={"context_only": True},
        )

        handoff = build_anata_handoff(self._frame(), [context], source_errors=[])
        treasury = handoff["families"]["treasury"]
        self.assertEqual(treasury["status"], "CONTEXT_ONLY")
        self.assertEqual(treasury["observation_count"], 1)
        self.assertEqual(treasury["scoring_observation_count"], 0)
        self.assertTrue(treasury["has_context_only_evidence"])
        self.assertIsNone(treasury["scoring_latest_effective_at_ms"])
        self.assertIsNone(treasury["scoring_latest_available_at_ms"])
        self.assertIsNone(treasury["scoring_latest_observed_at_ms"])
        self.assertIsNone(treasury["scoring_economic_age_ms"])
        self.assertIsNone(treasury["scoring_availability_age_ms"])
        self.assertIsNone(treasury["scoring_collector_age_ms"])
        self.assertIn("treasury", handoff["availability"]["missing_optional_families"])


if __name__ == "__main__":
    unittest.main()
