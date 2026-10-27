from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from part2.capital_flow import storage


def test_atomic_handoff_visibility(tmp_path: Path) -> None:
    destination = tmp_path / "anata_latest.json"

    payload_a = {
        "generation_marker": "marker_a_1850_01",
        "correlated_marker": "corr_a_1850_01",
        "nested": {
            "field_one": 100,
            "field_two": "alpha",
        },
    }

    payload_b = {
        "generation_marker": "marker_b_1850_01",
        "correlated_marker": "corr_b_1850_01",
        "nested": {
            "field_one": 200,
            "field_two": "beta",
        },
    }

    # First publish full payload A normally
    storage.atomic_write_json(destination, payload_a)

    # Verify payload A is present and correct
    assert destination.exists()
    with destination.open("r", encoding="utf-8") as f:
        parsed_initial = json.load(f)
    assert parsed_initial == payload_a

    entered = threading.Event()
    release = threading.Event()
    original_replace = os.replace
    writer_exception: list[BaseException] = []

    def narrowly_scoped_replace(src, dst):
        # Scope only to our exact target destination path
        if Path(dst).resolve() == destination.resolve():
            entered.set()
            # Wait for release with bounded timeout to prevent pytest hangs
            if not release.wait(timeout=5.0):
                raise TimeoutError("Timed out waiting for test synchronization release event")
        return original_replace(src, dst)

    def background_writer():
        try:
            storage.atomic_write_json(destination, payload_b)
        except BaseException as exc:
            writer_exception.append(exc)

    # Monkeypatch os.replace and start background thread writing payload B
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(os, "replace", narrowly_scoped_replace)

    thread = threading.Thread(target=background_writer, daemon=True)
    thread.start()

    try:
        # Wait for writer B to reach os.replace using bounded timeout event
        assert entered.wait(timeout=5.0), "Background writer failed to reach replace within timeout"

        # While B is paused right before replacement, parse destination and assert it is strictly complete A
        with destination.open("r", encoding="utf-8") as f:
            parsed_during_pause = json.load(f)
        assert parsed_during_pause == payload_a

        # Verify precisely one live temporary file for destination exists matching mkstemp prefix and .tmp suffix
        expected_prefix = destination.name + "."
        tmp_files = [
            p for p in destination.parent.glob("*.tmp")
            if p.name.startswith(expected_prefix)
        ]
        assert len(tmp_files) == 1

    finally:
        # Release B in a finally block
        release.set()
        thread.join(timeout=5.0)
        monkeypatch.undo()

    # Propagate any background exceptions if raised
    if writer_exception:
        raise writer_exception[0]

    # Assert background thread finished successfully
    assert not thread.is_alive()

    # Parse destination again and assert it is now exactly complete B
    with destination.open("r", encoding="utf-8") as f:
        parsed_after = json.load(f)
    assert parsed_after == payload_b

    # Assert no leaked *.tmp files after completion
    remaining_tmp_files = list(destination.parent.glob("*.tmp"))
    assert len(remaining_tmp_files) == 0
