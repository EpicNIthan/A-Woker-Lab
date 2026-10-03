from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.request import Request, urlopen

from .contracts import FlowObservation, SourceContract, iso_to_ms, utc_now_ms

FARSIDE_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
DEFILLAMA_STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

FARSIDE_ETF_CONTRACT = SourceContract(
    provider="Farside Investors",
    family="etf",
    metric="net_flow_usd",
    units="USD millions on source; normalized to USD",
    update_cadence="trading-day table, updated during/after the trading day",
    historical_depth="US spot-BTC ETF era shown by provider",
    availability_rule=(
        "Provider table does not expose a per-row first-publication timestamp. "
        "Any row is legally usable only from the first collector observation that stored that revision. "
        "Bootstrap history therefore gets available_at=bootstrap observed_at and must never be replayed earlier."
    ),
    revision_behavior="Rows may change as the provider updates the table; each scrape is stored as a new revision.",
    rate_limits="No documented machine API rate limit; V0 performs low-frequency page fetches only.",
    access_limits="Public web table; no API key used.",
    missing_periods="Non-trading days and source gaps remain missing; '-' is not converted to zero.",
    attribution_assumptions="Regulated product flow total, not exact exchange-buy execution timing.",
    storage_license_notes="Store compact derived observations/provenance locally; do not redistribute source page dumps.",
    fallback_behavior="On fetch/parse failure, ETF family remains missing/stale; no synthetic value.",
    point_in_time_backfill_safe=False,
)

DEFILLAMA_STABLECOIN_CONTRACT = SourceContract(
    provider="DefiLlama stablecoin charts",
    family="stablecoin",
    metric="supply_usd",
    units="USD",
    update_cadence="daily historical chart snapshots in the public stablecoin chart endpoint",
    historical_depth="provider historical stablecoin chart history",
    availability_rule=(
        "Historical chart points do not carry trustworthy original publication timestamps. "
        "Any row is legally usable only from the first collector observation that stored that revision. "
        "Bootstrap history therefore gets available_at=bootstrap observed_at and must never be replayed earlier."
    ),
    revision_behavior="Historical/current chart values may be corrected by provider; each observed scrape is versioned.",
    rate_limits="Free endpoint limits are not treated as guaranteed; V0 fetches conservatively.",
    access_limits="Public endpoint used without API key; premium DefiLlama datasets are not assumed available.",
    missing_periods="Missing chart dates remain missing; no forward fill.",
    attribution_assumptions="Aggregate stablecoin supply is potential purchasing liquidity, not a BTC purchase.",
    storage_license_notes="Store compact derived observations/provenance locally; do not redistribute raw provider dumps.",
    fallback_behavior="On fetch/parse failure, stablecoin family remains missing/stale; no synthetic value.",
    point_in_time_backfill_safe=False,
)

EXTERNAL_JSONL_CONTRACT = SourceContract(
    provider="Explicit external/licensed JSONL adapter",
    family="exchange_btc",
    metric="provider-declared exchange BTC flow/reserve metric",
    units="must be declared per record",
    update_cadence="provider-declared",
    historical_depth="provider-declared",
    availability_rule="Record must explicitly provide available_at for causal use; missing availability is excluded.",
    revision_behavior="Record revision/source_version must be preserved; later revisions do not overwrite earlier archive rows.",
    rate_limits="not applicable to local JSONL adapter",
    access_limits="depends on upstream provider/license; Capital Flow does not assume premium access.",
    missing_periods="preserved as missing",
    attribution_assumptions="entity/wallet attribution must be supplied by upstream source and quality recorded",
    storage_license_notes="upstream provider terms control storage; adapter does not bypass them",
    fallback_behavior="family remains missing when no compliant file/provider is supplied",
    point_in_time_backfill_safe=True,
    notes="The same adapter can carry whale/LTH, miner, and treasury observations when their contracts are explicit.",
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in ("td", "th") and self._row is not None and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append(text)
            self._cell = None
        elif lower == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _fetch_text(url: str, *, timeout: float = 20.0) -> str:
    request = Request(url, headers={"User-Agent": "AnataCapitalFlow/0.1 (+local research collector)"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_farside_number(text: str) -> float | None:
    raw = text.strip().replace(",", "")
    if raw in ("", "-", "–", "—", "N/A"):
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    raw = re.sub(r"[^0-9.+-]", "", raw)
    if not raw:
        return None
    value = float(raw)
    return -abs(value) if negative else value


def _parse_farside_date(text: str) -> int | None:
    cleaned = " ".join(text.split())
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


@dataclass(slots=True)
class FarsideEtfCollector:
    url: str = FARSIDE_URL
    timeout: float = 20.0

    def collect(self, *, observed_at_ms: int | None = None, include_backfill: bool = False) -> list[FlowObservation]:
        observed = utc_now_ms() if observed_at_ms is None else int(observed_at_ms)
        return self.parse_html(
            _fetch_text(self.url, timeout=self.timeout),
            observed_at_ms=observed,
            include_backfill=include_backfill,
        )

    @staticmethod
    def parse_html(html: str, *, observed_at_ms: int, include_backfill: bool = False) -> list[FlowObservation]:
        parser = _TableParser()
        parser.feed(html)
        dated_rows: list[tuple[int, list[str]]] = []
        for row in parser.rows:
            if not row:
                continue
            date_ms = _parse_farside_date(row[0])
            if date_ms is not None:
                dated_rows.append((date_ms, row))
        if not dated_rows:
            raise ValueError("Farside ETF table did not contain dated rows")

        dated_rows.sort(key=lambda item: item[0])
        latest_date = dated_rows[-1][0]
        observations: list[FlowObservation] = []
        for date_ms, row in dated_rows:
            total: float | None = None
            # The table's total is the last numeric/non-empty data cell. Search
            # from the right to survive a harmless trailing empty column.
            for cell in reversed(row[1:]):
                parsed = _parse_farside_number(cell)
                if parsed is not None:
                    total = parsed
                    break
            if total is None:
                continue
            is_live_latest = date_ms == latest_date
            if not is_live_latest and not include_backfill:
                continue
            available = observed_at_ms
            flags = ["ETF_EXECUTION_TIMING_NOT_INFERRED"]
            if not is_live_latest:
                flags.extend((
                    "HISTORICAL_VALUE_FIRST_OBSERVED_AT_BOOTSTRAP",
                    "NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY",
                ))
            observations.append(
                FlowObservation(
                    family="etf",
                    metric="net_flow_usd",
                    asset="BTC",
                    value=total,
                    unit="USD_MILLIONS",
                    effective_at_ms=date_ms,
                    available_at_ms=available,
                    observed_at_ms=observed_at_ms,
                    source="farside_btc_etf",
                    source_record_id=f"us-btc-etf:{date_ms}",
                    revision=str(observed_at_ms),
                    cadence_seconds=86400,
                    attribution_status="DIRECT",
                    attribution_quality=1.0,
                    data_quality=0.9,
                    economic_event_id=f"us-btc-etf-total:{date_ms}",
                    dependence_group=f"etf-flow:{date_ms}",
                    provenance={"url": FARSIDE_URL, "source_units": "USD millions"},
                    quality_flags=tuple(flags),
                )
            )
        return observations


def _extract_pegged_usd(row: Mapping[str, Any]) -> float | None:
    candidates = (
        row.get("totalCirculatingUSD"),
        row.get("totalCirculating"),
        row.get("circulatingUSD"),
        row.get("circulating"),
    )
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            for key in ("peggedUSD", "usd", "USD"):
                value = candidate.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        pass
        elif candidate is not None:
            try:
                return float(candidate)
            except (TypeError, ValueError):
                pass
    return None


@dataclass(slots=True)
class DefiLlamaStablecoinCollector:
    url: str = DEFILLAMA_STABLECOIN_URL
    timeout: float = 20.0

    def collect(self, *, observed_at_ms: int | None = None, include_backfill: bool = False) -> list[FlowObservation]:
        observed = utc_now_ms() if observed_at_ms is None else int(observed_at_ms)
        text = _fetch_text(self.url, timeout=self.timeout)
        return self.parse_json(text, observed_at_ms=observed, include_backfill=include_backfill)

    @staticmethod
    def parse_json(text: str, *, observed_at_ms: int, include_backfill: bool = False) -> list[FlowObservation]:
        payload = json.loads(text)
        if isinstance(payload, Mapping):
            rows = payload.get("data") or payload.get("chart") or payload.get("history") or []
        else:
            rows = payload
        if not isinstance(rows, list):
            raise ValueError("DefiLlama stablecoin chart payload is not a list")

        parsed: list[tuple[int, float]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            date = row.get("date") or row.get("timestamp") or row.get("time")
            if date is None:
                continue
            try:
                date_ms = iso_to_ms(date)
            except Exception:
                continue
            value = _extract_pegged_usd(row)
            if value is None:
                continue
            parsed.append((date_ms, value))
        if not parsed:
            raise ValueError("DefiLlama stablecoin chart contained no usable USD supply rows")

        parsed.sort(key=lambda item: item[0])
        latest_date = parsed[-1][0]
        observations: list[FlowObservation] = []
        for date_ms, value in parsed:
            is_live_latest = date_ms == latest_date
            if not is_live_latest and not include_backfill:
                continue
            available = observed_at_ms
            flags = ["STABLECOIN_SUPPLY_IS_POTENTIAL_LIQUIDITY_NOT_BTC_BUYING"]
            if not is_live_latest:
                flags.extend((
                    "HISTORICAL_VALUE_FIRST_OBSERVED_AT_BOOTSTRAP",
                    "NO_PRE_BOOTSTRAP_POINT_IN_TIME_REPLAY",
                ))
            observations.append(
                FlowObservation(
                    family="stablecoin",
                    metric="supply_usd",
                    asset="USD_STABLECOINS",
                    value=value,
                    unit="USD",
                    effective_at_ms=date_ms,
                    available_at_ms=available,
                    observed_at_ms=observed_at_ms,
                    source="defillama_stablecoins",
                    source_record_id=f"all-stablecoins:{date_ms}",
                    revision=str(observed_at_ms),
                    cadence_seconds=86400,
                    attribution_status="NOT_APPLICABLE",
                    attribution_quality=None,
                    data_quality=0.9,
                    economic_event_id=f"stablecoin-total-supply:{date_ms}",
                    dependence_group=f"stablecoin-supply:{date_ms}",
                    provenance={"url": DEFILLAMA_STABLECOIN_URL},
                    quality_flags=tuple(flags),
                )
            )
        return observations


@dataclass(slots=True)
class JsonlFlowAdapter:
    path: str | Path
    allowed_families: tuple[str, ...] | None = None

    def collect(self) -> list[FlowObservation]:
        source = Path(self.path)
        observations: list[FlowObservation] = []
        with source.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                    obs = FlowObservation.from_dict(payload)
                except Exception as exc:
                    raise ValueError(f"invalid flow JSONL at {source}:{line_no}: {exc}") from exc
                if self.allowed_families and obs.family not in self.allowed_families:
                    continue
                observations.append(obs)
        return observations


SOURCE_CONTRACTS = (
    FARSIDE_ETF_CONTRACT,
    DEFILLAMA_STABLECOIN_CONTRACT,
    EXTERNAL_JSONL_CONTRACT,
)
