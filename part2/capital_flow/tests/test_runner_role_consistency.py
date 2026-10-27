from __future__ import annotations

import json
from pathlib import Path
import pytest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.runner import _scoring_history, run_once


@pytest.mark.parametrize(
    "provenance,expected_scoring",
    [
        ({}, True),
        ({"context_only": False}, True),
        ({"context_only": True}, False),
        ({"context_only": " false "}, True),
        ({"context_only": "TRUE"}, False),
        ({"context_only": "maybe"}, False),
        ({"context_only": None}, False),
        ({"context_only": ""}, False),
        ({"context_only": []}, False),
    ],
)
def test_scoring_history_truth_table(provenance, expected_scoring):
    as_of = 1_787_520_123_456
    obs = FlowObservation(
        family="etf",
        metric="etf_netflow_btc",
        asset="BTC",
        value=50.0,
        unit="BTC",
        effective_at_ms=as_of - 10_000,
        available_at_ms=as_of,
        observed_at_ms=as_of,
        source="test_source_scoring",
        source_record_id=f"rec:prov:{id(provenance)}",
        cadence_seconds=3600,
        provenance=provenance,
    )
    scored = _scoring_history([obs])
    if expected_scoring:
        assert len(scored) == 1
        assert scored[0].source_record_id == obs.source_record_id
    else:
        assert len(scored) == 0


def test_run_once_runner_context_role_integration(tmp_path: Path):
    fixed_clock = 1_787_520_123_456
    obs_scoring = FlowObservation(
        family="etf",
        metric="etf_netflow_btc",
        asset="BTC",
        value=100.0,
        unit="BTC",
        effective_at_ms=fixed_clock - 20_000,
        available_at_ms=fixed_clock - 10_000,
        observed_at_ms=fixed_clock - 5_000,
        source="test_integration_source",
        source_record_id="score_rec_1445_01",
        cadence_seconds=3600,
        provenance={"context_only": " false "},
    )
    obs_context = FlowObservation(
        family="etf",
        metric="etf_netflow_btc",
        asset="BTC",
        value=200.0,
        unit="BTC",
        effective_at_ms=fixed_clock - 10_000,
        available_at_ms=fixed_clock,
        observed_at_ms=fixed_clock,
        source="test_integration_source",
        source_record_id="context_rec_1445_01",
        cadence_seconds=3600,
        provenance={"context_only": None},
    )

    archive = tmp_path / "observations.jsonl"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with open(archive, "w", encoding="utf-8") as f:
        f.write(json.dumps(obs_scoring.to_dict()) + "\n")
        f.write(json.dumps(obs_context.to_dict()) + "\n")

    res = run_once(
        local_dir=tmp_path,
        network=False,
        external_jsonl=(),
        as_of_ms=fixed_clock,
    )

    assert res["scoring_records_loaded"] == 1
    assert res["archive_records_loaded"] == 2

    audit_path = tmp_path / "audit_latest.json"
    assert audit_path.exists()
    with open(audit_path, "r", encoding="utf-8") as f:
        audit_data = json.load(f)
    assert audit_data["context_only_observation_count"] == 1

    handoff = res["anata_output"]
    source_evidence = handoff["source_evidence"]
    roles = {item["role"] for item in source_evidence}
    assert "scoring" in roles
    assert "context" in roles
