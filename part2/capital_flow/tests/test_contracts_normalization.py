from __future__ import annotations

import unittest

from part2.capital_flow.contracts import FlowObservation, point_in_time_filter
from part2.capital_flow.normalization import normalize_and_dedup, normalize_observation, select_latest_revisions

DAY = 86_400_000


def obs(**overrides):
    base = dict(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=10.0,
        unit="USD_MILLIONS",
        effective_at_ms=DAY,
        available_at_ms=DAY + 1000,
        observed_at_ms=DAY + 2000,
        source="test",
        source_record_id="row-1",
        revision="1",
        cadence_seconds=86400,
        attribution_status="DIRECT",
        attribution_quality=1.0,
        data_quality=0.9,
    )
    base.update(overrides)
    return FlowObservation(**base)


class ContractNormalizationTests(unittest.TestCase):
    def test_unknown_availability_is_not_visible(self):
        unknown = obs(available_at_ms=None)
        self.assertEqual(point_in_time_filter([unknown], DAY * 10), [])

    def test_available_after_replay_cutoff_is_not_visible(self):
        future = obs(available_at_ms=DAY * 3, observed_at_ms=DAY * 3)
        self.assertEqual(point_in_time_filter([future], DAY * 2), [])

    def test_usd_millions_normalizes_to_usd(self):
        normalized = normalize_observation(obs(value=-12.5))
        self.assertEqual(normalized.unit, "USD")
        self.assertEqual(normalized.value, -12_500_000.0)

    def test_revision_selection_is_point_in_time_safe(self):
        original = obs(value=10, revision="1", available_at_ms=DAY + 1000, observed_at_ms=DAY + 1000)
        revised = obs(value=99, revision="2", available_at_ms=DAY * 2, observed_at_ms=DAY * 2)
        early = point_in_time_filter([original, revised], DAY + 5000)
        chosen_early = select_latest_revisions(early)
        self.assertEqual(len(chosen_early), 1)
        self.assertEqual(chosen_early[0].value, 10)
        late = point_in_time_filter([original, revised], DAY * 3)
        chosen_late = select_latest_revisions(late)
        self.assertEqual(chosen_late[0].value, 99)

    def test_revision_numeric_ordering_r9_vs_r10(self):
        t1 = DAY + 1000
        t2 = DAY + 2000
        r9 = obs(
            source="src",
            source_record_id="rec-1",
            revision="r9",
            value=9.0,
            available_at_ms=t1,
            observed_at_ms=t1,
        )
        r10 = obs(
            source="src",
            source_record_id="rec-1",
            revision="r10",
            value=10.0,
            available_at_ms=t2,
            observed_at_ms=t2,
        )

        # At as_of between t1 and t2, only r9 is visible.
        filtered_early = point_in_time_filter([r9, r10], t1 + 500)
        chosen_early = select_latest_revisions(filtered_early)
        self.assertEqual(len(chosen_early), 1)
        self.assertEqual(chosen_early[0].revision, "r9")
        self.assertEqual(chosen_early[0].value, 9.0)

        # At as_of after t2, r10 wins regardless of input order [r9, r10] vs [r10, r9].
        for input_list in ([r9, r10], [r10, r9]):
            filtered_late = point_in_time_filter(input_list, t2 + 500)
            chosen_late = select_latest_revisions(filtered_late)
            self.assertEqual(len(chosen_late), 1)
            self.assertEqual(chosen_late[0].revision, "r10")
            self.assertEqual(chosen_late[0].value, 10.0)

    def test_same_clock_revision_alias_determinism_r1_vs_r01(self):
        t1 = DAY + 1000
        obs_r1 = obs(
            source="src",
            source_record_id="rec-alias",
            family="etf",
            metric="net_flow_usd",
            revision="r1",
            value=11.1,
            available_at_ms=t1,
            observed_at_ms=t1,
            provenance={"token": "r1"},
        )
        obs_r01 = obs(
            source="src",
            source_record_id="rec-alias",
            family="etf",
            metric="net_flow_usd",
            revision="r01",
            value=22.2,
            available_at_ms=t1,
            observed_at_ms=t1,
            provenance={"token": "r01"},
        )
        for input_permutation in ([obs_r1, obs_r01], [obs_r01, obs_r1]):
            chosen = select_latest_revisions(input_permutation)
            self.assertEqual(len(chosen), 1)
            winner = chosen[0]
            self.assertEqual(winner.revision, "r1")
            self.assertEqual(winner.provenance, {"token": "r1"})

    def test_same_clock_tie_behavior_and_separate_records(self):
        t1 = DAY + 1000
        obs_a = obs(source="src", source_record_id="rec-1", revision="1", value=1.0, available_at_ms=t1, observed_at_ms=t1)
        obs_b = obs(source="src", source_record_id="rec-1", revision="2", value=2.0, available_at_ms=t1, observed_at_ms=t1)
        # Same-clock tie-breaking: revision 2 vs 1
        chosen_tie = select_latest_revisions([obs_a, obs_b])
        self.assertEqual(len(chosen_tie), 1)
        self.assertEqual(chosen_tie[0].revision, "2")
        self.assertEqual(chosen_tie[0].value, 2.0)

        # Separate source_record_id are not collapsed
        obs_c = obs(source="src", source_record_id="rec-2", revision="1", value=3.0, available_at_ms=t1, observed_at_ms=t1)
        chosen_separate = select_latest_revisions([obs_a, obs_c])
        self.assertEqual(len(chosen_separate), 2)
        values = {o.value for o in chosen_separate}
        self.assertEqual(values, {1.0, 3.0})

    def test_same_clock_conflicting_same_record_revisions_permutation_and_flags(self):
        t1 = DAY + 1000
        obs_1 = obs(
            source="src",
            source_record_id="rec",
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            revision="1",
            available_at_ms=t1,
            observed_at_ms=t1,
            value=100.0,
            provenance={"tag": "one"},
        )
        obs_2 = obs(
            source="src",
            source_record_id="rec",
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            revision="1",
            available_at_ms=t1,
            observed_at_ms=t1,
            value=200.0,
            provenance={"tag": "two"},
        )
        for permutation in ([obs_1, obs_2], [obs_2, obs_1]):
            chosen = select_latest_revisions(permutation)
            self.assertEqual(len(chosen), 1)
            winner = chosen[0]
            # Winner is deterministic (based on observation_id / value sorting)
            expected_winner_value = min(obs_1.value, obs_2.value)
            self.assertEqual(winner.value, expected_winner_value)
            self.assertIn("CONFLICTING_EQUAL_RANK_VALUES", winner.quality_flags)
            self.assertTrue(winner.provenance)

    def test_same_clock_identical_duplicates_no_conflict_marker(self):
        t1 = DAY + 1000
        obs_1 = obs(
            source="src",
            source_record_id="rec-dup",
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            revision="1",
            available_at_ms=t1,
            observed_at_ms=t1,
            value=100.0,
        )
        obs_2 = obs(
            source="src",
            source_record_id="rec-dup",
            family="etf",
            metric="net_flow_usd",
            asset="BTC",
            revision="1",
            available_at_ms=t1,
            observed_at_ms=t1,
            value=100.0,
        )
        chosen = select_latest_revisions([obs_1, obs_2])
        self.assertEqual(len(chosen), 1)
        winner = chosen[0]
        self.assertEqual(winner.value, 100.0)
        self.assertNotIn("CONFLICTING_EQUAL_RANK_VALUES", winner.quality_flags)

    def test_later_available_correction_wins(self):
        t1 = DAY + 1000
        t2 = DAY + 2000
        obs_early = obs(
            source="src",
            source_record_id="rec-corr",
            revision="1",
            available_at_ms=t1,
            observed_at_ms=t1,
            value=100.0,
        )
        obs_late = obs(
            source="src",
            source_record_id="rec-corr",
            revision="1",
            available_at_ms=t2,
            observed_at_ms=t2,
            value=300.0,
        )
        for permutation in ([obs_early, obs_late], [obs_late, obs_early]):
            chosen = select_latest_revisions(permutation)
            self.assertEqual(len(chosen), 1)
            self.assertEqual(chosen[0].value, 300.0)
            self.assertNotIn("CONFLICTING_EQUAL_RANK_VALUES", chosen[0].quality_flags)

    def test_btc_and_eth_same_source_record_identity_survive_normalize_and_dedup(self):
        t1 = DAY + 1000
        t2 = DAY + 2000

        # Early revision for both BTC and ETH sharing same source/source_record_id/family/metric
        btc_r1 = obs(asset="BTC", source="multi-asset-src", source_record_id="rec-shared-99", revision="1", value=100.0, unit="USD", available_at_ms=t1, observed_at_ms=t1)
        eth_r1 = obs(asset="ETH", source="multi-asset-src", source_record_id="rec-shared-99", revision="1", value=200.0, unit="USD", available_at_ms=t1, observed_at_ms=t1)

        # Later revision for BTC only, sharing the exact same source record identity
        btc_r2 = obs(asset="BTC", source="multi-asset-src", source_record_id="rec-shared-99", revision="2", value=150.0, unit="USD", available_at_ms=t2, observed_at_ms=t2)

        for input_order in (
            [btc_r1, eth_r1, btc_r2],
            [btc_r2, eth_r1, btc_r1],
            [eth_r1, btc_r1, btc_r2],
        ):
            # At as_of after t2, btc_r2 replaces btc_r1, while eth_r1 survives distinctly.
            filtered = point_in_time_filter(input_order, t2 + 500)
            kept, _ = normalize_and_dedup(filtered)
            self.assertEqual(len(kept), 2)

            assets_and_values = {(o.asset, o.value) for o in kept}
            self.assertEqual(assets_and_values, {("BTC", 150.0), ("ETH", 200.0)})

    def test_explicit_cross_provider_economic_duplicate_is_suppressed(self):
        a = obs(source="a", source_record_id="a1", economic_event_id="event-x", data_quality=0.8)
        b = obs(source="b", source_record_id="b1", economic_event_id="event-x", data_quality=0.95)
        kept, decisions = normalize_and_dedup([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].source, "b")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["reason"], "DUPLICATE_ECONOMIC_EVENT")

    def test_missing_without_economic_event_is_not_guessed_duplicate(self):
        a = obs(source="a", source_record_id="a1", economic_event_id=None)
        b = obs(source="b", source_record_id="b1", economic_event_id=None)
        kept, decisions = normalize_and_dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(decisions, [])

    def test_distinct_assets_same_event_id_survive_and_same_asset_resolves(self):
        btc_a = obs(asset="BTC", source="prov-1", source_record_id="rec-btc-1", economic_event_id="shared-event-123", data_quality=0.9)
        btc_b = obs(asset="BTC", source="prov-2", source_record_id="rec-btc-2", economic_event_id="shared-event-123", data_quality=0.9)
        eth = obs(asset="ETH", source="prov-1", source_record_id="rec-eth-1", economic_event_id="shared-event-123", data_quality=0.9)

        for input_order in (
            [btc_a, btc_b, eth],
            [eth, btc_b, btc_a],
            [btc_b, btc_a, eth],
        ):
            kept, decisions = normalize_and_dedup(input_order)
            assets = {o.asset for o in kept}
            self.assertEqual(assets, {"BTC", "ETH"})
            self.assertEqual(len(kept), 2)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0]["economic_event_id"], "shared-event-123")

    def test_cross_provider_equal_rank_determinism_and_controls(self):
        t1 = DAY + 1000
        obs_prov_alpha = obs(
            source="alpha_provider",
            source_record_id="rec-alpha-100",
            economic_event_id="event-shared-999",
            data_quality=0.9,
            attribution_quality=0.95,
            observed_at_ms=t1,
            value=10.0,
            unit="USD_MILLIONS",
            provenance={"collector": "alpha"},
        )
        obs_prov_beta = obs(
            source="beta_provider",
            source_record_id="rec-beta-200",
            economic_event_id="event-shared-999",
            data_quality=0.9,
            attribution_quality=0.95,
            observed_at_ms=t1,
            value=20.0,
            unit="USD_MILLIONS",
            provenance={"collector": "beta"},
        )

        kept_set_1, decisions_1 = normalize_and_dedup([obs_prov_alpha, obs_prov_beta])
        kept_set_2, decisions_2 = normalize_and_dedup([obs_prov_beta, obs_prov_alpha])

        self.assertEqual(len(kept_set_1), 1)
        self.assertEqual(len(kept_set_2), 1)
        self.assertEqual(kept_set_1[0].source, kept_set_2[0].source)
        self.assertEqual(kept_set_1[0].value, kept_set_2[0].value)
        self.assertEqual(kept_set_1[0].provenance, kept_set_2[0].provenance)
        self.assertEqual(decisions_1, decisions_2)
        self.assertEqual(len(decisions_1), 1)
        self.assertEqual(decisions_1[0]["reason"], "DUPLICATE_ECONOMIC_EVENT")

        obs_low_q = obs(
            source="beta_provider",
            source_record_id="rec-beta-200",
            economic_event_id="event-shared-999",
            data_quality=0.7,
            attribution_quality=0.95,
            observed_at_ms=t1,
            value=20.0,
            unit="USD_MILLIONS",
        )
        kept_unequal, _ = normalize_and_dedup([obs_low_q, obs_prov_alpha])
        self.assertEqual(len(kept_unequal), 1)
        self.assertEqual(kept_unequal[0].source, "alpha_provider")
        self.assertEqual(kept_unequal[0].value, 10_000_000.0)

        obs_event_one = obs(
            source="alpha_provider",
            source_record_id="rec-1",
            economic_event_id="event-1",
            data_quality=0.9,
            observed_at_ms=t1,
            value=10.0,
            unit="USD_MILLIONS",
        )
        obs_event_two = obs(
            source="alpha_provider",
            source_record_id="rec-2",
            economic_event_id="event-2",
            data_quality=0.9,
            observed_at_ms=t1,
            value=15.0,
            unit="USD_MILLIONS",
        )
        kept_events, _ = normalize_and_dedup([obs_event_one, obs_event_two])
        self.assertEqual(len(kept_events), 2)

        obs_no_event_1 = obs(
            source="alpha_provider",
            source_record_id="rec-alpha-100",
            economic_event_id=None,
            data_quality=0.9,
            observed_at_ms=t1,
            value=10.0,
            unit="USD_MILLIONS",
        )
        obs_no_event_2 = obs(
            source="beta_provider",
            source_record_id="rec-beta-200",
            economic_event_id=None,
            data_quality=0.9,
            observed_at_ms=t1,
            value=20.0,
            unit="USD_MILLIONS",
        )
        kept_missing, decisions_missing = normalize_and_dedup([obs_no_event_1, obs_no_event_2])
        self.assertEqual(len(kept_missing), 2)
        self.assertEqual(decisions_missing, [])


if __name__ == "__main__":
    unittest.main()
