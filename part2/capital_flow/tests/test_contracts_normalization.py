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


if __name__ == "__main__":
    unittest.main()
