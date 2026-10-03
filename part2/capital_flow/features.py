from __future__ import annotations

from dataclasses import dataclass
from math import copysign
import math
import statistics
from typing import Any, Iterable, Mapping, Sequence

from .contracts import FlowObservation

FEATURE_SCHEMA_VERSION = "cf-features-v1"

HORIZONS_MS: dict[str, int] = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "3d": 3 * 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
}

MIN_TRAILING_WINDOWS = 5
MAX_TRAILING_WINDOWS = 30


@dataclass(frozen=True, slots=True)
class MetricSpec:
    metric: str
    mode: str  # FLOW or LEVEL
    axis: str  # CAPITAL, LIQUID_VENUES, HOLDER
    direction_multiplier: float = 1.0


FAMILY_METRICS: Mapping[str, tuple[MetricSpec, ...]] = {
    "etf": (MetricSpec("net_flow_usd", "FLOW", "CAPITAL", 1.0),),
    "exchange_btc": (
        MetricSpec("btc_netflow", "FLOW", "LIQUID_VENUES", 1.0),
        MetricSpec("reserve_btc", "LEVEL", "LIQUID_VENUES", 1.0),
    ),
    "stablecoin": (
        MetricSpec("supply_change_usd", "FLOW", "CAPITAL", 1.0),
        MetricSpec("supply_usd", "LEVEL", "CAPITAL", 1.0),
    ),
    "whale_lth": (
        MetricSpec("holder_balance_btc", "LEVEL", "HOLDER", 1.0),
        # Kote's whale-to-exchange chart is an inflow-only metric, not netflow.
        # More whale BTC arriving at labeled exchanges is therefore negative for
        # the holder-accumulation axis; preserve the source semantic explicitly.
        MetricSpec("holder_exchange_inflow_btc", "FLOW", "HOLDER", -1.0),
    ),
    "miner": (
        MetricSpec("miner_reserve_btc", "LEVEL", "HOLDER", 1.0),
        MetricSpec("miner_exchange_netflow_btc", "FLOW", "HOLDER", -1.0),
    ),
    "treasury": (MetricSpec("treasury_holdings_btc", "LEVEL", "HOLDER", 1.0),),
}


@dataclass(frozen=True, slots=True)
class MetricWindowFeature:
    family: str
    metric: str
    horizon: str
    axis: str
    current_value: float | None
    change: float | None
    acceleration: float | None
    anomaly_score: float | None
    magnitude_percentile: float | None
    direction_score: float | None
    persistence: float | None
    reversal_state: str
    age_seconds: float | None
    data_quality: float | None
    attribution_quality: float | None
    observation_count: int
    source_count: int
    dependence_groups: tuple[str, ...]
    quality_flags: tuple[str, ...]

    @property
    def known(self) -> bool:
        return self.current_value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "metric": self.metric,
            "horizon": self.horizon,
            "axis": self.axis,
            "current_value": self.current_value,
            "change": self.change,
            "acceleration": self.acceleration,
            "anomaly_score": self.anomaly_score,
            "magnitude_percentile": self.magnitude_percentile,
            "direction_score": self.direction_score,
            "persistence": self.persistence,
            "reversal_state": self.reversal_state,
            "age_seconds": self.age_seconds,
            "data_quality": self.data_quality,
            "attribution_quality": self.attribution_quality,
            "observation_count": self.observation_count,
            "source_count": self.source_count,
            "dependence_groups": list(self.dependence_groups),
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class FamilyHorizonState:
    family: str
    horizon: str
    known: bool
    direction_score: float | None
    strength: float | None
    change: float | None
    persistence: float | None
    anomaly_score: float | None
    reversal_state: str
    age_seconds: float | None
    data_quality: float | None
    attribution_quality: float | None
    coverage: float
    source_count: int
    evidence_count: int
    dependence_groups: tuple[str, ...]
    metric_features: tuple[MetricWindowFeature, ...]
    unknown_reasons: tuple[str, ...]
    audit_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "horizon": self.horizon,
            "known": self.known,
            "direction_score": self.direction_score,
            "strength": self.strength,
            "change": self.change,
            "persistence": self.persistence,
            "anomaly_score": self.anomaly_score,
            "reversal_state": self.reversal_state,
            "age_seconds": self.age_seconds,
            "data_quality": self.data_quality,
            "attribution_quality": self.attribution_quality,
            "coverage": self.coverage,
            "source_count": self.source_count,
            "evidence_count": self.evidence_count,
            "dependence_groups": list(self.dependence_groups),
            "unknown_reasons": list(self.unknown_reasons),
            "audit_flags": list(self.audit_flags),
            "metric_features": [feature.to_dict() for feature in self.metric_features],
        }


def _sign(value: float | None, eps: float = 1e-15) -> int:
    if value is None or abs(value) <= eps:
        return 0
    return 1 if value > 0 else -1


def _median_or_none(values: Iterable[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.median(clean) if clean else None


def _mean_or_none(values: Iterable[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(clean) / len(clean) if clean else None


def _robust_z(value: float, history: Sequence[float]) -> float | None:
    if len(history) < MIN_TRAILING_WINDOWS:
        return None
    median = statistics.median(history)
    deviations = [abs(x - median) for x in history]
    mad = statistics.median(deviations)
    if mad <= 1e-15:
        return 0.0 if abs(value - median) <= 1e-15 else copysign(8.0, value - median)
    return max(-8.0, min(8.0, (value - median) / (1.4826 * mad)))


def _magnitude_percentile(value: float, history: Sequence[float]) -> float | None:
    if len(history) < MIN_TRAILING_WINDOWS:
        return None
    magnitude = abs(value)
    hist = [abs(x) for x in history]
    less = sum(1 for x in hist if x < magnitude)
    equal = sum(1 for x in hist if x == magnitude)
    return (less + 0.5 * equal) / len(hist)


def _supports_horizon(observations: Sequence[FlowObservation], horizon_ms: int) -> bool:
    cadences = [obs.cadence_seconds for obs in observations if obs.cadence_seconds]
    if not cadences:
        return True
    return min(cadences) * 1000 <= horizon_ms


def _flow_window(observations: Sequence[FlowObservation], start_ms: int, end_ms: int) -> tuple[float | None, list[FlowObservation]]:
    used = [obs for obs in observations if start_ms < obs.effective_at_ms <= end_ms]
    if not used:
        return None, []
    return sum(obs.value for obs in used), used


def _level_window(observations: Sequence[FlowObservation], start_ms: int, end_ms: int) -> tuple[float | None, list[FlowObservation]]:
    ordered = sorted((obs for obs in observations if obs.effective_at_ms <= end_ms), key=lambda x: x.effective_at_ms)
    if len(ordered) < 2:
        return None, []
    end_obs = ordered[-1]
    baseline_candidates = [obs for obs in ordered if obs.effective_at_ms <= start_ms]
    if not baseline_candidates:
        return None, []
    start_obs = baseline_candidates[-1]
    cadence_ms_values = [obs.cadence_seconds * 1000 for obs in (start_obs, end_obs) if obs.cadence_seconds]
    if cadence_ms_values:
        tolerance_ms = 2 * max(cadence_ms_values)
        if start_ms - start_obs.effective_at_ms > tolerance_ms:
            return None, []
        if end_ms - end_obs.effective_at_ms > tolerance_ms:
            return None, []
    return end_obs.value - start_obs.value, [start_obs, end_obs]


def _window_value(spec: MetricSpec, observations: Sequence[FlowObservation], start_ms: int, end_ms: int) -> tuple[float | None, list[FlowObservation]]:
    if spec.mode == "FLOW":
        return _flow_window(observations, start_ms, end_ms)
    if spec.mode == "LEVEL":
        return _level_window(observations, start_ms, end_ms)
    raise ValueError(f"unknown metric mode: {spec.mode}")


def _trailing_window_values(spec: MetricSpec, observations: Sequence[FlowObservation], as_of_ms: int, horizon_ms: int, count: int = MAX_TRAILING_WINDOWS) -> list[float]:
    values: list[float] = []
    for offset in range(1, count + 1):
        end = as_of_ms - offset * horizon_ms
        start = end - horizon_ms
        value, _ = _window_value(spec, observations, start, end)
        if value is not None:
            values.append(value * spec.direction_multiplier)
    values.reverse()
    return values


def _persistence(spec: MetricSpec, observations: Sequence[FlowObservation], start_ms: int, end_ms: int, current_signed: float) -> float | None:
    current_sign = _sign(current_signed)
    if current_sign == 0:
        return 0.0
    if spec.mode == "FLOW":
        seq = [obs.value * spec.direction_multiplier for obs in observations if start_ms < obs.effective_at_ms <= end_ms]
    else:
        ordered = sorted((obs for obs in observations if start_ms <= obs.effective_at_ms <= end_ms), key=lambda x: x.effective_at_ms)
        seq = [(b.value - a.value) * spec.direction_multiplier for a, b in zip(ordered, ordered[1:])]
    signs = [_sign(value) for value in seq if _sign(value) != 0]
    if not signs:
        return None
    same = sum(1 for sign in signs if sign == current_sign)
    consistency = same / len(signs)
    sample_support = min(1.0, len(signs) / 3.0)
    return consistency * sample_support


def build_metric_feature(family: str, spec: MetricSpec, observations: Sequence[FlowObservation], as_of_ms: int, horizon: str) -> MetricWindowFeature:
    horizon_ms = HORIZONS_MS[horizon]
    metric_obs = [obs for obs in observations if obs.family == family and obs.metric == spec.metric and obs.effective_at_ms <= as_of_ms]
    metric_obs.sort(key=lambda x: (x.effective_at_ms, x.available_at_ms or -1, x.observed_at_ms))
    flags: list[str] = []
    if not metric_obs:
        return MetricWindowFeature(family, spec.metric, horizon, spec.axis, None, None, None, None, None, None, None, "UNKNOWN", None, None, None, 0, 0, (), ("NO_OBSERVATIONS",))
    if not _supports_horizon(metric_obs, horizon_ms):
        latest = metric_obs[-1]
        return MetricWindowFeature(family, spec.metric, horizon, spec.axis, None, None, None, None, None, None, None, "UNSUPPORTED_HORIZON", max(0.0, (as_of_ms - latest.effective_at_ms) / 1000.0), latest.data_quality, latest.attribution_quality, 0, len({obs.source for obs in metric_obs}), tuple(sorted({obs.dependence_group for obs in metric_obs if obs.dependence_group})), ("SOURCE_CADENCE_TOO_SLOW_FOR_HORIZON",))
    current, used = _window_value(spec, metric_obs, as_of_ms - horizon_ms, as_of_ms)
    if current is None:
        latest = metric_obs[-1]
        return MetricWindowFeature(family, spec.metric, horizon, spec.axis, None, None, None, None, None, None, None, "UNKNOWN", max(0.0, (as_of_ms - latest.effective_at_ms) / 1000.0), latest.data_quality, latest.attribution_quality, 0, len({obs.source for obs in metric_obs}), tuple(sorted({obs.dependence_group for obs in metric_obs if obs.dependence_group})), ("INSUFFICIENT_WINDOW_DATA",))
    signed_current = current * spec.direction_multiplier
    previous, _ = _window_value(spec, metric_obs, as_of_ms - 2 * horizon_ms, as_of_ms - horizon_ms)
    previous2, _ = _window_value(spec, metric_obs, as_of_ms - 3 * horizon_ms, as_of_ms - 2 * horizon_ms)
    signed_previous = None if previous is None else previous * spec.direction_multiplier
    signed_previous2 = None if previous2 is None else previous2 * spec.direction_multiplier
    change = None if signed_previous is None else signed_current - signed_previous
    previous_change = None if signed_previous is None or signed_previous2 is None else signed_previous - signed_previous2
    acceleration = None if change is None or previous_change is None else change - previous_change
    history = _trailing_window_values(spec, metric_obs, as_of_ms, horizon_ms)
    anomaly = _robust_z(signed_current, history)
    magnitude_pct = _magnitude_percentile(signed_current, history)
    if magnitude_pct is None:
        direction_score = None
        flags.append("INSUFFICIENT_TRAILING_HISTORY")
    else:
        direction_score = _sign(signed_current) * magnitude_pct
    persistence = _persistence(spec, metric_obs, as_of_ms - horizon_ms, as_of_ms, signed_current)
    current_sign = _sign(signed_current)
    prev_signs = [_sign(value) for value in (signed_previous, signed_previous2) if value is not None and _sign(value) != 0]
    if current_sign == 0:
        reversal = "NEUTRAL"
    elif len(prev_signs) >= 2 and all(sign == -current_sign for sign in prev_signs[-2:]):
        reversal = "REVERSAL"
    elif prev_signs and prev_signs[-1] == current_sign:
        reversal = "CONTINUATION"
    else:
        reversal = "NONE"
    newest = max(used, key=lambda x: x.effective_at_ms)
    age_seconds = max(0.0, (as_of_ms - newest.effective_at_ms) / 1000.0)
    data_quality = _mean_or_none(obs.data_quality for obs in used)
    attribution_quality = _mean_or_none(obs.attribution_quality for obs in used)
    dependence_groups = tuple(sorted({obs.dependence_group for obs in used if obs.dependence_group}))
    return MetricWindowFeature(family, spec.metric, horizon, spec.axis, signed_current, change, acceleration, anomaly, magnitude_pct, direction_score, persistence, reversal, age_seconds, data_quality, attribution_quality, len(used), len({obs.source for obs in used}), dependence_groups, tuple(flags))


def build_family_horizon_state(family: str, observations: Sequence[FlowObservation], as_of_ms: int, horizon: str) -> FamilyHorizonState:
    specs = FAMILY_METRICS.get(family, ())
    metric_features = tuple(build_metric_feature(family, spec, observations, as_of_ms, horizon) for spec in specs)
    known_features = [feature for feature in metric_features if feature.current_value is not None]
    scored_features = [feature for feature in known_features if feature.direction_score is not None]
    unknown_reasons: list[str] = []
    if not known_features:
        unknown_reasons.append("NO_SUPPORTED_WINDOW_DATA")
    if known_features and not scored_features:
        unknown_reasons.append("INSUFFICIENT_HISTORY_FOR_NORMALIZED_SCORE")
    direction_score = _median_or_none(feature.direction_score for feature in scored_features)
    strength = _mean_or_none(abs(feature.direction_score) if feature.direction_score is not None else None for feature in scored_features)
    change = _median_or_none(feature.change for feature in known_features)
    persistence = _mean_or_none(feature.persistence for feature in known_features)
    anomaly = _median_or_none(feature.anomaly_score for feature in known_features)
    age = min((feature.age_seconds for feature in known_features if feature.age_seconds is not None), default=None)
    data_quality = _mean_or_none(feature.data_quality for feature in known_features)
    attribution_quality = _mean_or_none(feature.attribution_quality for feature in known_features)
    source_count = len({obs.source for obs in observations if obs.family == family and obs.effective_at_ms <= as_of_ms})
    dependence_groups = tuple(sorted({group for feature in known_features for group in feature.dependence_groups}))
    reversals = {feature.reversal_state for feature in known_features}
    if "REVERSAL" in reversals:
        reversal_state = "REVERSAL"
    elif reversals == {"CONTINUATION"}:
        reversal_state = "CONTINUATION"
    elif known_features:
        reversal_state = "MIXED" if len(reversals) > 1 else next(iter(reversals))
    else:
        reversal_state = "UNKNOWN"
    supported_metric_count = len(known_features)
    coverage = supported_metric_count / len(specs) if specs else 0.0
    audit_flags = tuple(dict.fromkeys(flag for feature in metric_features for flag in feature.quality_flags))
    return FamilyHorizonState(family, horizon, bool(known_features), direction_score, strength, change, persistence, anomaly, reversal_state, age, data_quality, attribution_quality, coverage, source_count, sum(feature.observation_count for feature in known_features), dependence_groups, metric_features, tuple(unknown_reasons), audit_flags)


def build_all_family_states(observations: Sequence[FlowObservation], as_of_ms: int) -> dict[str, dict[str, FamilyHorizonState]]:
    return {family: {horizon: build_family_horizon_state(family, observations, as_of_ms, horizon) for horizon in HORIZONS_MS} for family in FAMILY_METRICS}
