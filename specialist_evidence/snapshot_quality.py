from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass(frozen=True, slots=True)
class HandoffClock:
    """Normalized causal clocks for one Specialist handoff, in Unix milliseconds."""

    specialist: str
    schema_version: str
    as_of_ms: int
    available_at_ms: int
    observed_at_ms: int | None = None
    source_observed_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffQuality:
    """Per-Specialist evidence packaging quality; never a prediction score."""

    specialist: str
    usable: bool
    schema_version: str | None
    as_of_ms: int | None
    available_at_ms: int | None
    age_seconds: float | None
    availability_lag_seconds: float | None
    missing: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    reason: str | None


def _int_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _provenance_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for key in ("provenance_refs", "source_refs", "sources"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            refs.extend(str(item) for item in value.keys())
        else:
            refs.extend(_text_tuple(value))
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("source", "source_id", "provider", "venue", "record_id"):
            value = provenance.get(key)
            if value is not None and str(value).strip():
                refs.append(f"{key}:{value}")
    return tuple(dict.fromkeys(refs))


def assess_handoff_quality(
    specialist: str,
    payload: Mapping[str, Any],
    *,
    frame_as_of_ms: int,
    max_age_seconds: float,
    max_future_skew_seconds: float = 30.0,
) -> HandoffQuality:
    """Assess one handoff against a caller-supplied causal frame.

    The function deliberately does not merge payloads. `frame_as_of_ms` is only
    a common causal cutoff used to detect stale/future/misaligned handoffs.
    A Specialist must expose both its evidence `as_of_ms` and the earliest
    `available_at_ms` at which that exact revision was knowable. Falling back
    from availability to observation/publication time is intentionally forbidden.
    """

    schema = payload.get("schema_version")
    schema_text = None if schema is None else str(schema)
    as_of_ms = _int_ms(payload.get("as_of_ms"))
    available_at_ms = _int_ms(payload.get("available_at_ms"))
    observed_at_ms = _int_ms(payload.get("observed_at_ms"))
    source_observed_at_ms = _int_ms(payload.get("source_observed_at_ms"))

    missing: list[str] = []
    if schema_text is None or not schema_text.strip():
        missing.append("schema_version")
    if as_of_ms is None:
        missing.append("as_of_ms")
    if available_at_ms is None:
        missing.append("available_at_ms")
    if not _provenance_refs(payload):
        missing.append("provenance_refs")

    limitations = list(_text_tuple(payload.get("limitations")))
    limitations.extend(_text_tuple(payload.get("missing_reasons")))

    reason: str | None = None
    future_limit_ms = frame_as_of_ms + int(max_future_skew_seconds * 1000)
    if missing:
        reason = "missing_causal_metadata"
    elif available_at_ms is not None and available_at_ms > frame_as_of_ms:
        reason = "not_yet_available"
    elif as_of_ms is not None and as_of_ms > future_limit_ms:
        reason = "future_as_of"
    # available_at may legitimately precede the Specialist handoff as_of cutoff.
    # Causality requires availability no later than the cutoff (checked above),
    # while source receipt ordering is enforced independently below.
    elif observed_at_ms is not None and available_at_ms is not None and available_at_ms > observed_at_ms:
        # Local receipt is a hard upper bound on what this installation knew.
        reason = "availability_after_receipt"

    age_seconds = None if as_of_ms is None else max(0.0, (frame_as_of_ms - as_of_ms) / 1000.0)
    availability_lag_seconds = (
        None
        if as_of_ms is None or available_at_ms is None
        else max(0.0, (available_at_ms - as_of_ms) / 1000.0)
    )
    if reason is None and age_seconds is not None and age_seconds > max_age_seconds:
        reason = "stale"

    return HandoffQuality(
        specialist=specialist,
        usable=reason is None,
        schema_version=schema_text,
        as_of_ms=as_of_ms,
        available_at_ms=available_at_ms,
        age_seconds=age_seconds,
        availability_lag_seconds=availability_lag_seconds,
        missing=tuple(missing),
        limitations=tuple(dict.fromkeys(limitations)),
        provenance_refs=_provenance_refs(payload),
        reason=reason,
    )
