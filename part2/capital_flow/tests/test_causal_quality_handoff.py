from types import SimpleNamespace

from part2.capital_flow.contracts import FAMILIES, FlowObservation
from part2.capital_flow.handoff import build_anata_handoff


def _frame(as_of_ms: int):
    states = {family: {"24h": SimpleNamespace(known=False)} for family in FAMILIES}
    return SimpleNamespace(
        as_of_ms=as_of_ms, family_states=states, family_scores={family: None for family in FAMILIES},
        horizon_axes={}, capital_inflow_score=None, btc_to_liquid_venues_score=None,
        holder_accumulation_score=None, flow_state="UNKNOWN", flow_strength=None, flow_change=None,
        flow_persistence=None, family_agreement=None, source_agreement=None, evidence_independence=None,
        coverage=0.0, data_quality=0.0, freshness=0.0, attribution_quality=None, flow_clarity=0.0,
        known=False, unknown_reasons=("INSUFFICIENT_COVERAGE",), audit_flags=(),
    )


def _obs(as_of_ms: int, *, available_at_ms: int | None = None):
    return FlowObservation(
        family="exchange_btc", metric="btc_netflow", asset="BTC", value=1.0, unit="BTC",
        effective_at_ms=as_of_ms - 3_600_000,
        available_at_ms=as_of_ms - 1_000 if available_at_ms is None else available_at_ms,
        observed_at_ms=as_of_ms, source="test_exchange", source_record_id="row-1",
        cadence_seconds=3600, data_quality=1.0,
    )


def test_capital_flow_handoff_adopts_causal_quality_contract():
    now = 1_787_520_123_456
    handoff = build_anata_handoff(_frame(now), [_obs(now)])
    assert handoff["available_at_ms"] == now - 1_000
    assert handoff["observed_at_ms"] == now
    assert handoff["provenance_refs"] == ["test_exchange:row-1"]
    assert handoff["causal_quality"]["usable"] is True
    assert handoff["causal_quality"]["reason"] is None
    assert "missing_families:" in handoff["limitations"][0]


def test_capital_flow_handoff_fails_closed_without_visible_provenance():
    now = 1_787_520_123_456
    handoff = build_anata_handoff(_frame(now), [])
    assert handoff["available_at_ms"] is None
    assert "no_causally_visible_source_availability" in handoff["missing_reasons"]
    assert handoff["causal_quality"]["usable"] is False
    assert handoff["causal_quality"]["reason"] == "missing_causal_metadata"


def test_future_source_revision_is_not_promoted_into_handoff():
    now = 1_787_520_123_456
    future = _obs(now, available_at_ms=now + 60_000)
    handoff = build_anata_handoff(_frame(now), [future])
    assert handoff["source_evidence"] == []
    assert handoff["causal_quality"]["usable"] is False
    assert "no_causally_visible_source_availability" in handoff["missing_reasons"]
