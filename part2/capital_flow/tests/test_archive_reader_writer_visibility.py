from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path
import time
import pytest

from part2.capital_flow.contracts import FlowObservation
from part2.capital_flow.storage import ArchiveWriterLock, append_observations, load_observations

DAY = 86_400_000


def _writer_partial_target(
    archive_path: str,
    obs1_dict: dict,
    obs2_dict: dict,
    start_event: mp.Event,
    partial_written_event: mp.Event,
    release_event: mp.Event,
) -> None:
    try:
        obs1 = FlowObservation.from_dict(obs1_dict)
        obs2 = FlowObservation.from_dict(obs2_dict)

        # Seed valid first observation normally
        append_observations(archive_path, [obs1])

        destination = Path(archive_path)
        with ArchiveWriterLock(destination):
            start_event.set()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("a", encoding="utf-8", newline="\n") as handle:
                # Write half of second row json body without newline
                full_row_json = json.dumps(obs2.to_dict(), sort_keys=True, separators=(",", ":"))
                half_idx = len(full_row_json) // 2
                partial_json = full_row_json[:half_idx]
                handle.write(partial_json)
                handle.flush()
                os.fsync(handle.fileno())

            partial_written_event.set()

            # Wait for bounded release from parent/reader test orchestration
            if not release_event.wait(timeout=10.0):
                os._exit(42)

            # Write remainder of JSON row plus terminal newline and fsync
            with destination.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(full_row_json[half_idx:] + "\n")
                handle.flush()
                os.fsync(handle.fileno())

        os._exit(0)
    except Exception as exc:
        print(f"Writer child error: {exc}")
        os._exit(1)


def _reader_target(
    archive_path: str,
    start_event: mp.Event,
    partial_written_event: mp.Event,
    queue: mp.Queue,
) -> None:
    try:
        # Wait for writer to acquire lock and signal start
        if not start_event.wait(timeout=5.0):
            queue.put(("TIMEOUT", "Writer start signal not received"))
            return

        # Ensure partial write has been flushed
        if not partial_written_event.wait(timeout=5.0):
            queue.put(("TIMEOUT", "Partial written signal not received"))
            return

        # Attempt loading observations while writer holds lock; should block on ArchiveWriterLock
        records = load_observations(archive_path)
        queue.put(("OK", [r.to_dict() for r in records]))
    except Exception as exc:
        queue.put(("ERROR", str(exc)))


def test_archive_reader_writer_visibility_barrier(tmp_path: Path) -> None:
    archive = tmp_path / "visibility.jsonl"
    obs1 = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=100.0,
        unit="USD",
        effective_at_ms=DAY,
        available_at_ms=DAY + 1,
        observed_at_ms=DAY + 1,
        source="vis-src-1",
        source_record_id="rec-1",
    )
    obs2 = FlowObservation(
        family="etf",
        metric="net_flow_usd",
        asset="BTC",
        value=200.0,
        unit="USD",
        effective_at_ms=DAY * 2,
        available_at_ms=DAY * 2 + 1,
        observed_at_ms=DAY * 2 + 1,
        source="vis-src-2",
        source_record_id="rec-2",
    )

    ctx = mp.get_context("spawn")
    start_event = ctx.Event()
    partial_written_event = ctx.Event()
    release_event = ctx.Event()
    queue = ctx.Queue()

    writer_proc = ctx.Process(
        target=_writer_partial_target,
        args=(
            str(archive),
            obs1.to_dict(),
            obs2.to_dict(),
            start_event,
            partial_written_event,
            release_event,
        ),
    )

    reader_proc = ctx.Process(
        target=_reader_target,
        args=(
            str(archive),
            start_event,
            partial_written_event,
            queue,
        ),
    )

    try:
        writer_proc.start()
        reader_proc.start()

        # Verify reader cannot complete during partial write phase because writer holds ArchiveWriterLock
        with pytest.raises(Exception):
            queue.get(timeout=1.0)

        assert reader_proc.is_alive(), "Reader process should be blocked waiting for ArchiveWriterLock"

        # Release the writer lock
        release_event.set()

        # Now reader should unblock and finish successfully
        status, payload = queue.get(timeout=10.0)
        assert status == "OK", f"Reader failed with status {status}: {payload}"

        # Join processes with bounded timeouts
        writer_proc.join(timeout=5.0);
        reader_proc.join(timeout=5.0);

        if writer_proc.is_alive():
            writer_proc.terminate()
            writer_proc.join()
        if reader_proc.is_alive():
            reader_proc.terminate()
            reader_proc.join()

        assert writer_proc.exitcode == 0
        assert reader_proc.exitcode == 0

        # Verify complete two-row read, unique IDs, no partial-row error, and lock cleanup
        loaded_records = [FlowObservation.from_dict(item) for item in payload]
        assert len(loaded_records) == 2
        ids = {r.observation_id for r in loaded_records}
        assert ids == {obs1.observation_id, obs2.observation_id}

        lock_path = Path(str(archive) + ".lock")
        assert not lock_path.exists(), "Archive writer lock file must be cleaned up"
    finally:
        try:
            queue.close()
        except Exception:
            pass
        if writer_proc.is_alive():
            writer_proc.terminate()
            writer_proc.join()
        if reader_proc.is_alive():
            reader_proc.terminate()
            reader_proc.join()
