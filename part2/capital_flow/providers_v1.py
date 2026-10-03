from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import FlowObservation, SourceContract, iso_to_ms, utc_now_ms

DEFILLAMA_STABLECOIN_LIST_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
GLASSNODE_BASE_URL = "https://api.glassnode.com"

DEFILLAMA_STABLECOIN_COMPONENT_CONTRACT = SourceContract(
    provider="DefiLlama stablecoin list",
    family="stablecoin",
    metric="component_supply_usd/component_supply_change_*_usd/component_price_usd",
    units="USD",
    update_cadence="current snapshot; V1 stores one UTC-day effective bucket with causal observed revisions",
    historical_depth="current snapshot plus provider-supplied previous-day/week/month comparison fields",
    availability_rule=(
        "The list endpoint does not expose a trustworthy source-native effective timestamp for the current snapshot. "
        "V1 buckets the effective period to the UTC day of collection and uses available_at=observed_at. "
        "The snapshot is never replayed before first local observation."
    ),
    revision_behavior="Changed component values append as new observed revisions; unchanged same-day snapshots are deduplicated.",
    rate_limits="No hard public guarantee assumed; collect conservatively at daily/low-frequency cadence.",
    access_limits="Public endpoint; no API key required.",
    missing_periods="Missing assets/fields remain missing; no zero fill and no inferred peg supply.",
    attribution_assumptions="Stablecoin supply is potential purchasing liquidity, not evidence of BTC buying.",
    storage_license_notes="Store compact normalized observations/provenance; do not redistribute raw payload dumps.",
    fallback_behavior="Composition context remains partial/missing when the endpoint or a component field is unavailable.",
    point_in_time_backfill_safe=False,
    notes="Component metrics are context-only in V1 and do not silently alter the frozen V0 capital score.",
)

GLASSNODE_PIT_ADAPTER_CONTRACT = SourceContract(
    provider="Glassnode strict PIT adapter",
    family="exchange_btc",
    metric="configuration-declared exchange/holder/miner metric",
    units="configuration-declared",
    update_cadence="configuration-declared",
    historical_depth="configuration/provider-declared",
    availability_rule=(
        "V1 first checks Glassnode metric metadata and refuses metrics unless is_pit=true. "
        "Even then, rows fetched during bootstrap are legally usable only from this collector observation unless "
        "an explicit upstream publication timestamp is supplied."
    ),
    revision_behavior="Every observed revision is preserved; later values do not overwrite prior local observations.",
    rate_limits="Subject to Glassnode account/API credit and rate limits.",
    access_limits="Requires GLASSNODE_API_KEY (or configured environment variable) and plan access to requested metrics.",
    missing_periods="Preserved as missing; adapter never fabricates unavailable metrics.",
    attribution_assumptions="Entity/venue semantics are those declared by the configured Glassnode metric.",
    storage_license_notes="Use/store according to the user's Glassnode license; adapter does not bypass access controls.",
    fallback_behavior="Family remains missing if key, access, PIT metadata, metric, or parse validation fails.",
    point_in_time_backfill_safe=False,
    notes="This adapter exists to safely activate exchange BTC / Whale-LTH / Miner inputs when an approved PIT metric is configured.",
)


def _fetch_json(url: str, *, timeout: float = 20.0, headers: Mapping[str, str] | None = None) -> Any:
    request_headers = {"User-Agent": "AnataCapitalFlow/1.0 (+local research collector)"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _mapping_float(value: Any, key: str = "peggedUSD") -> float | None:
    if isinstance(value, Mapping):
        candidate = value.get(key)
        if candidate is None and key != "usd":
            candidate = value.get("usd")
        if candidate is None:
            return None
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_day_bucket_ms(timestamp_ms: int) -> int:
    return (int(timestamp_ms) // 86_400_000) * 86_400_000


@dataclass(slots=True)
class DefiLlamaStablecoinCompositionCollector:
    url: str = DEFILLAMA_STABLECOIN_LIST_URL
    timeout: float = 20.0
    symbols: tuple[str, ...] = ("USDT", "USDC", "USDE", "USDS", "DAI")

    def collect(self, *, observed_at_ms: int | None = None) -> list[FlowObservation]:
        observed = utc_now_ms() if observed_at_ms is None else int(observed_at_ms)
        payload = _fetch_json(self.url, timeout=self.timeout)
        return self.parse_payload(payload, observed_at_ms=observed, symbols=self.symbols)

    @staticmethod
    def parse_payload(
        payload: Any,
        *,
        observed_at_ms: int,
        symbols: Sequence[str] = ("USDT", "USDC", "USDE", "USDS", "DAI"),
    ) -> list[FlowObservation]:
        if not isinstance(payload, Mapping):
            raise ValueError("DefiLlama stablecoin list payload must be an object")
        rows = payload.get("peggedAssets")
        if not isinstance(rows, list):
            raise ValueError("DefiLlama stablecoin list payload missing peggedAssets")

        wanted = {str(symbol).upper() for symbol in symbols}
        by_symbol: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
            if symbol and symbol in wanted:
                by_symbol[symbol] = row

        if not by_symbol:
            raise ValueError("DefiLlama stablecoin list contained none of the configured symbols")

        effective = _utc_day_bucket_ms(observed_at_ms)
        observations: list[FlowObservation] = []
        for symbol in sorted(wanted):
            row = by_symbol.get(symbol)
            if row is None:
                continue

            current = _mapping_float(row.get("circulating"))
            prev_day = _mapping_float(row.get("circulatingPrevDay"))
            prev_week = _mapping_float(row.get("circulatingPrevWeek"))
            prev_month = _mapping_float(row.get("circulatingPrevMonth"))
            price = _mapping_float(row.get("price"), key="usd")

            values: tuple[tuple[str, float | None], ...] = (
                ("component_supply_usd", current),
                ("component_supply_change_1d_usd", None if current is None or prev_day is None else current - prev_day),
                ("component_supply_change_7d_usd", None if current is None or prev_week is None else current - prev_week),
                ("component_supply_change_30d_usd", None if current is None or prev_month is None else current - prev_month),
                ("component_price_usd", price),
            )
            stable_id = str(row.get("id") or symbol)
            for metric, value in values:
                if value is None:
                    continue
                observations.append(
                    FlowObservation(
                        family="stablecoin",
                        metric=metric,
                        asset=symbol,
                        value=float(value),
                        unit="USD",
                        effective_at_ms=effective,
                        available_at_ms=observed_at_ms,
                        observed_at_ms=observed_at_ms,
                        source="defillama_stablecoin_components",
                        source_record_id=f"{stable_id}:{metric}:{effective}",
                        revision=str(observed_at_ms),
                        cadence_seconds=86400,
                        attribution_status="NOT_APPLICABLE",
                        attribution_quality=None,
                        data_quality=0.85,
                        economic_event_id=None,
                        dependence_group=f"stablecoin-component:{symbol}:{effective}",
                        provenance={
                            "url": DEFILLAMA_STABLECOIN_LIST_URL,
                            "stablecoin_id": stable_id,
                            "symbol": symbol,
                            "peg_type": row.get("pegType"),
                            "peg_mechanism": row.get("pegMechanism"),
                            "context_only": True,
                        },
                        quality_flags=(
                            "STABLECOIN_COMPONENT_CONTEXT_ONLY",
                            "STABLECOIN_SUPPLY_IS_POTENTIAL_LIQUIDITY_NOT_BTC_BUYING",
                            "CURRENT_SNAPSHOT_EFFECTIVE_DAY_BUCKET_ASSUMED",
                            "NO_PRE_OBSERVATION_POINT_IN_TIME_REPLAY",
                        ),
                    )
                )
        return observations


@dataclass(frozen=True, slots=True)
class GlassnodeMetricConfig:
    path: str
    family: str
    metric: str
    unit: str
    asset: str = "BTC"
    cadence_seconds: int = 3600
    parameters: Mapping[str, str] = field(default_factory=dict)
    attribution_status: str = "DIRECT"
    attribution_quality: float | None = 0.9
    data_quality: float = 0.9
    source_name: str = "glassnode_pit"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GlassnodeMetricConfig":
        required = ("path", "family", "metric", "unit")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValueError("Glassnode metric config missing: " + ", ".join(missing))
        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, Mapping):
            raise ValueError("Glassnode metric parameters must be an object")
        return cls(
            path=str(payload["path"]),
            family=str(payload["family"]),
            metric=str(payload["metric"]),
            unit=str(payload["unit"]),
            asset=str(payload.get("asset") or "BTC"),
            cadence_seconds=int(payload.get("cadence_seconds") or 3600),
            parameters={str(k): str(v) for k, v in parameters.items()},
            attribution_status=str(payload.get("attribution_status") or "DIRECT"),
            attribution_quality=(
                None
                if payload.get("attribution_quality") is None
                else float(payload["attribution_quality"])
            ),
            data_quality=float(payload.get("data_quality", 0.9)),
            source_name=str(payload.get("source_name") or "glassnode_pit"),
        )


def load_glassnode_config(path: str | Path) -> list[GlassnodeMetricConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("metrics") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise ValueError("Glassnode config must be a list or {\"metrics\": [...]} object")
    return [GlassnodeMetricConfig.from_dict(row) for row in rows if isinstance(row, Mapping)]


def validate_glassnode_metadata(metadata: Any, *, metric_path: str) -> Mapping[str, Any]:
    if isinstance(metadata, list) and metadata:
        metadata = metadata[0]
    if not isinstance(metadata, Mapping):
        raise ValueError(f"Glassnode metadata for {metric_path} is not an object")
    if metadata.get("is_pit") is not True:
        raise ValueError(
            f"Glassnode metric {metric_path} is not declared point-in-time (is_pit=true required)"
        )
    return metadata


@dataclass(slots=True)
class GlassnodePitCollector:
    api_key: str
    metrics: Sequence[GlassnodeMetricConfig]
    base_url: str = GLASSNODE_BASE_URL
    timeout: float = 20.0

    @classmethod
    def from_config_file(
        cls,
        path: str | Path,
        *,
        api_key_env: str = "GLASSNODE_API_KEY",
        timeout: float = 20.0,
    ) -> "GlassnodePitCollector":
        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            raise ValueError(f"missing Glassnode API key in environment variable {api_key_env}")
        return cls(api_key=api_key, metrics=load_glassnode_config(path), timeout=timeout)

    def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        if query:
            url += "?" + query
        return _fetch_json(
            url,
            timeout=self.timeout,
            headers={"X-Api-Key": self.api_key},
        )

    def collect(
        self,
        *,
        observed_at_ms: int | None = None,
        include_backfill: bool = False,
    ) -> list[FlowObservation]:
        observed = utc_now_ms() if observed_at_ms is None else int(observed_at_ms)
        observations: list[FlowObservation] = []
        for config in self.metrics:
            metadata = self._get("/v1/metadata/metric", {"path": config.path})
            validate_glassnode_metadata(metadata, metric_path=config.path)

            params: dict[str, Any] = {"a": config.asset.upper()}
            params.update(dict(config.parameters))
            payload = self._get(config.path, params)
            observations.extend(
                self.parse_metric_payload(
                    payload,
                    config=config,
                    observed_at_ms=observed,
                    include_backfill=include_backfill,
                )
            )
        return observations

    @staticmethod
    def parse_metric_payload(
        payload: Any,
        *,
        config: GlassnodeMetricConfig,
        observed_at_ms: int,
        include_backfill: bool = False,
    ) -> list[FlowObservation]:
        if not isinstance(payload, list):
            raise ValueError(f"Glassnode metric {config.path} payload must be a list")

        parsed: list[tuple[int, float]] = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            timestamp = row.get("t")
            value = row.get("v")
            if timestamp is None or value is None:
                continue
            try:
                effective_at = iso_to_ms(timestamp)
                number = float(value)
            except (TypeError, ValueError):
                continue
            parsed.append((effective_at, number))

        if not parsed:
            raise ValueError(f"Glassnode metric {config.path} contained no usable t/v rows")
        parsed.sort(key=lambda item: item[0])
        if not include_backfill:
            parsed = [parsed[-1]]

        observations: list[FlowObservation] = []
        for effective_at, value in parsed:
            is_latest = effective_at == parsed[-1][0]
            flags = [
                "GLASSNODE_METADATA_IS_PIT_TRUE",
                "UPSTREAM_ENTITY_SEMANTICS_PROVIDER_DEFINED",
            ]
            if include_backfill and not is_latest:
                flags.extend(
                    (
                        "HISTORICAL_VALUE_FIRST_OBSERVED_AT_BOOTSTRAP",
                        "NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY",
                    )
                )
            observations.append(
                FlowObservation(
                    family=config.family,
                    metric=config.metric,
                    asset=config.asset,
                    value=value,
                    unit=config.unit,
                    effective_at_ms=effective_at,
                    available_at_ms=observed_at_ms,
                    observed_at_ms=observed_at_ms,
                    source=config.source_name,
                    source_record_id=f"{config.path}:{effective_at}",
                    revision=str(observed_at_ms),
                    cadence_seconds=config.cadence_seconds,
                    attribution_status=config.attribution_status,
                    attribution_quality=config.attribution_quality,
                    data_quality=config.data_quality,
                    economic_event_id=None,
                    dependence_group=f"glassnode:{config.path}:{effective_at}",
                    provenance={
                        "provider": "Glassnode",
                        "metric_path": config.path,
                        "parameters": dict(config.parameters),
                        "metadata_is_pit": True,
                    },
                    quality_flags=tuple(flags),
                )
            )
        return observations


V1_SOURCE_CONTRACTS = (
    DEFILLAMA_STABLECOIN_COMPONENT_CONTRACT,
    GLASSNODE_PIT_ADAPTER_CONTRACT,
)
