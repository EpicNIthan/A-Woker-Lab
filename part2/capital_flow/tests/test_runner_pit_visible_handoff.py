from __future__ import annotations

import json
from pathlib import Path
import pytest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.storage import append_observations
from part2.capital_flow import runner


def test_runner_pit_visible_sequential_handoff(tmp_path: Path) -> None:
    T = 1_700_000_000_000
    effective_ms = T - 2000
    available_ms = T - 1000
    observed_ms = T - 1000

    assert available_ms <= T
    assert observed_ms <= T
    assert available_ms <= observed_ms

    row = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=25_000_000.0,
        unit="USD",
        effective_at_ms=effective_ms,
        available_at_ms=available_ms,
        observed_at_ms=observed_ms,
        source="farside_etf",
        source_record_id="rowB",
    )

    archive_path = tmp_path / "observations.jsonl"
    appended_count = append_observations(archive_path, [row])
    assert appended_count == 1

    result1 = runner.run_once(network=False, local_dir=tmp_path, as_of_ms=T)
    assert result1["archive_records_loaded"] == 1
    assert result1["scoring_records_loaded"] == 1
    assert result1["source_errors"] == []

    anata1 = result1["anata_output"]
    assert anata1["schema_version"] == "cf-anata-handoff-v1"
    
    source_evidence_list = anata1["source_evidence"]
    matching_evidence = [e for e in source_evidence_list if e.get("source") == "farside_etf"]
    assert len(matching_evidence) == 1
    ev = matching_evidence[0]
    assert ev["role"] == "scoring"
    assert ev["clock_provenance"]["effective"]["source_record_id"] == "rowB"

    anata_latest_path = tmp_path / "anata_latest.json"
    assert anata_latest_path.exists()
    parsed_anata = json.loads(anata_latest_path.read_text(encoding="utf-8"))
    
    parsed_matching = [e for e in parsed_anata["source_evidence"] if e.get("source") == "farside_etf"]
    assert len(parsed_matching) == 1
    pev = parsed_matching[0]
    assert pev["role"] == "scoring"
    assert pev["clock_provenance"]["effective"]["source_record_id"] == "rowB"

    result2 = runner.run_once(network=False, local_dir=tmp_path, as_of_ms=T)
    assert result2["archive_records_loaded"] == 1
    assert result2["scoring_records_loaded"] == 1
    assert result2["source_errors"] == []

    anata2 = result2["anata_output"]
    matching_evidence_2 = [e for e in anata2["source_evidence"] if e.get("source") == "farside_etf"]
    assert len(matching_evidence_2) == 1
    assert matching_evidence_2[0]["role"] == "scoring"
    assert matching_evidence_2[0]["clock_provenance"]["effective"]["source_record_id"] == "rowB"
