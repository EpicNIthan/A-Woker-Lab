from __future__ import annotations

from types import SimpleNamespace
import unittest

from part2.capital_flow.contracts import FAMILIES, FlowObservation
from part2.capital_flow.handoff import _family_support, _source_evidence, build_anata_handoff


class HandoffContextRoleParityTests(unittest.TestCase):
    def _dummy_frame(self, as_of_ms: int = 1_787_520_123_456):
        family_states = {
            family: {
                "24h": SimpleNamespace(known=False),
            }
            for family in FAMILIES
        }
        return SimpleNamespace(
            as_of_ms=as_of_ms,
            family_states=family_states,
            family_scores={f: None for f in FAMILIES},
            horizon_axes={},
            capital_inflow_score=None,
            btc_to_liquid_venues_score=None,
            holder_accumulation_score=None,
            flow_state="NEUTRAL",
            flow_strength=0.0,
            flow_change=0.0,
            flow_persistence=0.0,
            family_agreement=1.0,
            source_agreement=1.0,
            evidence_independence=1.0,
            coverage=0.0,
            data_quality=1.0,
            freshness=1.0,
            attribution_quality=None,
            flow_clarity=1.0,
            known=False,
            unknown_reasons=(),
            audit_flags=(),
        )

    def test_nonnegotiable_truth_table_context_role_mapping(self):
        as_of = 1_787_520_123_456
        cases = [
            ({}, False),
            ({"context_only": False}, False),
            ({"context_only": True}, True),
            ({"context_only": " false "}, False),
            ({"context_only": "TRUE"}, True),
            ({"context_only": "maybe"}, True),
            ({"context_only": None}, True),
            ({"context_only": ""}, True),
            ({"context_only": []}, True),
        ]

        for idx, (prov, expected_context_only) in enumerate(cases):
            with self.subTest(prov=prov, expected=expected_context_only):
                obs = FlowObservation(
                    family="etf",
                    metric="etf_netflow_btc",
                    asset="BTC",
                    value=10.0,
                    unit="BTC",
                    effective_at_ms=as_of - 10_000,
                    available_at_ms=as_of,
                    observed_at_ms=as_of,
                    source="test_source",
                    source_record_id=f"rec:{idx}",
                    cadence_seconds=3600,
                    provenance=prov,
                )
                frame = self._dummy_frame(as_of_ms=as_of)
                normalized = [obs]
                
                fam_support = _family_support(frame, normalized, as_of_ms=as_of)
                etf_sup = fam_support["etf"]
                sources = _source_evidence(normalized, as_of_ms=as_of)
                self.assertEqual(len(sources), 1)
                assigned_role = sources[0]["role"]

                if expected_context_only:
                    self.assertEqual(assigned_role, "context")
                    self.assertEqual(etf_sup["context_observation_count"], 1)
                    self.assertEqual(etf_sup["scoring_observation_count"], 0)
                else:
                    self.assertEqual(assigned_role, "scoring")
                    self.assertEqual(etf_sup["context_observation_count"], 0)
                    self.assertEqual(etf_sup["scoring_observation_count"], 1)

    def test_build_anata_handoff_with_mixed_roles_and_causal_clocks(self):
        as_of = 1_787_520_123_456
        obs_scoring = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=15.0,
            unit="BTC",
            effective_at_ms=as_of - 20_000,
            available_at_ms=as_of - 10_000,
            observed_at_ms=as_of - 5_000,
            source="glassnode",
            source_record_id="score_1",
            cadence_seconds=3600,
            provenance={"context_only": False},
        )
        obs_context = FlowObservation(
            family="exchange_btc",
            metric="btc_netflow",
            asset="BTC",
            value=99.0,
            unit="BTC",
            effective_at_ms=as_of - 10_000,
            available_at_ms=as_of,
            observed_at_ms=as_of,
            source="glassnode",
            source_record_id="context_1",
            cadence_seconds=3600,
            provenance={"context_only": "maybe"},
        )
        frame = self._dummy_frame(as_of_ms=as_of)
        handoff = build_anata_handoff(frame, [obs_scoring, obs_context], source_errors=[])

        exc_family = handoff["families"]["exchange_btc"]
        self.assertEqual(exc_family["scoring_observation_count"], 1)
        self.assertEqual(exc_family["context_observation_count"], 1)
        self.assertEqual(exc_family["observation_count"], 2)

        sources = handoff["source_evidence"]
        self.assertEqual(len(sources), 2)
        roles = {s["role"] for s in sources}
        self.assertEqual(roles, {"scoring", "context"})

        scoring_src = next(s for s in sources if s["role"] == "scoring")
        self.assertEqual(scoring_src["clock_provenance"]["effective"]["source_record_id"], "score_1")


if __name__ == "__main ప్రధాన__" or __name__ == "__main__":
    unittest.main()
