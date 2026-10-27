from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import time

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.storage import append_observations, load_observations

DAY = 86_400_000


def _worker_append_target(archive_path: str, serialized_obs_list: list[str], queue: mp.Queue) -> None:
    try:
        obs_list = [FlowObservation.from_dict(dict(item)) for item in serialized_obs_list]
        count = append_observations(archive_path, obs_list)
        queue.put(("OK", count))
    except Exception as exc:
        queue.put(("ERROR", str(exc)))


def test_archive_concurrent_same_observation_id(tmp_path: Path) -> None:
    archive = tmp_path / "concurrent.jsonl"
    obs = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=42.0,
        unit="USD",
        effective_at_ms=DAY,
        available_at_ms=DAY + 1,
        observed_at_ms=DAY + 1,
        source="concurrent-src",
        source_record_id="rec-1",
    )
    serialized_payloads = [obs.to_dict()]

    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    num_workers = 4
    processes = [
        ctx.Process(target=_worker_append_target, args=(str(archive), serialized_payloads, queue))
        for _ in range(num_workers)
    ]

    for p in processes:
        p.start()

    results = []
    for _ in range(num_workers):
        status, payload = queue.get(timeout=10.0)
        results.append((status, payload))

    for p in processes:
        p.join(timeout=5.0)
        if p.is_alive():
            p.terminate()
            p.join()

    for status, payload in results:
        assert status == "OK", f"Worker failed with error: {payload}"

    loaded = load_observations(archive)
    assert len(loaded) == 1
    assert loaded[0].observation_id == obs.observation_id
    assert loaded[0].value == 42.0


def test_archive_concurrent_distinct_observation_ids(tmp_path: Path) -> None:
    archive = tmp_path / "distinct.jsonl"
    obs1 = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=10.0,
        unit="USD",
        effective_at_ms=DAY,
        available_at_ms=DAY + 1,
        observed_at_ms=DAY + 1,
        source="src-1",
        source_record_id="rec-1",
    )
    obs2 = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=20.0,
        unit="USD",
        effective_at_ms=DAY * 2,
        available_at_ms=DAY * 2 + 1,
        observed_at_ms=DAY * 2 + 1,
        source="src-2",
        source_record_id="rec-2",
    )

    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    p1 = ctx.Process(target=_worker_append_target, args=(str(archive), [obs1.to_dict()], queue))
    p2 = ctx.Process(target=_worker_append_target, args=(str(archive), [obs2.to_dict()], queue))

    p1.start()
    p2.start()

    results = []
    for _ in range(2):
        status, payload = queue.get(timeout=10.0)
        results.append((status, payload))

    p1.join(timeout=5.0)
    p2.join(timeout=5.0)
    if p1.is_alive():
        p1.terminate()
    if p2.is_alive():
        p2.terminate()

    for status, payload in results:
        assert status == "OK", f"Worker failed with error: {payload}"

    loaded = load_observations(archive)
    assert len(loaded) == 2
    ids = {item.observation_id for item in loaded}
    assert ids == {obs1.observation_id, obs2.observation_id}


def test_archive_idempotent_repeated_append(tmp_path: Path) -> None:
    archive = tmp_path / "idempotent.jsonl"
    obs = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=100.0,
        unit="USD",
        effective_at_ms=DAY,
        available_at_ms=DAY + 1,
        observed_at_ms=DAY + 1,
        source="idempotent-src",
        source_record_id="rec-100",
    )

    assert append_observations(archive, [obs]) == 1
    assert append_observations(archive, [obs]) == 0
    assert append_observations(archive, [obs, obs]) == 0

    loaded = load_observations(archive)
    assert len(loaded) == 1
    assert loaded[0].observation_id == obs.observation_id
