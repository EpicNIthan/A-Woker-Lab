from __future__ import annotations

import json
multiprocessing = __import__("multiprocessing")
from pathlib import Path
import queue
import pytest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.storage import append_observations
from part2.capital_flow import runner


def _child_target(shared_tmp_path_str: str, q: multiprocessing.Queue) -> None:
    try:
        T = 1_700_000_000_000
        res = runner.run_once(
            network=False,
            local_dir=Path(shared_tmp_path_str),
            as_of_ms=T,
        )
        q.put({
            "archive_records_loaded": res.get("archive_records_loaded"),
            "scoring_records_loaded": res.get("scoring_records_loaded"),
            "source_errors": res.get("source_errors"),
            "anata_output": res.get("anata_output"),
        })
    except Exception as exc:
        q.put({"error": f"{type(exc).__name__}: {exc}"})


def test_runner_two_child_spawn_preflight(tmp_path: Path) -> None:
    T = 1_700_000_000_000
    effective_ms = T - 2000
    available_ms = T - 1000
    observed_ms = T - 1000

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    # Child A: empty shared tmp_path
    pA = ctx.Process(target=_child_target, args=(str(tmp_path), q))
    pA.start()
    try:
        msgA = q.get(timeout=10.0)
    except queue.Empty:
        pA.terminate()
        pytest.fail("Child A timed out")
    pA.join(timeout=5.0)
    if pA.is_alive():
        pA.terminate()
        pA.join()

    assert pA.exitcode == 0
    assert "error" not in msgA
    assert msgA["archive_records_loaded"] == 0
    assert msgA["scoring_records_loaded"] == 0
    assert msgA["source_errors"] == []

    # Parent appends exactly one valid PIT-visible BTC ETF FlowObservation rowB
    rowB = FlowObservation(
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
    appended_count = append_observations(archive_path, [rowB])
    assert appended_count == 1

    # Child B: same path
    pB = ctx.Process(target=_child_target, args=(str(tmp_path), q))
    pB.start()
    try:
        msgB = q.get(timeout=10.0)
    except queue.Empty:
        pB.terminate()
        pytest.fail("Child B timed out")
    pB.join(timeout=5.0)
    if pB.is_alive():
        pB.terminate()
        pB.join()

    assert pB.exitcode == 0
    assert "error" not in msgB
    assert msgB["archive_records_loaded"] == 1
    assert msgB["scoring_records_loaded"] == 1
    assert msgB["source_errors"] == []

    anata_out = msgB["anata_output"]
    matching_evidence = [e for e in anata_out.get("source_evidence", []) if e.get("source") == "farside_etf"]
    assert len(matching_evidence) == 1
    ev = matching_evidence[0]
    assert ev["role"] == "scoring"
    assert ev["clock_provenance"]["effective"]["source_record_id"] == "rowB"

    # Parse persisted anata_latest.json and assert rowB provenance
    anata_latest_path = tmp_path / "anata_latest.json"
    assert anata_latest_path.exists()
    parsed_anata = json.loads(anata_latest_path.read_text(encoding="utf-8"))
    parsed_matching = [e for e in parsed_anata.get("source_evidence", []) if e.get("source") == "farside_etf"]
    assert len(parsed_matching) == 1
    pev = parsed_matching[0]
    assert pev["role"] == "scoring"
    assert pev["clock_provenance"]["effective"]["source_record_id"] == "rowB"
