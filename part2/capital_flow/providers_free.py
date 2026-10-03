from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import FlowObservation, SourceContract, iso_to_ms, utc_now_ms

KOTE_BASE_URL = "https://kotecharts.com/api/v1/public/charts"

KOTE_EXCHANGE_CONTRACT = SourceContract(
    provider="Kote Charts free API",
    family="exchange_btc",
    metric="btc_netflow / reserve_btc",
    units="BTC",
    update_cadence="daily closed UTC buckets; partial current day excluded",
    historical_depth="provider chart history subject to endpoint retention/limits",
    availability_rule=(
        "Kote does not expose original per-row publication timestamps in the documented chart series. "
        "Capital Flow therefore uses available_at=first local observation for every fetched revision. "
        "Historical bootstrap rows may support the current state after bootstrap but are never replayed earlier."
    ),
    revision_behavior=(
        "Entity labels can change as wallets are reorganized; changed historical values are appended as later "
        "locally observed revisions rather than overwriting earlier archive rows."
    ),
    rate_limits="Free API: 3 requests/second per API key.",
    access_limits="Free account/API key required; key is read from KOTE_API_KEY and never stored in repository data.",
    missing_periods="Missing rows/fields remain missing; partial current-day buckets are excluded.",
    attribution_assumptions=(
        "Exchange labels are provider-defined and probabilistic. Netflow is movement into/out of labeled exchange "
        "wallets, not proof of sale or purchase intent."
    ),
    storage_license_notes="Store compact normalized observations/provenance; do not redistribute raw API payload dumps.",
    fallback_behavior="Exchange family remains missing/stale when the key, endpoint, schema or field mapping fails.",
    point_in_time_backfill_safe=False,
    notes="Candidate free V1.1 source. Must pass live schema validation before being called frozen.",
)

KOTE_WHALE_LTH_CONTRACT = SourceContract(
    provider="Kote Charts free API",
    family="whale_lth",
    metric="holder_balance_btc / holder_exchange_inflow_btc",
    units="BTC",
    update_cadence="daily closed UTC buckets; partial current day excluded",
    historical_depth="provider chart history subject to endpoint retention/limits",
    availability_rule=(
        "Rows become causally usable only from first local observation because original publication timestamps "
        "are not present in the documented chart series."
    ),
    revision_behavior=(
        "Holder cohort calculations and exchange/entity labels may revise. Changed values append as new locally "
        "observed revisions."
    ),
    rate_limits="Free API: 3 requests/second per API key.",
    access_limits="Free account/API key required.",
    missing_periods="Missing rows/fields remain missing; no interpolation or zero fill.",
    attribution_assumptions=(
        "LTH supply is a holder-cohort heuristic. Whale-to-exchange means large deposits into labeled exchange "
        "wallets and is not automatically a sale."
    ),
    storage_license_notes="Store compact normalized observations/provenance; do not redistribute raw API payload dumps.",
    fallback_behavior="Whale/LTH family remains missing/partial when a chart or field is unavailable.",
    point_in_time_backfill_safe=False,
    notes="Whale deposit evidence and LTH supply remain distinct metrics inside one holder family.",
)

KOTE_MINER_CONTRACT = SourceContract(
    provider="Kote Charts free API",
    family="miner",
    metric="miner_reserve_btc",
    units="BTC",
    update_cadence="daily closed UTC buckets; partial current day excluded",
    historical_depth="provider chart history subject to endpoint retention/limits",
    availability_rule="Rows are usable only from first local observation; no pre-bootstrap causal replay.",
    revision_behavior="Miner/pool labels may revise; changed values append as new locally observed revisions.",
    rate_limits="Free API: 3 requests/second per API key.",
    access_limits="Free account/API key required.",
    missing_periods="Missing rows/fields remain missing.",
    attribution_assumptions=(
        "Reserve is BTC attributed to labeled miner/pool wallets. Generic miner outflow is not assumed to be "
        "exchange selling, so V1.1 promotes reserve only unless destination semantics are explicit."
    ),
    storage_license_notes="Store compact normalized observations/provenance; do not redistribute raw API payload dumps.",
    fallback_behavior="Miner family remains missing/partial when the chart or reserve field is unavailable.",
    point_in_time_backfill_safe=False,
)

KOTE_FUND_CONTEXT_CONTRACT = SourceContract(
    provider="Kote Charts free API",
    family="treasury",
    metric="fund_custody_reserve_btc (context only)",
    units="BTC",
    update_cadence="daily closed UTC buckets; partial current day excluded",
    historical_depth="provider chart history subject to endpoint retention/limits",
    availability_rule="Rows are usable only from first local observation; no pre-bootstrap causal replay.",
    revision_behavior="Fund/custody labels may revise; changed values append as later locally observed revisions.",
    rate_limits="Free API: 3 requests/second per API key.",
    access_limits="Free account/API key required.",
    missing_periods="Missing rows/fields remain missing.",
    attribution_assumptions=(
        "The provider chart combines ETF custody / fund / treasury activity. It is not a clean corporate-treasury "
        "series, so it is context-only and must not activate treasury_holdings_btc scoring."
    ),
    storage_license_notes="Store compact normalized observations/provenance; do not redistribute raw API payload dumps.",
    fallback_behavior="Treasury scoring remains missing; mixed fund/custody context may also be absent.",
    point_in_time_backfill_safe=False,
    notes="Do not promote to treasury scoring without cleaner entity semantics.",
)


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


@dataclass(frozen=True, slots=True)
class KoteChartSpec:
    chart_id: str
    family: str
    metric: str
    unit: str
    value_keys: tuple[str, ...]
    cadence_seconds: int = 86_400
    attribution_status: str = "MEDIUM"
    attribution_quality: float | None = 0.7
    data_quality: float = 0.8
    context_only: bool = False
    semantic_note: str = ""


KOTE_CHART_SPECS: tuple[KoteChartSpec, ...] = (
    KoteChartSpec(
        chart_id="exchange-netflow",
        family="exchange_btc",
        metric="btc_netflow",
        unit="BTC",
        value_keys=(
            "netflow",
            "net_flow",
            "netflow_btc",
            "net_btc",
            "exchange_netflow",
            "exchange_netflow_btc",
        ),
        attribution_status="HIGH",
        attribution_quality=0.75,
        data_quality=0.82,
        semantic_note="positive means BTC moving into labeled exchanges; negative means leaving",
    ),
    KoteChartSpec(
        chart_id="exchange-reserve",
        family="exchange_btc",
        metric="reserve_btc",
        unit="BTC",
        value_keys=(
            "reserve",
            "reserve_btc",
            "exchange_reserve",
            "exchange_reserve_btc",
            "balance",
            "balance_btc",
        ),
        attribution_status="HIGH",
        attribution_quality=0.75,
        data_quality=0.82,
        semantic_note="BTC balance attributed to labeled exchanges",
    ),
    KoteChartSpec(
        chart_id="lth-supply",
        family="whale_lth",
        metric="holder_balance_btc",
        unit="BTC",
        value_keys=(
            "lth_supply",
            "long_term_holder_supply",
            "long_term_supply",
            "lth",
        ),
        attribution_status="HIGH",
        attribution_quality=0.9,
        data_quality=0.85,
        semantic_note="long-term-holder cohort supply; cohort heuristic rather than named wallet identity",
    ),
    KoteChartSpec(
        chart_id="whale-to-exchange",
        family="whale_lth",
        metric="holder_exchange_inflow_btc",
        unit="BTC",
        value_keys=(
            "whale_to_exchange",
            "whale_inflow",
            "whale_inflow_btc",
            "whale_deposits",
            "whale_deposits_btc",
            "whale_exchange_inflow",
        ),
        attribution_status="MEDIUM",
        attribution_quality=0.65,
        data_quality=0.78,
        semantic_note="large deposits (provider threshold >=100 BTC) into labeled exchange wallets; not proof of sale",
    ),
    KoteChartSpec(
        chart_id="miner-flows",
        family="miner",
        metric="miner_reserve_btc",
        unit="BTC",
        value_keys=(
            "reserve",
            "reserve_btc",
            "miner_reserve",
            "miner_reserve_btc",
            "balance",
            "balance_btc",
        ),
        attribution_status="MEDIUM",
        attribution_quality=0.7,
        data_quality=0.78,
        semantic_note="BTC reserve attributed to labeled miner/pool wallets",
    ),
    KoteChartSpec(
        chart_id="fund-flows",
        family="treasury",
        metric="fund_custody_reserve_btc",
        unit="BTC",
        value_keys=(
            "reserve",
            "reserve_btc",
            "fund_reserve",
            "fund_reserve_btc",
            "custody_reserve",
            "custody_reserve_btc",
        ),
        attribution_status="MEDIUM",
        attribution_quality=0.6,
        data_quality=0.72,
        context_only=True,
        semantic_note="mixed ETF custody/fund/treasury reserve; context only, not corporate treasury holdings",
    ),
)


def _extract_series(payload: Any, *, chart_id: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"Kote {chart_id} payload must be an object")
    if payload.get("success") is False:
        error = payload.get("error")
        raise ValueError(f"Kote {chart_id} API error: {error}")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(f"Kote {chart_id} payload missing data object")
    returned_chart = data.get("chart")
    if returned_chart and str(returned_chart) != chart_id:
        raise ValueError(f"Kote chart mismatch: requested {chart_id}, received {returned_chart}")
    series = data.get("series")
    if not isinstance(series, list):
        raise ValueError(f"Kote {chart_id} payload missing data.series list")
    return [row for row in series if isinstance(row, Mapping)]


def _extract_timestamp(row: Mapping[str, Any]) -> int | None:
    for key in ("t", "date", "timestamp", "time"):
        if key not in row or row.get(key) is None:
            continue
        raw = row[key]
        # Kote documents daily chart labels as YYYY-MM-DD. Capital Flow's generic
        # parser intentionally rejects timezone-naive timestamps, so make the daily
        # bucket boundary explicit as UTC instead of weakening the shared parser.
        if isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
            raw = raw.strip() + "T00:00:00Z"
        try:
            return iso_to_ms(raw)
        except Exception:
            continue
    return None


def _extract_value(row: Mapping[str, Any], aliases: Sequence[str]) -> tuple[float | None, str | None]:
    normalized = {_norm_key(key): key for key in row}
    matches: list[tuple[str, float]] = []
    for alias in aliases:
        original = normalized.get(_norm_key(alias))
        if original is None:
            continue
        value = _finite_float(row.get(original))
        if value is not None:
            matches.append((str(original), value))
    if not matches:
        return None, None

    unique_values = {round(value, 12) for _, value in matches}
    if len(unique_values) > 1:
        fields = ", ".join(f"{key}={value}" for key, value in matches)
        raise ValueError(f"ambiguous Kote value fields: {fields}")
    return matches[0][1], matches[0][0]


def _numeric_keys(row: Mapping[str, Any]) -> list[str]:
    return sorted(
        str(key)
        for key, value in row.items()
        if _finite_float(value) is not None and _norm_key(str(key)) not in {"t", "time", "timestamp", "date"}
    )


@dataclass(slots=True)
class KoteFreeCollector:
    api_key: str
    specs: Sequence[KoteChartSpec] = KOTE_CHART_SPECS
    base_url: str = KOTE_BASE_URL
    timeout: float = 20.0
    min_interval_seconds: float = 0.4
    backfill_limit: int = 1_200
    _last_request_monotonic: float = 0.0

    @classmethod
    def from_env(
        cls,
        *,
        api_key_env: str = "KOTE_API_KEY",
        specs: Sequence[KoteChartSpec] = KOTE_CHART_SPECS,
        timeout: float = 20.0,
    ) -> "KoteFreeCollector":
        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            raise ValueError(
                f"missing Kote API key in environment variable {api_key_env}; "
                "create a free key at Kote Charts and keep it out of Git"
            )
        return cls(api_key=api_key, specs=specs, timeout=timeout)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_interval_seconds - elapsed
        if self._last_request_monotonic and remaining > 0:
            time.sleep(remaining)

    def _get_chart(self, chart_id: str, *, limit: int) -> Any:
        self._throttle()
        query = urlencode(
            {
                "granularity": "day",
                "includePartial": "false",
                "limit": max(1, int(limit)),
            }
        )
        url = self.base_url.rstrip("/") + "/" + chart_id + "?" + query
        request = Request(
            url,
            headers={
                "User-Agent": "AnataCapitalFlow/1.1 (+local research collector)",
                "X-API-Key": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        finally:
            self._last_request_monotonic = time.monotonic()

    def collect_spec(
        self,
        spec: KoteChartSpec,
        *,
        observed_at_ms: int,
        include_backfill: bool = False,
    ) -> list[FlowObservation]:
        payload = self._get_chart(
            spec.chart_id,
            limit=self.backfill_limit if include_backfill else 5,
        )
        return self.parse_payload(
            payload,
            spec=spec,
            observed_at_ms=observed_at_ms,
            include_backfill=include_backfill,
        )

    def collect_with_errors(
        self,
        *,
        observed_at_ms: int | None = None,
        include_backfill: bool = False,
    ) -> tuple[list[FlowObservation], list[str]]:
        observed = utc_now_ms() if observed_at_ms is None else int(observed_at_ms)
        observations: list[FlowObservation] = []
        errors: list[str] = []
        for spec in self.specs:
            try:
                observations.extend(
                    self.collect_spec(
                        spec,
                        observed_at_ms=observed,
                        include_backfill=include_backfill,
                    )
                )
            except Exception as exc:
                errors.append(f"kote:{spec.chart_id}: {type(exc).__name__}: {exc}")
        return observations, errors

    def probe(self) -> dict[str, Any]:
        charts: list[dict[str, Any]] = []
        for spec in self.specs:
            try:
                payload = self._get_chart(spec.chart_id, limit=2)
                series = _extract_series(payload, chart_id=spec.chart_id)
                sample = dict(series[-1]) if series else None
                charts.append(
                    {
                        "chart_id": spec.chart_id,
                        "family": spec.family,
                        "target_metric": spec.metric,
                        "context_only": spec.context_only,
                        "row_count": len(series),
                        "sample_keys": sorted(str(key) for key in sample) if sample else [],
                        "numeric_keys": _numeric_keys(sample) if sample else [],
                        "sample_latest_row": sample,
                    }
                )
            except Exception as exc:
                charts.append(
                    {
                        "chart_id": spec.chart_id,
                        "family": spec.family,
                        "target_metric": spec.metric,
                        "context_only": spec.context_only,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "provider": "Kote Charts",
            "probe_only": True,
            "api_key_included": False,
            "charts": charts,
        }

    @staticmethod
    def parse_payload(
        payload: Any,
        *,
        spec: KoteChartSpec,
        observed_at_ms: int,
        include_backfill: bool = False,
    ) -> list[FlowObservation]:
        series = _extract_series(payload, chart_id=spec.chart_id)
        parsed: list[tuple[int, float, str]] = []
        last_row: Mapping[str, Any] | None = None
        for row in series:
            last_row = row
            if row.get("partial") is True:
                continue
            effective = _extract_timestamp(row)
            if effective is None:
                continue
            value, field_key = _extract_value(row, spec.value_keys)
            if value is None or field_key is None:
                continue
            parsed.append((effective, value, field_key))

        if not parsed:
            available = _numeric_keys(last_row) if last_row is not None else []
            raise ValueError(
                f"Kote {spec.chart_id} contained no recognized {spec.metric} field; "
                f"candidate source numeric keys={available}; configured aliases={list(spec.value_keys)}"
            )

        parsed.sort(key=lambda item: item[0])
        if not include_backfill:
            parsed = [parsed[-1]]

        observations: list[FlowObservation] = []
        latest_effective = parsed[-1][0]
        for effective, value, field_key in parsed:
            flags = [
                "KOTE_DAILY_CLOSED_BUCKET",
                "UPSTREAM_ENTITY_OR_COHORT_SEMANTICS_PROVIDER_DEFINED",
                "NO_PRE_OBSERVATION_POINT_IN_TIME_REPLAY",
            ]
            if include_backfill and effective != latest_effective:
                flags.extend(
                    (
                        "HISTORICAL_VALUE_FIRST_OBSERVED_AT_BOOTSTRAP",
                        "NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY",
                    )
                )
            if spec.context_only:
                flags.append("CONTEXT_ONLY_NOT_SCORING")

            provenance: dict[str, Any] = {
                "provider": "Kote Charts",
                "chart_id": spec.chart_id,
                "url": KOTE_BASE_URL.rstrip("/") + "/" + spec.chart_id,
                "source_field": field_key,
                "semantic_note": spec.semantic_note,
                "historical_publication_time_unknown": True,
            }
            if spec.context_only:
                provenance["context_only"] = True

            observations.append(
                FlowObservation(
                    family=spec.family,
                    metric=spec.metric,
                    asset="BTC",
                    value=value,
                    unit=spec.unit,
                    effective_at_ms=effective,
                    available_at_ms=int(observed_at_ms),
                    observed_at_ms=int(observed_at_ms),
                    source=f"kote_{spec.chart_id.replace('-', '_')}",
                    source_record_id=f"{spec.chart_id}:{spec.metric}:{effective}",
                    revision=str(observed_at_ms),
                    cadence_seconds=spec.cadence_seconds,
                    attribution_status=spec.attribution_status,
                    attribution_quality=spec.attribution_quality,
                    data_quality=spec.data_quality,
                    economic_event_id=None,
                    dependence_group=f"kote:{spec.chart_id}:{effective}",
                    provenance=provenance,
                    quality_flags=tuple(flags),
                )
            )
        return observations


KOTE_SOURCE_CONTRACTS = (
    KOTE_EXCHANGE_CONTRACT,
    KOTE_WHALE_LTH_CONTRACT,
    KOTE_MINER_CONTRACT,
    KOTE_FUND_CONTEXT_CONTRACT,
)
