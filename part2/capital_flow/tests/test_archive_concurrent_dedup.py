from __future__ import annotations

import errno
import multiprocessing as mp
import os
from pathlib import Path
import time
import pytest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.storage import ArchiveWriterLock, append_observations, load_observations

DAY = 86_400_000


def _worker_append_target(archive_path: str, serialized_obs_list: list[str], queue: mp.Queue) -> None:
    try:
        obs_list = [FlowObservation.from_dict(dict(item)) for item in serialized_obs_list]
        count = append_observations(archive_path, obs_list)
        queue.put(("OK", count))
    except Exception as exc:
        queue.put(("ERROR", str(exc)))


def _orphan_lock_child_target(archive_path: str, acquired_event: mp.Event, release_event: mp.Event) -> None:
    with ArchiveWriterLock(archive_path):
        acquired_event.set()
        # Wait for parent release signal with bounded timeout
        release_event.wait(timeout=10.0)
        os._exit(17)


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

    try:
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
            assert p.exitcode == 0

        total_appended = 0
        for status, payload in results:
            assert status == "OK", f"Worker failed with error: {payload}"
            total_appended += payload

        # For same ID across multiple concurrent workers, exactly one worker appends the row (sum == 1)
        assert total_appended == 1

        loaded = load_observations(archive)
        assert len(loaded) == 1
        assert loaded[0].observation_id == obs.observation_id
        assert loaded[0].value == 42.0
    finally:
        try:
            queue.close()
        except Exception:
            pass
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join()


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

    try:
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
            p1.join()
        if p2.is_alive():
            p2.terminate()
            p2.join()

        assert p1.exitcode == 0
        assert p2.exitcode == 0

        total_appended = 0
        for status, payload in results:
            assert status == "OK", f"Worker failed with error: {payload}"
            total_appended += payload

        # Distinct IDs should sum to 2 appended records
        assert total_appended == 2

        loaded = load_observations(archive)
        assert len(loaded) == 2
        ids = {item.observation_id for item in loaded}
        assert ids == {obs1.observation_id, obs2.observation_id}
    finally:
        try:
            queue.close()
        except Exception:
            pass
        if p1.is_alive():
            p1.terminate()
            p1.join()
        if p2.is_alive():
            p2.terminate()
            p2.join()


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


def test_pid_write_failure_removes_only_new_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "pid_fail.jsonl"
    lock_path = Path(str(archive) + ".lock")

    assert not lock_path.exists()

    original_write = os.write
    def mock_write(fd, data):
        if fd >= 0:
            raise OSError(errno.ENOSPC, "simulated PID write failure")
        return original_write(fd, data)

    monkeypatch.setattr(os, "write", mock_write)

    with pytest.raises(OSError) as exc_info:
        with ArchiveWriterLock(archive, timeout=0.05, poll_interval=0.005):
            pass

    assert exc_info.value.errno == errno.ENOSPC
    assert not lock_path.exists()

    # Restore monkeypatch before a second successful lock acquisition
    monkeypatch.undo()

    with ArchiveWriterLock(archive, timeout=1.0, poll_interval=0.01):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_preexisting_orphan_lock_is_preserved(tmp_path: Path) -> None:
    archive = tmp_path / "orphan_fixed.jsonl"
    lock_path = Path(str(archive) + ".lock")

    sentinel = "PREEXISTING_ORPHAN_SENTINEL"
    lock_path.write_text(sentinel, encoding="utf-8")
    assert lock_path.exists()

    try:
        with pytest.raises(TimeoutError):
            with ArchiveWriterLock(archive, timeout=0.05, poll_interval=0.005):
                pass

        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8") == sentinel
    finally:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass


def test_archive_orphan_lock_fail_closed(tmp_path: Path) -> None:
    archive = tmp_path / "orphan.jsonl"
    lock_path = Path(str(archive) + ".lock")

    ctx = mp.get_context("spawn")
    acquired_event = ctx.Event()
    release_event = ctx.Event()

    p = ctx.Process(
        target=_orphan_lock_child_target,
        args=(str(archive), acquired_event, release_event),
    )

    try:
        p.start()
        # Wait for child to acquire lock
        assert acquired_event.wait(timeout=5.0), "Child failed to acquire lock in time"
        assert lock_path.exists(), ".jsonl.lock must exist while child holds lock"

        # Release child to proceed and crash via os._exit(17)
        release_event.set()
        p.join(timeout=5.0)
        if p.is_alive():
            p.terminate()
            p.join()

        assert p.exitcode == 17
        assert lock_path.exists(), "Orphan lock file must remain after child crash"

        # Verify subsequent lock attempt fails with TimeoutError due to orphan lock
        with pytest.raises(TimeoutError):
            with ArchiveWriterLock(archive, timeout=0.1, poll_interval=0.01):
                pass
    finally:
        if p.is_alive():
            p.terminate()
            p.join()
        # Safely cleanup orphan lockfile only after child is confirmed dead
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass
