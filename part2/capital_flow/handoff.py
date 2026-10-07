from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from specialist_evidence.snapshot_quality import assess_handoff_quality

from .contracts import FAMILIES, FlowObservation, point_in_time_filter
from .engine import CORE_FAMILIES, OPTIONAL_FAMILIES, CapitalFlowFrame
from .normalization import normalize_and_dedup

HANDOFF_SCHEMA_VERSION = "cf-anata-handoff-v1"
HANDOFF_MAX_AGE_SECONDS = 172800.0

_COMPONENT_METRICS = (
    "component_supply_usd",
    "component_supply_change_1d_usd",
    "component_supply_change_7d_usd",
    "component_supply_change_30d_usd",
    "component_price_usd",
)


def _visible_normalized(observations: Iterable[FlowObservation], *, as_of_ms: int) -> list[FlowObservation]:
    visible = point_in_time_filter(list(observations), as_of_ms)
    normalized, _ = normalize_and_dedup(visible)
    return [obs for obs in normalized if obs.effective_at_ms <= as_of_ms]


def _is_context_only(obs: FlowObservation) -> bool:
    return bool(dict(obs.provenance).get("context_only", False))


def _age_ms(as_of_ms: int, timestamp_ms: int | None) -> int | None:
    if timestamp_ms is None:
        return None
    return max(0, int(as_of_ms) - int(timestamp_ms))


def _source_evidence(normalized: list[FlowObservation], *, as_of_ms: int) -> list[dict[str, Any]]:
    """Compact source-level PIT/freshness provenance for Anata."""
    grouped: dict[tuple[str, str, str], list[FlowObservation]] = {}
    for obs in normalized:
        grouped.setdefault((obs.family, obs.source, "context" if _is_context_only(obs) else "scoring"), []).append(obs)

    result: list[dict[str, Any]] = []
    for (family, source, role), rows in sorted(grouped.items()):
        newest_effective = max(
            rows,
            key=lambda obs: (
                obs.effective_at_ms,
                obs.available_at_ms if obs.available_at_ms is not None else -1,
                obs.observed_at_ms,
                obs.source_record_id,
            ),
        )
        latest_effective_at_ms = newest_effective.effective_at_ms

        available_rows = [obs for obs in rows if obs.available_at_ms is not None]
        if available_rows:
            best_available = max(
                available_rows,
                key=lambda obs: (
                    obs.available_at_ms,
                    obs.observed_at_ms,
                    obs.effective_at_ms,
                    obs.source_record_id,
                ),
            )
            latest_available_at_ms = best_available.available_at_ms
            latest_available_provenance = {
                "source_record_id": best_available.source_record_id,
                "revision": best_available.revision,
            }
        else:
            latest_available_at_ms = None
            latest_available_provenance = None

        best_observed = max(
            rows,
            key=lambda obs: (
                obs.observed_at_ms,
                obs.available_at_ms if obs.available_at_ms is not None else -1,
                obs.effective_at_ms,
                obs.source_record_id,
            ),
        )
        latest_observed_at_ms = best_observed.observed_at_ms

        cadences = sorted({int(obs.cadence_seconds) for obs in rows if obs.cadence_seconds is not None})
        metrics = sorted({obs.metric for obs in rows})
        quality_flags = sorted({flag for obs in rows for flag in obs.quality_flags})
        result.append({
            "family": family, "source": source, "role": role, "metrics": metrics,
            "observation_count": len(rows), "latest_effective_at_ms": latest_effective_at_ms,
            "latest_available_at_ms": latest_available_at_ms, "latest_observed_at_ms": latest_observed_at_ms,
            "clock_provenance": {
                "effective": {
                    "source_record_id": newest_effective.source_record_id,
                    "revision": newest_effective.revision,
                },
                "availability": latest_available_provenance,
                "observed": {
                    "source_record_id": best_observed.source_record_id,
                    "revision": best_observed.revision,
                },
            },
            "economic_age_ms": _age_ms(as_of_ms, latest_effective_at_ms),
            "availability_age_ms": _age_ms(as_of_ms, latest_available_at_ms),
            "collector_age_ms": _age_ms(as_of_ms, latest_observed_at_ms),
            "cadence_seconds": cadences[0] if len(cadences) == 1 else None,
            "cadences_seconds": cadences, "attribution_status": newest_effective.attribution_status,
            "attribution_quality": newest_effective.attribution_quality, "data_quality": newest_effective.data_quality,
            "quality_flags": quality_flags, "provenance": dict(newest_effective.provenance),
        })
    return result


def build_stablecoin_context(observations: Iterable[FlowObservation], *, as_of_ms: int, max_components: int = 8) -> dict[str, Any]:
    normalized = _visible_normalized(observations, as_of_ms=as_of_ms)
    latest: dict[tuple[str, str], FlowObservation] = {}
    for obs in normalized:
        if obs.family != "stablecoin" or obs.metric not in _COMPONENT_METRICS:
            continue
        key = (obs.asset.upper(), obs.metric)
        current = latest.get(key)
        rank = (obs.effective_at_ms, obs.available_at_ms or -1, obs.observed_at_ms)
        current_rank = ((current.effective_at_ms, current.available_at_ms or -1, current.observed_at_ms) if current is not None else (-1, -1, -1))
        if current is None or rank > current_rank:
            latest[key] = obs

    symbols = sorted({symbol for symbol, _ in latest})
    components: list[dict[str, Any]] = []
    for symbol in symbols:
        by_metric = {metric: latest.get((symbol, metric)) for metric in _COMPONENT_METRICS}
        supply_obs = by_metric["component_supply_usd"]
        if supply_obs is None:
            continue
        components.append({
            "symbol": symbol, "supply_usd": supply_obs.value,
            "change_1d_usd": by_metric["component_supply_change_1d_usd"].value if by_metric["component_supply_change_1d_usd"] is not None else None,
            "change_7d_usd": by_metric["component_supply_change_7d_usd"].value if by_metric["component_supply_change_7d_usd"] is not None else None,
            "change_30d_usd": by_metric["component_supply_change_30d_usd"].value if by_metric["component_supply_change_30d_usd"] is not None else None,
            "price_usd": by_metric["component_price_usd"].value if by_metric["component_price_usd"] is not None else None,
            "effective_at_ms": supply_obs.effective_at_ms, "available_at_ms": supply_obs.available_at_ms,
            "source": supply_obs.source,
        })
    components.sort(key=lambda item: float(item["supply_usd"]), reverse=True)
    components = components[: max(0, int(max_components))]
    tracked_supply = sum(float(item["supply_usd"]) for item in components) if components else None

    # Composition-quality features are descriptive context only.  They expose
    # whether the tracked liquidity proxy is concentrated and whether its USD
    # pegs are currently well represented; they never become a BTC direction.
    for item in components:
        supply = float(item["supply_usd"])
        share = None if not tracked_supply or tracked_supply <= 0 else supply / tracked_supply
        price = item["price_usd"]
        item["supply_share_of_tracked"] = share
        item["peg_deviation_bps"] = None if price is None else (float(price) - 1.0) * 10_000.0
        item["economic_age_ms"] = _age_ms(as_of_ms, item["effective_at_ms"])
        item["availability_age_ms"] = _age_ms(as_of_ms, item["available_at_ms"])
        item["missing_fields"] = [
            field
            for field in ("change_1d_usd", "change_7d_usd", "change_30d_usd", "price_usd")
            if item[field] is None
        ]

    change_1d_values = [item["change_1d_usd"] for item in components if item["change_1d_usd"] is not None]
    change_7d_values = [item["change_7d_usd"] for item in components if item["change_7d_usd"] is not None]
    change_30d_values = [item["change_30d_usd"] for item in components if item["change_30d_usd"] is not None]
    shares = [float(item["supply_share_of_tracked"]) for item in components if item["supply_share_of_tracked"] is not None]
    priced = [item for item in components if item["peg_deviation_bps"] is not None and item["supply_share_of_tracked"] is not None]
    weighted_abs_peg_deviation_bps = (
        sum(abs(float(item["peg_deviation_bps"])) * float(item["supply_share_of_tracked"]) for item in priced)
        / sum(float(item["supply_share_of_tracked"]) for item in priced)
        if priced
        else None
    )
    max_abs_peg_deviation_bps = max((abs(float(item["peg_deviation_bps"])) for item in priced), default=None)
    count = len(components)
    return {
        "known": bool(components), "tracked_component_count": count, "tracked_supply_usd": tracked_supply,
        "tracked_change_1d_usd": sum(change_1d_values) if change_1d_values else None,
        "tracked_change_7d_usd": sum(change_7d_values) if change_7d_values else None,
        "tracked_change_30d_usd": sum(change_30d_values) if change_30d_values else None,
        "composition_hhi": sum(share * share for share in shares) if shares else None,
        "top_component_share": max(shares) if shares else None,
        "top_two_component_share": sum(sorted(shares, reverse=True)[:2]) if shares else None,
        "peg_price_coverage": (len(priced) / count) if count else 0.0,
        "weighted_abs_peg_deviation_bps": weighted_abs_peg_deviation_bps,
        "max_abs_peg_deviation_bps": max_abs_peg_deviation_bps,
        "change_coverage": {
            "1d": (len(change_1d_values) / count) if count else 0.0,
            "7d": (len(change_7d_values) / count) if count else 0.0,
            "30d": (len(change_30d_values) / count) if count else 0.0,
        },
        "components": components,
        "quality_flags": [
            "TRACKED_COMPONENT_SUBSET_NOT_TOTAL_STABLECOIN_MARKET",
            "PEG_PRICE_IS_CONTEXT_NOT_REDEMPTION_GUARANTEE",
            "COMPONENT_CONTEXT_EXCLUDED_FROM_FROZEN_SCORING",
        ] if components else ["NO_STABLECOIN_COMPONENT_CONTEXT"],
        "interpretation_guard": "potential_liquidity_not_btc_buying",
    }


def _family_support(frame: CapitalFlowFrame, normalized: list[FlowObservation], *, as_of_ms: int) -> dict[str, dict[str, Any]]:
    scoring_counts = {family: 0 for family in FAMILIES}; context_counts = {family: 0 for family in FAMILIES}
    scoring_sources = {family: set() for family in FAMILIES}; context_sources = {family: set() for family in FAMILIES}
    total_counts = {family: 0 for family in FAMILIES}; total_sources = {family: set() for family in FAMILIES}
    scoring_rows = {family: [] for family in FAMILIES}
    for obs in normalized:
        if obs.family not in scoring_counts: continue
        total_counts[obs.family] += 1; total_sources[obs.family].add(obs.source)
        if _is_context_only(obs): context_counts[obs.family] += 1; context_sources[obs.family].add(obs.source)
        else:
            scoring_counts[obs.family] += 1; scoring_sources[obs.family].add(obs.source); scoring_rows[obs.family].append(obs)
    result: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        states = frame.family_states.get(family, {})
        known_horizons = [name for name, state in states.items() if state.known]
        score = frame.family_scores.get(family)
        if score is not None: status = "ACTIVE"
        elif known_horizons: status = "ACTIVE_NO_PREFERRED_SCORE"
        elif scoring_counts[family] > 0: status = "OBSERVED_INSUFFICIENT_HISTORY"
        elif context_counts[family] > 0: status = "CONTEXT_ONLY"
        else: status = "MISSING"
        rows = scoring_rows[family]
        scoring_latest_effective = max((obs.effective_at_ms for obs in rows), default=None)
        scoring_latest_available = max((obs.available_at_ms for obs in rows if obs.available_at_ms is not None), default=None)
        scoring_latest_observed = max((obs.observed_at_ms for obs in rows), default=None)
        result[family] = {
            "role": "core" if family in CORE_FAMILIES else "optional", "status": status, "score": score,
            "known_horizons": known_horizons, "observation_count": total_counts[family], "source_count": len(total_sources[family]),
            "scoring_observation_count": scoring_counts[family], "scoring_source_count": len(scoring_sources[family]),
            "scoring_latest_effective_at_ms": scoring_latest_effective,
            "scoring_latest_available_at_ms": scoring_latest_available,
            "scoring_latest_observed_at_ms": scoring_latest_observed,
            "scoring_economic_age_ms": _age_ms(as_of_ms, scoring_latest_effective),
            "scoring_availability_age_ms": _age_ms(as_of_ms, scoring_latest_available),
            "scoring_collector_age_ms": _age_ms(as_of_ms, scoring_latest_observed),
            "context_observation_count": context_counts[family], "context_source_count": len(context_sources[family]),
            "has_context_only_evidence": context_counts[family] > 0,
        }
    return result


def _causal_metadata(normalized: list[FlowObservation], *, as_of_ms: int, source_errors: tuple[str, ...], missing_families: list[str]) -> dict[str, Any]:
    # Top-level causal quality gates the frozen scoring handoff. Context-only
    # evidence remains visible in source_evidence, but cannot make scoring
    # provenance/timing appear usable on its own.
    scoring = [obs for obs in normalized if not _is_context_only(obs)]
    available = [int(obs.available_at_ms) for obs in scoring if obs.available_at_ms is not None]
    observed = [int(obs.observed_at_ms) for obs in scoring]
    refs = sorted({f"{obs.source}:{obs.source_record_id}" for obs in scoring})
    missing_reasons: list[str] = []
    limitations: list[str] = []
    if not available:
        missing_reasons.append("no_causally_visible_source_availability")
    if not refs:
        missing_reasons.append("no_visible_source_provenance")
    if missing_families:
        limitations.append("missing_families:" + ",".join(sorted(missing_families)))
    if source_errors:
        limitations.append("source_errors_present")
    return {
        "available_at_ms": max(available) if available else None,
        "observed_at_ms": max(observed) if observed else None,
        "provenance_refs": refs,
        "missing_reasons": missing_reasons,
        "limitations": limitations,
    }


def build_anata_handoff(frame: CapitalFlowFrame, observations: Iterable[FlowObservation], *, source_errors: Iterable[str] = ()) -> dict[str, Any]:
    raw = list(observations)
    normalized = _visible_normalized(raw, as_of_ms=frame.as_of_ms)
    family_support = _family_support(frame, normalized, as_of_ms=frame.as_of_ms)
    source_evidence = _source_evidence(normalized, as_of_ms=frame.as_of_ms)
    errors = tuple(str(error) for error in source_errors)
    unavailable_statuses = {"MISSING", "CONTEXT_ONLY"}
    missing_core = [family for family in CORE_FAMILIES if family_support[family]["status"] in unavailable_statuses]
    missing_optional = [family for family in OPTIONAL_FAMILIES if family_support[family]["status"] in unavailable_statuses]
    horizons = {name: {
        "capital_inflow_score": axes.get("capital_inflow_score"), "btc_to_liquid_venues_score": axes.get("btc_to_liquid_venues_score"),
        "holder_accumulation_score": axes.get("holder_accumulation_score"), "flow_strength": axes.get("flow_strength"),
    } for name, axes in frame.horizon_axes.items()}
    causal = _causal_metadata(normalized, as_of_ms=frame.as_of_ms, source_errors=errors, missing_families=missing_core + missing_optional)
    result = {
        "schema_version": HANDOFF_SCHEMA_VERSION, "specialist": "capital_flow", "asset": "BTC", "as_of_ms": frame.as_of_ms,
        **causal,
        "known": frame.known, "flow_state": frame.flow_state,
        "axes": {"capital_inflow_score": frame.capital_inflow_score, "btc_to_liquid_venues_score": frame.btc_to_liquid_venues_score, "holder_accumulation_score": frame.holder_accumulation_score},
        "families": family_support, "horizons": horizons,
        "dynamics": {"flow_strength": frame.flow_strength, "flow_change": frame.flow_change, "flow_persistence": frame.flow_persistence},
        "quality": {"coverage": frame.coverage, "data_quality": frame.data_quality, "freshness": frame.freshness, "attribution_quality": frame.attribution_quality, "family_agreement": frame.family_agreement, "source_agreement": frame.source_agreement, "evidence_independence": frame.evidence_independence, "flow_clarity": frame.flow_clarity},
        "source_evidence": source_evidence,
        "source_evidence_semantics": {
            "selection": "newest causally visible observation per family/source/role",
            "economic_age_clock": "as_of_minus_effective_at", "availability_age_clock": "as_of_minus_available_at",
            "collector_age_clock": "as_of_minus_observed_at", "fresh_download_does_not_imply_fresh_economic_evidence": True,
            "historical_bootstrap_is_not_source_native_pit": True,
        },
        "stablecoin_context": build_stablecoin_context(raw, as_of_ms=frame.as_of_ms),
        "availability": {"missing_core_families": missing_core, "missing_optional_families": missing_optional, "source_errors_present": bool(errors)},
        "unknown_reasons": list(frame.unknown_reasons), "audit_flags": list(frame.audit_flags),
        "semantics": {"evidence_only": True, "is_price_forecast": False, "is_trade_signal": False, "is_calibrated_probability": False, "missing_is_zero": False},
        "audit_artifact": "audit_latest.json",
    }
    result["causal_quality"] = asdict(assess_handoff_quality(
        "capital_flow", result, frame_as_of_ms=frame.as_of_ms, max_age_seconds=HANDOFF_MAX_AGE_SECONDS
    ))
    return result
