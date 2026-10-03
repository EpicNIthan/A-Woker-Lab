from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

OBSERVATION_SCHEMA_VERSION = "cf-observation-v1"
SOURCE_CONTRACT_SCHEMA_VERSION = "cf-source-contract-v1"

FAMILIES = (
    "etf",
    "exchange_btc",
    "stablecoin",
    "whale_lth",
    "miner",
    "treasury",
)

ATTRIBUTION_STATUSES = (
    "DIRECT",
    "HIGH",
    "MEDIUM",
    "LOW",
    "UNKNOWN",
    "NOT_APPLICABLE",
)


def utc_now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def iso_to_ms(value: str | int | float | datetime) -> int:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("timestamp must be finite")
        # Accept seconds or milliseconds. Millisecond Unix values are already > 1e11.
        return int(number if abs(number) >= 100_000_000_000 else number * 1000)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp string is empty")
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return iso_to_ms(int(text))
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise TypeError(f"unsupported timestamp type: {type(value)!r}")

    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone information")
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def ms_to_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _quality_number(value: Any, *, name: str) -> float:
    number = _finite_number(value, name=name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


@dataclass(frozen=True, slots=True)
class SourceContract:
    """Document one provider/metric contract before it enters Capital Flow.

    This structure is intentionally descriptive rather than predictive. It records
    what a source actually supplies and the caveats required for causal replay.
    """

    provider: str
    family: str
    metric: str
    units: str
    update_cadence: str
    historical_depth: str
    availability_rule: str
    revision_behavior: str
    rate_limits: str
    access_limits: str
    missing_periods: str
    attribution_assumptions: str
    storage_license_notes: str
    fallback_behavior: str
    point_in_time_backfill_safe: bool
    notes: str = ""
    schema_version: str = SOURCE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unknown family: {self.family}")
        for name in (
            "provider",
            "metric",
            "units",
            "update_cadence",
            "historical_depth",
            "availability_rule",
            "revision_behavior",
            "rate_limits",
            "access_limits",
            "missing_periods",
            "attribution_assumptions",
            "storage_license_notes",
            "fallback_behavior",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be documented")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "family": self.family,
            "metric": self.metric,
            "units": self.units,
            "update_cadence": self.update_cadence,
            "historical_depth": self.historical_depth,
            "availability_rule": self.availability_rule,
            "revision_behavior": self.revision_behavior,
            "rate_limits": self.rate_limits,
            "access_limits": self.access_limits,
            "missing_periods": self.missing_periods,
            "attribution_assumptions": self.attribution_assumptions,
            "storage_license_notes": self.storage_license_notes,
            "fallback_behavior": self.fallback_behavior,
            "point_in_time_backfill_safe": self.point_in_time_backfill_safe,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class FlowObservation:
    family: str
    metric: str
    asset: str
    value: float
    unit: str
    effective_at_ms: int
    available_at_ms: int | None
    observed_at_ms: int
    source: str
    source_record_id: str
    revision: str = "1"
    cadence_seconds: int | None = None
    attribution_status: str = "NOT_APPLICABLE"
    attribution_quality: float | None = None
    data_quality: float = 1.0
    economic_event_id: str | None = None
    dependence_group: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unknown family: {self.family}")
        if not self.metric.strip():
            raise ValueError("metric is required")
        if not self.asset.strip():
            raise ValueError("asset/currency is required")
        if not self.unit.strip():
            raise ValueError("unit is required")
        if not self.source.strip() or not self.source_record_id.strip():
            raise ValueError("source and source_record_id are required")
        if self.attribution_status not in ATTRIBUTION_STATUSES:
            raise ValueError(f"unknown attribution_status: {self.attribution_status}")

        object.__setattr__(self, "value", _finite_number(self.value, name="value"))
        object.__setattr__(self, "data_quality", _quality_number(self.data_quality, name="data_quality"))
        if self.attribution_quality is not None:
            object.__setattr__(
                self,
                "attribution_quality",
                _quality_number(self.attribution_quality, name="attribution_quality"),
            )
        if self.cadence_seconds is not None and int(self.cadence_seconds) <= 0:
            raise ValueError("cadence_seconds must be positive when supplied")
        if self.available_at_ms is not None and self.available_at_ms > self.observed_at_ms:
            raise ValueError("available_at cannot be later than observed_at")

    @property
    def availability_known(self) -> bool:
        return self.available_at_ms is not None

    @property
    def revision_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.source_record_id, self.family, self.metric)

    @property
    def economic_key(self) -> str:
        if self.economic_event_id:
            return self.economic_event_id
        return f"{self.family}:{self.source}:{self.source_record_id}:{self.metric}"

    @property
    def observation_id(self) -> str:
        payload = {
            "schema": self.schema_version,
            "family": self.family,
            "metric": self.metric,
            "asset": self.asset,
            "value": self.value,
            "unit": self.unit,
            "effective_at_ms": self.effective_at_ms,
            "available_at_ms": self.available_at_ms,
            "observed_at_ms": self.observed_at_ms,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "revision": self.revision,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def visible_at(self, as_of_ms: int) -> bool:
        return self.available_at_ms is not None and self.available_at_ms <= int(as_of_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "family": self.family,
            "metric": self.metric,
            "asset": self.asset,
            "value": self.value,
            "unit": self.unit,
            "effective_at_ms": self.effective_at_ms,
            "effective_at": ms_to_iso(self.effective_at_ms),
            "available_at_ms": self.available_at_ms,
            "available_at": ms_to_iso(self.available_at_ms),
            "observed_at_ms": self.observed_at_ms,
            "observed_at": ms_to_iso(self.observed_at_ms),
            "source": self.source,
            "source_record_id": self.source_record_id,
            "revision": self.revision,
            "cadence_seconds": self.cadence_seconds,
            "attribution_status": self.attribution_status,
            "attribution_quality": self.attribution_quality,
            "data_quality": self.data_quality,
            "economic_event_id": self.economic_event_id,
            "dependence_group": self.dependence_group,
            "provenance": dict(self.provenance),
            "quality_flags": list(self.quality_flags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FlowObservation":
        # Explicit *_ms fields are already milliseconds and must not pass through
        # the seconds-vs-milliseconds heuristic used for generic external timestamps.
        effective = (
            int(payload["effective_at_ms"])
            if payload.get("effective_at_ms") is not None
            else iso_to_ms(payload.get("effective_at"))
        )
        observed = (
            int(payload["observed_at_ms"])
            if payload.get("observed_at_ms") is not None
            else iso_to_ms(payload.get("observed_at"))
        )
        if payload.get("available_at_ms") is not None:
            available = int(payload["available_at_ms"])
        elif payload.get("available_at") in (None, ""):
            available = None
        else:
            available = iso_to_ms(payload.get("available_at"))
        return cls(
            family=str(payload["family"]),
            metric=str(payload["metric"]),
            asset=str(payload.get("asset") or payload.get("currency") or "BTC"),
            value=float(payload["value"]),
            unit=str(payload["unit"]),
            effective_at_ms=effective,
            available_at_ms=available,
            observed_at_ms=observed,
            source=str(payload["source"]),
            source_record_id=str(payload["source_record_id"]),
            revision=str(payload.get("revision", payload.get("source_version", "1"))),
            cadence_seconds=(
                None if payload.get("cadence_seconds") in (None, "") else int(payload["cadence_seconds"])
            ),
            attribution_status=str(payload.get("attribution_status", "NOT_APPLICABLE")),
            attribution_quality=(
                None
                if payload.get("attribution_quality") in (None, "")
                else float(payload["attribution_quality"])
            ),
            data_quality=float(payload.get("data_quality", 1.0)),
            economic_event_id=(
                None if payload.get("economic_event_id") in (None, "") else str(payload["economic_event_id"])
            ),
            dependence_group=(
                None if payload.get("dependence_group") in (None, "") else str(payload["dependence_group"])
            ),
            provenance=dict(payload.get("provenance") or {}),
            quality_flags=tuple(str(x) for x in (payload.get("quality_flags") or ())),
        )


def point_in_time_filter(
    observations: Iterable[FlowObservation],
    as_of_ms: int,
) -> list[FlowObservation]:
    """Return only observations legally available at `as_of_ms`.

    Unknown availability is excluded instead of guessed. This is the central
    anti-leakage rule for live and historical reconstruction.
    """

    return [obs for obs in observations if obs.visible_at(as_of_ms)]
