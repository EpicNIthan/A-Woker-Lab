from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Mapping

from .contracts import FlowObservation


class ArchiveWriterLock:
    """Portable cross-process writer lock using standard library primitives."""

    def __init__(self, archive_path: str | Path, timeout: float = 10.0, poll_interval: float = 0.01) -> None:
        self.path = Path(archive_path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.fd: int | None = None

    def __enter__(self) -> "ArchiveWriterLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()
        while True:
            try:
                self.fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                break
            except FileExistsError:
                if time.monotonic() - start_time > self.timeout:
                    raise TimeoutError(f"Timed out acquiring archive writer lock for {self.path}")
                time.sleep(self.poll_interval)
            except Exception:
                # Cleanup only if we successfully created this exact new lock file
                if self.fd is not None:
                    try:
                        new_stat = os.fstat(self.fd)
                    except Exception:
                        new_stat = None
                    try:
                        os.close(self.fd)
                    except Exception:
                        pass
                    self.fd = None

                    if new_stat is not None:
                        try:
                            current_stat = self.lock_path.lstat()
                            if current_stat.st_ino == new_stat.st_ino and current_stat.st_dev == new_stat.st_dev:
                                self.lock_path.unlink()
                        except Exception:
                            pass
                raise
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        owned_stat = None
        if self.fd is not None:
            try:
                owned_stat = os.fstat(self.fd)
            except Exception:
                owned_stat = None
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

        if owned_stat is not None:
            try:
                current_stat = self.lock_path.lstat()
                if current_stat.st_ino == owned_stat.st_ino and current_stat.st_dev == owned_stat.st_dev:
                    self.lock_path.unlink()
            except Exception:
                pass


def atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_observations(path: str | Path, *, max_records: int | None = None) -> list[FlowObservation]:
    source = Path(path)
    with ArchiveWriterLock(source):
        return _load_observations_unlocked(source, max_records=max_records)


def _load_observations_unlocked(path: str | Path, *, max_records: int | None = None) -> list[FlowObservation]:
    source = Path(path)
    if not source.exists():
        return []
    if max_records is not None and max_records <= 0:
        return []
    records = deque(maxlen=max_records) if max_records is not None else []
    with source.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
                records.append(FlowObservation.from_dict(payload))
            except Exception as exc:
                raise ValueError(f"invalid observation JSONL at {source}:{line_no}: {exc}") from exc
    return list(records)


def append_observations(
    path: str | Path,
    observations: Iterable[FlowObservation],
    *,
    max_existing_records: int = 100_000,
) -> int:
    """Append only unseen observation IDs while keeping memory bounded.

    The archive is intentionally append-only. Provider revisions are separate
    records and are resolved point-in-time by the engine instead of overwriting
    history.
    """

    destination = Path(path)
    observations_list = list(observations)
    if not observations_list:
        return 0

    with ArchiveWriterLock(destination):
        existing = _load_observations_unlocked(destination, max_records=max_existing_records)
        seen = {obs.observation_id for obs in existing}
        latest_signature: dict[tuple[str, str, str, str], tuple[Any, ...]] = {}
        for obs in existing:
            latest_signature[obs.revision_key] = _semantic_signature(obs)

        new: list[FlowObservation] = []
        for obs in observations_list:
            if obs.observation_id in seen:
                continue
            signature = _semantic_signature(obs)
            # Re-scraping an unchanged historical row must not create a new revision
            # merely because observed_at changed. The first stored copy remains the
            # legal availability time until the provider value/semantics actually change.
            if latest_signature.get(obs.revision_key) == signature:
                continue
            new.append(obs)
            seen.add(obs.observation_id)
            latest_signature[obs.revision_key] = signature
        if not new:
            return 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8", newline="\n") as handle:
            for obs in new:
                handle.write(json.dumps(obs.to_dict(), sort_keys=True, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return len(new)


def _semantic_signature(obs: FlowObservation) -> tuple[Any, ...]:
    return (
        obs.value,
        obs.unit,
        obs.effective_at_ms,
        obs.cadence_seconds,
        obs.attribution_status,
        obs.attribution_quality,
        obs.data_quality,
        obs.economic_event_id,
        obs.dependence_group,
        tuple(sorted(obs.quality_flags)),
        json.dumps(dict(obs.provenance), sort_keys=True, separators=(",", ":")),
    )
