from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Iterable

from .contracts import FlowObservation

# Canonical metric aliases intentionally cover only semantics that are known to be
# equivalent. A provider-specific metric should remain provider-specific unless its
# meaning has been reviewed.
METRIC_ALIASES = {
    "etf_net_flow_usd": "net_flow_usd",
    "netflow_usd": "net_flow_usd",
    "btc_exchange_netflow": "btc_netflow",
    "exchange_btc_netflow": "btc_netflow",
    "exchange_reserve_btc": "reserve_btc",
    "stablecoin_total_supply_usd": "supply_usd",
    "stablecoin_supply_usd": "supply_usd",
    "holder_balance_btc": "holder_balance_btc",
    "miner_reserve_btc": "miner_reserve_btc",
    "treasury_holdings_btc": "treasury_holdings_btc",
}

CANONICAL_UNITS = {
    "net_flow_usd": "USD",
    "inflow_usd": "USD",
    "outflow_usd": "USD",
    "btc_inflow": "BTC",
    "btc_outflow": "BTC",
    "btc_netflow": "BTC",
    "reserve_btc": "BTC",
    "supply_usd": "USD",
    "supply_change_usd": "USD",
    "holder_balance_btc": "BTC",
    "holder_exchange_netflow_btc": "BTC",
    "miner_reserve_btc": "BTC",
    "miner_exchange_netflow_btc": "BTC",
    "treasury_holdings_btc": "BTC",
}

_UNIT_MULTIPLIERS = {
    "USD": 1.0,
    "USD_THOUSANDS": 1_000.0,
    "USD_MILLIONS": 1_000_000.0,
    "USD_BILLIONS": 1_000_000_000.0,
    "BTC": 1.0,
}


def canonical_metric(metric: str) -> str:
    key = re.sub(r"[^a-z0-9_]+", "_", metric.strip().lower()).strip("_")
    return METRIC_ALIASES.get(key, key)


def canonical_unit(unit: str) -> str:
    raw = unit.strip().upper().replace(" ", "_")
    aliases = {
        "$": "USD",
        "US_DOLLARS": "USD",
        "USD_M": "USD_MILLIONS",
        "USDM": "USD_MILLIONS",
        "MILLION_USD": "USD_MILLIONS",
        "US$M": "USD_MILLIONS",
        "USD_B": "USD_BILLIONS",
        "BTC_UNITS": "BTC",
    }
    return aliases.get(raw, raw)


def normalize_observation(obs: FlowObservation) -> FlowObservation:
    metric = canonical_metric(obs.metric)
    unit = canonical_unit(obs.unit)
    target_unit = CANONICAL_UNITS.get(metric, unit)

    value = obs.value
    if unit != target_unit:
        if target_unit == "USD" and unit in _UNIT_MULTIPLIERS:
            value = value * _UNIT_MULTIPLIERS[unit]
            unit = "USD"
        else:
            raise ValueError(
                f"unsupported unit conversion for {obs.family}.{metric}: {unit} -> {target_unit}"
            )

    if not math.isfinite(value):
        raise ValueError(
            "normalized value must remain finite"
        )

    return FlowObservation(
        family=obs.family,
        metric=metric,
        asset=obs.asset.upper(),
        value=value,
        unit=unit,
        effective_at_ms=obs.effective_at_ms,
        available_at_ms=obs.available_at_ms,
        observed_at_ms=obs.observed_at_ms,
        source=obs.source,
        source_record_id=obs.source_record_id,
        revision=obs.revision,
        cadence_seconds=obs.cadence_seconds,
        attribution_status=obs.attribution_status,
        attribution_quality=obs.attribution_quality,
        data_quality=obs.data_quality,
        economic_event_id=obs.economic_event_id,
        dependence_group=obs.dependence_group,
        provenance=obs.provenance,
        quality_flags=obs.quality_flags,
    )


def _revision_rank(revision: str) -> tuple[int, int | tuple[str, int, str] | str, str]:
    text = str(revision).strip()
    try:
        return (0, int(text), text)
    except ValueError:
        match = re.search(r"(\d+)", text)
        if match:
            prefix = text[:match.start()]
            number = int(match.group(1))
            suffix = text[match.end():]
            return (1, (prefix, number, suffix), text)
        return (2, text, text)


def select_latest_revisions(observations: Iterable[FlowObservation]) -> list[FlowObservation]:
    """Keep the latest *available* revision for each provider record identity.

    Call this only after the point-in-time filter. That ordering guarantees a
    later correction cannot replace what was known in an earlier replay state.
    """

    chosen: dict[tuple[str, str, str, str], FlowObservation] = {}
    for obs in observations:
        key = obs.revision_key
        current = chosen.get(key)
        if current is None:
            chosen[key] = obs
            continue
        candidate_rank = (
            obs.available_at_ms or -1,
            obs.observed_at_ms,
            _revision_rank(obs.revision),
        )
        current_rank = (
            current.available_at_ms or -1,
            current.observed_at_ms,
            _revision_rank(current.revision),
        )
        if candidate_rank > current_rank:
            chosen[key] = obs
    return list(chosen.values())


def suppress_duplicates(observations: Iterable[FlowObservation]) -> tuple[list[FlowObservation], list[dict[str, str]]]:
    """Suppress exact/cross-provider copies without claiming economic independence.

    - Revisions are resolved separately by `select_latest_revisions`.
    - When `economic_event_id` is shared, keep the highest quality representation.
    - Records without an explicit economic event id are not guessed to be duplicates.

    The decisions are returned for audit rather than silently discarded.
    """

    by_event: dict[tuple[str, str, str], list[FlowObservation]] = defaultdict(list)
    passthrough: list[FlowObservation] = []
    for obs in observations:
        if obs.economic_event_id:
            by_event[(obs.family, obs.metric, obs.economic_event_id)].append(obs)
        else:
            passthrough.append(obs)

    kept = list(passthrough)
    decisions: list[dict[str, str]] = []
    for key, group in by_event.items():
        group.sort(
            key=lambda x: (
                x.data_quality,
                x.attribution_quality if x.attribution_quality is not None else -1.0,
                x.observed_at_ms,
            ),
            reverse=True,
        )
        winner = group[0]
        kept.append(winner)
        for duplicate in group[1:]:
            decisions.append(
                {
                    "economic_event_id": key[2],
                    "kept_observation_id": winner.observation_id,
                    "suppressed_observation_id": duplicate.observation_id,
                    "reason": "DUPLICATE_ECONOMIC_EVENT",
                }
            )

    kept.sort(key=lambda x: (x.effective_at_ms, x.observed_at_ms, x.source, x.source_record_id))
    return kept, decisions


def normalize_and_dedup(
    observations: Iterable[FlowObservation],
) -> tuple[list[FlowObservation], list[dict[str, str]]]:
    normalized = [normalize_observation(obs) for obs in observations]
    revised = select_latest_revisions(normalized)
    return suppress_duplicates(revised)
