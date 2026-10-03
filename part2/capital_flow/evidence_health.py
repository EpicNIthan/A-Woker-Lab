from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .contracts import FAMILIES, FlowObservation, point_in_time_filter

EVIDENCE_HEALTH_SCHEMA = "cf-evidence-health-v2"


def _age_seconds(as_of_ms: int, timestamp_ms: int | None) -> float | None:
    if timestamp_ms is None:
        return None
    return max(0.0, (int(as_of_ms) - int(timestamp_ms)) / 1000.0)


def _latest(observations: list[FlowObservation], field: str) -> int | None:
    values = [getattr(obs, field) for obs in observations if getattr(obs, field) is not None]
    return max(values) if values else None


def _source_error_names(source_errors: Iterable[str]) -> tuple[str, ...]:
    names: list[str] = []
    for error in source_errors:
        prefix = str(error).split(":", 1)[0].strip()
        if prefix and prefix not in names:
            names.append(prefix)
    return tuple(names)


def _collection_summary(
    attempts: Iterable[Mapping[str, Any]], *, as_of_ms: int, errors: tuple[str, ...]
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for attempt in attempts:
        attempted_at = attempt.get("attempted_at_ms")
        normalized.append(
            {
                "collector": str(attempt.get("collector", "unknown")),
                "status": str(attempt.get("status", "UNKNOWN")),
                "attempted_at_ms": int(attempted_at) if attempted_at is not None else None,
                "attempt_age_seconds": _age_seconds(as_of_ms, int(attempted_at)) if attempted_at is not None else None,
                "observation_count": max(0, int(attempt.get("observation_count", 0))),
                "error_count": max(0, int(attempt.get("error_count", 0))),
                "mode": str(attempt.get("mode", "network")),
            }
        )
    failed = [item["collector"] for item in normalized if item["status"] in {"FAILED", "PARTIAL"}]
    succeeded = [item["collector"] for item in normalized if item["status"] == "OK"]
    return {
        "attempted": bool(normalized),
        "attempts": normalized,
        "successful_collectors": succeeded,
        "failed_or_partial_collectors": failed,
        "errors_present": bool(errors),
        "failed_collectors": list(_source_error_names(errors)),
        "error_count": len(errors),
    }


def build_evidence_health(
    observations: Iterable[FlowObservation],
    *,
    as_of_ms: int,
    source_errors: Iterable[str] = (),
    collection_attempts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return causal provenance/freshness and current collection health without changing CF scores."""
    errors = tuple(str(error) for error in source_errors)
    visible = point_in_time_filter(list(observations), int(as_of_ms))
    by_family: dict[str, list[FlowObservation]] = defaultdict(list)
    for obs in visible:
        if obs.family in FAMILIES and obs.effective_at_ms <= int(as_of_ms):
            by_family[obs.family].append(obs)

    families: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        rows = by_family.get(family, [])
        scoring = [row for row in rows if not bool(dict(row.provenance).get("context_only", False))]
        latest_effective = _latest(rows, "effective_at_ms")
        latest_available = _latest(rows, "available_at_ms")
        latest_observed = _latest(rows, "observed_at_ms")
        cadences = sorted({int(row.cadence_seconds) for row in rows if int(row.cadence_seconds) > 0})
        sources = sorted({str(row.source) for row in rows})
        scoring_sources = sorted({str(row.source) for row in scoring})
        families[family] = {
            "visible_observation_count": len(rows),
            "scoring_observation_count": len(scoring),
            "sources": sources,
            "scoring_sources": scoring_sources,
            "cadence_seconds": cadences,
            "latest_effective_at_ms": latest_effective,
            "latest_available_at_ms": latest_available,
            "latest_observed_at_ms": latest_observed,
            "effective_age_seconds": _age_seconds(as_of_ms, latest_effective),
            "availability_age_seconds": _age_seconds(as_of_ms, latest_available),
            "observation_age_seconds": _age_seconds(as_of_ms, latest_observed),
            "missing": not rows,
            "scoring_missing": not scoring,
        }

    return {
        "schema_version": EVIDENCE_HEALTH_SCHEMA,
        "as_of_ms": int(as_of_ms),
        "families": families,
        "collection": _collection_summary(collection_attempts, as_of_ms=int(as_of_ms), errors=errors),
        "semantics": {
            "point_in_time_visible_only": True,
            "historical_rows_do_not_imply_current_collection_success": True,
            "collector_success_does_not_imply_fresh_economic_data": True,
            "age_is_not_zero_filled": True,
            "does_not_change_capital_flow_scores": True,
        },
    }
