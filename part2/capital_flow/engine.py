from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .contracts import FAMILIES, FlowObservation, point_in_time_filter
from .features import FEATURE_SCHEMA_VERSION, HORIZONS_MS, FamilyHorizonState, build_all_family_states
from .normalization import normalize_and_dedup

ENGINE_SCHEMA_VERSION = "cf-engine-v1"

CORE_FAMILIES = ("etf", "exchange_btc", "stablecoin")
OPTIONAL_FAMILIES = ("whale_lth", "miner", "treasury")

PREFERRED_HORIZONS: Mapping[str, tuple[str, ...]] = {
    "etf": ("7d", "3d", "24h", "30d"),
    "exchange_btc": ("24h", "4h", "3d", "7d"),
    "stablecoin": ("7d", "3d", "30d", "24h"),
    "whale_lth": ("7d", "3d", "30d", "24h"),
    "miner": ("7d", "3d", "30d", "24h"),
    "treasury": ("30d", "7d", "3d", "24h"),
}

STALE_AFTER_SECONDS: Mapping[str, float] = {
    "etf": 3 * 86400.0,
    "exchange_btc": 12 * 3600.0,
    "stablecoin": 3 * 86400.0,
    "whale_lth": 3 * 86400.0,
    "miner": 3 * 86400.0,
    "treasury": 45 * 86400.0,
}

FLOW_STATE_DEADZONE = 0.15


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _median(values: Iterable[float | None]) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    mid = len(clean) // 2
    return clean[mid] if len(clean) % 2 else (clean[mid - 1] + clean[mid]) / 2.0


def _clamp(value: float | None, low: float = -1.0, high: float = 1.0) -> float | None:
    if value is None:
        return None
    return max(low, min(high, float(value)))


@dataclass(frozen=True, slots=True)
class CapitalFlowFrame:
    as_of_ms: int
    family_states: Mapping[str, Mapping[str, FamilyHorizonState]]
    family_scores: Mapping[str, float | None]
    horizon_axes: Mapping[str, Mapping[str, float | None]]
    capital_inflow_score: float | None
    btc_to_liquid_venues_score: float | None
    holder_accumulation_score: float | None
    flow_state: str
    flow_strength: float | None
    flow_change: float | None
    flow_persistence: float | None
    family_agreement: float | None
    family_conflict: float | None
    evidence_overlap: float | None
    evidence_independence: float | None
    coverage: float
    data_quality: float | None
    freshness: float | None
    attribution_quality: float | None
    source_agreement: float | None
    flow_clarity: float | None
    known: bool
    unknown_reasons: tuple[str, ...]
    audit_flags: tuple[str, ...]
    dedup_decisions: tuple[Mapping[str, str], ...]
    visible_observation_count: int
    normalized_observation_count: int
    source_feature_schema_version: str = FEATURE_SCHEMA_VERSION
    schema_version: str = ENGINE_SCHEMA_VERSION

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_feature_schema_version": self.source_feature_schema_version,
            "as_of_ms": self.as_of_ms,
            "known": self.known,
            "flow_state": self.flow_state,
            "axes": {
                "capital_inflow_score": self.capital_inflow_score,
                "btc_to_liquid_venues_score": self.btc_to_liquid_venues_score,
                "holder_accumulation_score": self.holder_accumulation_score,
            },
            "horizon_axes": {name: dict(values) for name, values in self.horizon_axes.items()},
            "family_scores": dict(self.family_scores),
            "family_states": {
                family: {horizon: state.to_dict() for horizon, state in states.items()}
                for family, states in self.family_states.items()
            },
            "flow_strength": self.flow_strength,
            "flow_change": self.flow_change,
            "flow_persistence": self.flow_persistence,
            "family_agreement": self.family_agreement,
            "family_conflict": self.family_conflict,
            "evidence_overlap": self.evidence_overlap,
            "evidence_independence": self.evidence_independence,
            "coverage": self.coverage,
            "data_quality": self.data_quality,
            "freshness": self.freshness,
            "attribution_quality": self.attribution_quality,
            "source_agreement": self.source_agreement,
            "flow_clarity": self.flow_clarity,
            "unknown_reasons": list(self.unknown_reasons),
            "audit_flags": list(self.audit_flags),
            "dedup_decisions": [dict(item) for item in self.dedup_decisions],
            "visible_observation_count": self.visible_observation_count,
            "normalized_observation_count": self.normalized_observation_count,
        }


class CapitalFlowEngine:
    """Deterministic, point-in-time-safe Capital Flow V0 engine."""

    def build(self, observations: Iterable[FlowObservation], *, as_of_ms: int) -> CapitalFlowFrame:
        raw = list(observations)
        visible = point_in_time_filter(raw, as_of_ms)
        normalized, dedup_decisions = normalize_and_dedup(visible)
        # A record may become available before its effective period. Capital Flow
        # states describe flows effective by T, so future-effective records are not
        # treated as completed flow evidence here.
        normalized = [obs for obs in normalized if obs.effective_at_ms <= as_of_ms]

        family_states = build_all_family_states(normalized, as_of_ms)
        family_scores = {
            family: self._preferred_family_score(family, states)
            for family, states in family_states.items()
        }
        horizon_axes = {
            horizon: self._axis_scores_for_horizon(family_states, horizon)
            for horizon in HORIZONS_MS
        }

        preferred_axes = self._preferred_axes(horizon_axes)
        capital_inflow = preferred_axes["capital_inflow_score"]
        liquid = preferred_axes["btc_to_liquid_venues_score"]
        holder = preferred_axes["holder_accumulation_score"]

        agreement, conflict = self._agreement(family_scores)
        independence, overlap, dependence_flags = self._evidence_dependence(family_states)
        flow_strength = _mean(abs(value) if value is not None else None for value in family_scores.values())
        flow_persistence = self._preferred_persistence(family_states)
        flow_change = self._flow_change(horizon_axes)
        coverage = self._coverage(family_states)
        data_quality = self._data_quality(family_states)
        freshness, stale_core = self._freshness(normalized, as_of_ms)
        attribution_quality = self._attribution_quality(family_states)
        flow_clarity = self._flow_clarity(agreement, independence, family_scores)

        flow_state = self._classify_flow_state(capital_inflow, liquid, holder)
        unknown_reasons: list[str] = []
        if coverage < 2 / 3:
            unknown_reasons.append("INSUFFICIENT_SOURCE_COVERAGE")
        if stale_core:
            unknown_reasons.append("STALE_CORE_SOURCES")
        if not any(value is not None for value in family_scores.values()):
            unknown_reasons.append("INSUFFICIENT_HISTORY")
        if capital_inflow is None and liquid is None and holder is None:
            unknown_reasons.append("LOW_FLOW_CLARITY")
        if not any(
            any(state.known for state in family_states[family].values())
            for family in CORE_FAMILIES
        ):
            unknown_reasons.append("NO_RELIABLE_CORE_FAMILY")

        # Lack of normalized historical score does not erase the existence of raw
        # evidence, but V0 refuses to fabricate a compact directional magnitude.
        known = coverage >= 2 / 3 and any(value is not None for value in family_scores.values()) and not stale_core
        if not known:
            flow_state = "UNKNOWN"

        audit_flags: list[str] = list(dependence_flags)
        if any(obs.available_at_ms is None for obs in raw):
            audit_flags.append("UNKNOWN_AVAILABILITY_RECORDS_EXCLUDED")
        if dedup_decisions:
            audit_flags.append("DUPLICATE_ECONOMIC_EVENTS_SUPPRESSED")
        missing_optional = [
            family
            for family in OPTIONAL_FAMILIES
            if not any(state.known for state in family_states[family].values())
        ]
        if missing_optional:
            audit_flags.append("OPTIONAL_FAMILIES_MISSING:" + ",".join(missing_optional))
        if conflict is not None and conflict > 0:
            audit_flags.append("CROSS_FAMILY_CONFLICT_PRESENT")

        return CapitalFlowFrame(
            as_of_ms=int(as_of_ms),
            family_states=family_states,
            family_scores=family_scores,
            horizon_axes=horizon_axes,
            capital_inflow_score=capital_inflow,
            btc_to_liquid_venues_score=liquid,
            holder_accumulation_score=holder,
            flow_state=flow_state,
            flow_strength=flow_strength,
            flow_change=flow_change,
            flow_persistence=flow_persistence,
            family_agreement=agreement,
            family_conflict=conflict,
            evidence_overlap=overlap,
            evidence_independence=independence,
            coverage=coverage,
            data_quality=data_quality,
            freshness=freshness,
            attribution_quality=attribution_quality,
            source_agreement=agreement,
            flow_clarity=flow_clarity,
            known=known,
            unknown_reasons=tuple(dict.fromkeys(unknown_reasons)),
            audit_flags=tuple(dict.fromkeys(audit_flags)),
            dedup_decisions=tuple(dedup_decisions),
            visible_observation_count=len(visible),
            normalized_observation_count=len(normalized),
        )

    @staticmethod
    def _preferred_family_score(
        family: str, states: Mapping[str, FamilyHorizonState]
    ) -> float | None:
        for horizon in PREFERRED_HORIZONS[family]:
            value = states[horizon].direction_score
            if value is not None:
                return _clamp(value)
        return None

    @staticmethod
    def _axis_scores_for_horizon(
        family_states: Mapping[str, Mapping[str, FamilyHorizonState]], horizon: str
    ) -> dict[str, float | None]:
        axis_values: dict[str, list[float]] = {
            "CAPITAL": [],
            "LIQUID_VENUES": [],
            "HOLDER": [],
        }
        for states in family_states.values():
            state = states[horizon]
            for feature in state.metric_features:
                if feature.direction_score is not None:
                    axis_values[feature.axis].append(feature.direction_score)
        return {
            "capital_inflow_score": _clamp(_median(axis_values["CAPITAL"])),
            "btc_to_liquid_venues_score": _clamp(_median(axis_values["LIQUID_VENUES"])),
            "holder_accumulation_score": _clamp(_median(axis_values["HOLDER"])),
            "flow_strength": _mean(
                abs(value)
                for values in axis_values.values()
                for value in values
            ),
        }

    @staticmethod
    def _preferred_axes(horizon_axes: Mapping[str, Mapping[str, float | None]]) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for axis in (
            "capital_inflow_score",
            "btc_to_liquid_venues_score",
            "holder_accumulation_score",
        ):
            result[axis] = None
            for horizon in ("7d", "3d", "24h", "30d", "4h", "1h"):
                value = horizon_axes[horizon][axis]
                if value is not None:
                    result[axis] = value
                    break
        return result

    @staticmethod
    def _agreement(family_scores: Mapping[str, float | None]) -> tuple[float | None, float | None]:
        # Family score signs are axis-local. Positive exchange_btc means more BTC
        # toward liquid venues (distribution orientation), while positive ETF,
        # stablecoin, whale/miner/treasury scores are accumulation orientation.
        # Convert to one semantic orientation only for agreement/conflict counting.
        orientation_multiplier = {
            "etf": 1.0,
            "stablecoin": 1.0,
            "exchange_btc": -1.0,
            "whale_lth": 1.0,
            "miner": 1.0,
            "treasury": 1.0,
        }
        signs: list[int] = []
        for family, value in family_scores.items():
            if value is None:
                continue
            oriented = value * orientation_multiplier.get(family, 1.0)
            if abs(oriented) <= FLOW_STATE_DEADZONE:
                continue
            signs.append(1 if oriented > 0 else -1)
        if not signs:
            return None, None
        positive = sum(1 for sign in signs if sign > 0)
        negative = len(signs) - positive
        agreement = max(positive, negative) / len(signs)
        conflict = min(positive, negative) / len(signs)
        return agreement, conflict

    @staticmethod
    def _evidence_dependence(
        family_states: Mapping[str, Mapping[str, FamilyHorizonState]]
    ) -> tuple[float | None, float | None, tuple[str, ...]]:
        # Use one preferred horizon per family so repeated 24h/3d/7d windows do not
        # themselves count as independent evidence.
        groups: list[tuple[str, str]] = []
        participating = 0
        for family, states in family_states.items():
            chosen: FamilyHorizonState | None = None
            for horizon in PREFERRED_HORIZONS[family]:
                state = states[horizon]
                if state.direction_score is not None:
                    chosen = state
                    break
            if chosen is None:
                continue
            participating += 1
            if chosen.dependence_groups:
                for group in chosen.dependence_groups:
                    groups.append((family, group))
            else:
                # No declared overlap is treated as family-local evidence, but the
                # audit flag below makes clear this is only explicit-dependence V0.
                groups.append((family, f"implicit-family:{family}"))

        if participating <= 1:
            return (1.0 if participating == 1 else None, 0.0 if participating == 1 else None, ("DEPENDENCE_ONLY_EXPLICIT",))

        group_to_families: dict[str, set[str]] = {}
        for family, group in groups:
            group_to_families.setdefault(group, set()).add(family)
        overlap_pairs = sum(max(0, len(families) - 1) for families in group_to_families.values())
        max_overlap = max(1, participating - 1)
        overlap = min(1.0, overlap_pairs / max_overlap)
        independence = 1.0 - overlap
        return independence, overlap, ("DEPENDENCE_ONLY_EXPLICIT",)

    @staticmethod
    def _preferred_persistence(
        family_states: Mapping[str, Mapping[str, FamilyHorizonState]]
    ) -> float | None:
        values: list[float] = []
        for family, states in family_states.items():
            for horizon in PREFERRED_HORIZONS[family]:
                state = states[horizon]
                if state.persistence is not None and state.known:
                    values.append(state.persistence)
                    break
        return _mean(values)

    @staticmethod
    def _flow_change(horizon_axes: Mapping[str, Mapping[str, float | None]]) -> float | None:
        for short_h, long_h in (("24h", "7d"), ("3d", "30d"), ("4h", "24h")):
            diffs: list[float] = []
            for axis in (
                "capital_inflow_score",
                "btc_to_liquid_venues_score",
                "holder_accumulation_score",
            ):
                short = horizon_axes[short_h][axis]
                long = horizon_axes[long_h][axis]
                if short is not None and long is not None:
                    diffs.append(short - long)
            if diffs:
                return _clamp(_mean(diffs))
        return None

    @staticmethod
    def _coverage(family_states: Mapping[str, Mapping[str, FamilyHorizonState]]) -> float:
        present = sum(
            1
            for family in CORE_FAMILIES
            if any(state.known for state in family_states[family].values())
        )
        return present / len(CORE_FAMILIES)

    @staticmethod
    def _data_quality(family_states: Mapping[str, Mapping[str, FamilyHorizonState]]) -> float | None:
        values: list[float] = []
        for family, states in family_states.items():
            for horizon in PREFERRED_HORIZONS[family]:
                value = states[horizon].data_quality
                if value is not None and states[horizon].known:
                    values.append(value)
                    break
        return _mean(values)

    @staticmethod
    def _freshness(observations: list[FlowObservation], as_of_ms: int) -> tuple[float | None, bool]:
        family_scores: list[float] = []
        stale_core = False
        for family in FAMILIES:
            family_obs = [obs for obs in observations if obs.family == family and obs.available_at_ms is not None]
            if not family_obs:
                continue
            latest_effective = max(obs.effective_at_ms for obs in family_obs)
            age = max(0.0, (as_of_ms - latest_effective) / 1000.0)
            limit = STALE_AFTER_SECONDS[family]
            freshness = max(0.0, 1.0 - age / limit)
            family_scores.append(freshness)
            if family in CORE_FAMILIES and age > limit:
                stale_core = True
        return _mean(family_scores), stale_core

    @staticmethod
    def _attribution_quality(
        family_states: Mapping[str, Mapping[str, FamilyHorizonState]]
    ) -> float | None:
        values: list[float] = []
        for family in ("exchange_btc", "whale_lth", "miner"):
            for horizon in PREFERRED_HORIZONS[family]:
                value = family_states[family][horizon].attribution_quality
                if value is not None:
                    values.append(value)
                    break
        return _mean(values)

    @staticmethod
    def _flow_clarity(
        agreement: float | None,
        independence: float | None,
        family_scores: Mapping[str, float | None],
    ) -> float | None:
        directional = sum(1 for value in family_scores.values() if value is not None and abs(value) > FLOW_STATE_DEADZONE)
        if directional == 0:
            return None
        support = min(1.0, directional / 3.0)
        values = [support]
        if agreement is not None:
            values.append(agreement)
        if independence is not None:
            values.append(independence)
        return _mean(values)

    @staticmethod
    def _classify_flow_state(
        capital: float | None,
        liquid: float | None,
        holder: float | None,
    ) -> str:
        axes = [value for value in (capital, liquid, holder) if value is not None]
        if not axes:
            return "UNKNOWN"
        if all(abs(value) <= FLOW_STATE_DEADZONE for value in axes):
            return "NEUTRAL"

        accumulation = False
        distribution = False
        if capital is not None:
            accumulation |= capital > FLOW_STATE_DEADZONE
            distribution |= capital < -FLOW_STATE_DEADZONE
        if holder is not None:
            accumulation |= holder > FLOW_STATE_DEADZONE
            distribution |= holder < -FLOW_STATE_DEADZONE
        if liquid is not None:
            # More BTC toward liquid venues is supply-location distribution
            # evidence; movement away is accumulation/cold-storage evidence.
            accumulation |= liquid < -FLOW_STATE_DEADZONE
            distribution |= liquid > FLOW_STATE_DEADZONE

        if accumulation and distribution:
            return "MIXED"
        if accumulation:
            return "ACCUMULATION_BIASED"
        if distribution:
            return "DISTRIBUTION_BIASED"
        return "NEUTRAL"
