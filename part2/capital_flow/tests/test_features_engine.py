from __future__ import annotations

import unittest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.engine import CapitalFlowEngine
from part2.capital_flow.features import build_family_horizon_state, build_metric_feature, FAMILY_METRICS
from part2.capital_flow.output import CapitalFlowOutputBuilder

DAY = 86_400_000
HOUR = 3_600_000
BASE = 1_800_000_000_000


def make_obs(
    family: str,
    metric: str,
    value: float,
    day: int,
    *,
    unit: str,
    cadence_seconds: int = 86400,
    source: str | None = None,
    dependence_group: str | None = None,
    attribution_quality: float | None = None,
) -> FlowObservation:
    effective = BASE + day * DAY
    available = effective + HOUR
    return FlowObservation(
        family=family,
        metric=metric,
        asset="BTC" if family != "stablecoin" else "USD_STABLECOINS",
        value=value,
        unit=unit,
        effective_at_ms=effective,
        available_at_ms=available,
        observed_at_ms=available,
        source=source or f"test-{family}",
        source_record_id=f"{family}:{metric}:{day}",
        revision="1",
        cadence_seconds=cadence_seconds,
        attribution_status="HIGH" if attribution_quality is not None else "NOT_APPLICABLE",
        attribution_quality=attribution_quality,
        data_quality=0.95,
        dependence_group=dependence_group,
    )


def history(days: int = 65, *, shared_dependence: bool = False) -> list[FlowObservation]:
    rows: list[FlowObservation] = []
    stable_supply = 120_000_000_000.0
    exchange_reserve = 2_000_000.0
    for day in range(days):
        etf = (-1 if day % 9 == 0 else 1) * (50_000_000 + day * 1_000_000)
        rows.append(
            make_obs(
                "etf",
                "net_flow_usd",
                etf,
                day,
                unit="USD",
                dependence_group=("shared-event" if shared_dependence and day == days - 1 else f"etf:{day}"),
            )
        )
        stable_supply += 100_000_000 + day * 1_000_000
        rows.append(make_obs("stablecoin", "supply_usd", stable_supply, day, unit="USD"))
        exchange_reserve -= 50 + day
        rows.append(
            make_obs(
                "exchange_btc",
                "reserve_btc",
                exchange_reserve,
                day,
                unit="BTC",
                dependence_group=("shared-event" if shared_dependence and day == days - 1 else f"exchange:{day}"),
                attribution_quality=0.8,
            )
        )
    return rows


class FeatureEngineTests(unittest.TestCase):
    def test_daily_etf_does_not_fake_one_hour_horizon(self):
        rows = history(10)
        as_of = BASE + 9 * DAY + 12 * HOUR
        state = build_family_horizon_state("etf", rows, as_of, "1h")
        self.assertFalse(state.known)
        self.assertIn("SOURCE_CADENCE_TOO_SLOW_FOR_HORIZON", state.audit_flags)

    def test_stablecoin_level_change_works_without_forward_fill(self):
        rows = history(65)
        as_of = BASE + 64 * DAY + 12 * HOUR
        spec = FAMILY_METRICS["stablecoin"][1]
        feature = build_metric_feature("stablecoin", spec, rows, as_of, "7d")
        self.assertIsNotNone(feature.current_value)
        self.assertGreater(feature.current_value, 0)
        self.assertIsNotNone(feature.direction_score)

    def test_whale_exchange_inflow_is_consumed_as_holder_distribution_pressure(self):
        rows = [
            make_obs(
                "whale_lth",
                "holder_exchange_inflow_btc",
                100.0 + day * 10.0,
                day,
                unit="BTC",
                attribution_quality=0.65,
            )
            for day in range(40)
        ]
        as_of = BASE + 39 * DAY + 12 * HOUR
        state = build_family_horizon_state("whale_lth", rows, as_of, "24h")
        inflow = next(feature for feature in state.metric_features if feature.metric == "holder_exchange_inflow_btc")
        self.assertTrue(state.known)
        self.assertIsNotNone(inflow.current_value)
        self.assertLess(inflow.current_value, 0.0)
        self.assertIsNotNone(inflow.direction_score)
        self.assertLess(inflow.direction_score, 0.0)

    def test_future_available_record_does_not_change_earlier_state(self):
        rows = history(65)
        as_of = BASE + 64 * DAY + 12 * HOUR
        baseline = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        future = make_obs("etf", "net_flow_usd", -9_999_999_999, 66, unit="USD")
        with_future = CapitalFlowEngine().build(rows + [future], as_of_ms=as_of)
        self.assertEqual(baseline.family_scores, with_future.family_scores)
        self.assertEqual(baseline.flow_state, with_future.flow_state)

    def test_core_axes_remain_separate(self):
        rows = history(65)
        as_of = BASE + 64 * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertIsNotNone(frame.capital_inflow_score)
        self.assertIsNotNone(frame.btc_to_liquid_venues_score)
        self.assertNotEqual(
            frame.capital_inflow_score,
            frame.btc_to_liquid_venues_score,
            "capital liquidity and BTC supply-location axes must not collapse into one score",
        )

    def test_explicit_cross_family_dependence_reduces_independence(self):
        rows = history(65, shared_dependence=True)
        as_of = BASE + 64 * DAY + 12 * HOUR
        frame = CapitalFlowEngine().build(rows, as_of_ms=as_of)
        self.assertIsNotNone(frame.evidence_independence)
        self.assertLessEqual(frame.evidence_independence, 1.0)
        self.assertIn("DEPENDENCE_ONLY_EXPLICIT", frame.audit_flags)

    def test_missing_optional_families_are_null_not_zero(self):
        rows = history(65)
        as_of = BASE + 64 * DAY + 12 * HOUR
        output = CapitalFlowOutputBuilder().build(CapitalFlowEngine().build(rows, as_of_ms=as_of)).to_dict()
        self.assertIsNone(output["whale_flow"])
        self.assertIsNone(output["miner_flow"])
        self.assertIsNone(output["treasury_flow"])
        self.assertNotIn("confidence", output)

    def test_freshness_uses_effective_data_age_not_recent_reobservation_time(self):
        as_of = 20 * DAY
        old_but_reobserved = FlowObservation(
            family="etf", metric="net_flow_usd", asset="BTC", value=10, unit="USD",
            effective_at_ms=10 * DAY, available_at_ms=as_of, observed_at_ms=as_of,
            source="source", source_record_id="old", revision="r1", cadence_seconds=86400,
            attribution_status="DIRECT", attribution_quality=1.0,
        )
        frame = CapitalFlowEngine().build([old_but_reobserved], as_of_ms=as_of)
        self.assertIn("STALE_CORE_SOURCES", frame.unknown_reasons)
        self.assertEqual(frame.freshness, 0.0)

    def test_live_output_has_no_trade_or_forecast_fields(self):
        rows = history(65)
        as_of = BASE + 64 * DAY + 12 * HOUR
        output = CapitalFlowOutputBuilder().build(CapitalFlowEngine().build(rows, as_of_ms=as_of)).to_dict()
        forbidden = {"buy", "sell", "leverage", "position_size", "expected_return", "btc_direction", "confidence"}
        self.assertTrue(forbidden.isdisjoint(output.keys()))
        self.assertEqual(output["schema_version"], "cf-output-v1")


if __name__ == "__main__":
    unittest.main()
