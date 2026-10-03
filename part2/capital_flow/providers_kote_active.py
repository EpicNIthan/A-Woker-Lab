from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import time
from typing import Any, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import FlowObservation
from .providers_free import KoteChartSpec, KoteFreeCollector

# Locked from the real user-machine schema probe on 2026-08-25.
# Do not broaden these aliases without another probe/review: schema ambiguity must fail
# instead of silently selecting a plausible numeric field.
ACTIVE_KOTE_SPECS: tuple[KoteChartSpec, ...] = (
    KoteChartSpec(
        chart_id="exchange-netflow",
        family="exchange_btc",
        metric="btc_netflow",
        unit="BTC",
        value_keys=("exNetBtc",),
        attribution_status="HIGH",
        attribution_quality=0.75,
        data_quality=0.82,
        semantic_note=(
            "Kote exNetBtc: BTC net movement into/out of labeled exchange wallets; "
            "positive is toward exchanges, negative is away; not proof of trade intent"
        ),
    ),
    KoteChartSpec(
        chart_id="exchange-reserve",
        family="exchange_btc",
        metric="reserve_btc",
        unit="BTC",
        value_keys=("exReserveBtc",),
        attribution_status="HIGH",
        attribution_quality=0.75,
        data_quality=0.82,
        semantic_note="Kote exReserveBtc: BTC balance attributed to labeled exchange wallets",
    ),
    KoteChartSpec(
        chart_id="lth-supply",
        family="whale_lth",
        metric="holder_balance_btc",
        unit="BTC",
        value_keys=("lthSupplyBtc",),
        attribution_status="HIGH",
        attribution_quality=0.90,
        data_quality=0.85,
        semantic_note=(
            "Kote lthSupplyBtc: long-term-holder cohort supply; cohort heuristic, "
            "not named-wallet identity"
        ),
    ),
    KoteChartSpec(
        chart_id="whale-to-exchange",
        family="whale_lth",
        metric="holder_exchange_inflow_btc",
        unit="BTC",
        value_keys=("whaleToExBtc",),
        attribution_status="MEDIUM",
        attribution_quality=0.65,
        data_quality=0.78,
        context_only=True,
        semantic_note=(
            "Kote whaleToExBtc: provider-defined whale-sized deposits (>=100 BTC) "
            "to labeled exchanges; context only in V1.1, not netflow and not proof of sale"
        ),
    ),
    KoteChartSpec(
        chart_id="miner-flows",
        family="miner",
        metric="miner_reserve_btc",
        unit="BTC",
        value_keys=("minerReserveBtc",),
        attribution_status="MEDIUM",
        attribution_quality=0.70,
        data_quality=0.78,
        semantic_note="Kote minerReserveBtc: BTC attributed to labeled miner/pool wallets",
    ),
)


def _closed_bucket_end(obs: FlowObservation) -> FlowObservation:
    """Represent Kote's closed daily bucket at its period end.

    The source label `2026-08-23` describes the closed UTC day. The generic Kote
    parser preserves that label as 2026-08-23T00:00Z. For feature windows and
    freshness, a completed daily aggregate becomes effective at the end of that
    period, 2026-08-24T00:00Z. The original bucket start is retained in provenance.
    """
    if "KOTE_DAILY_CLOSED_BUCKET" not in obs.quality_flags or not obs.cadence_seconds:
        return obs

    cadence_ms = int(obs.cadence_seconds) * 1000
    end_ms = obs.effective_at_ms + cadence_ms
    if end_ms > obs.observed_at_ms:
        return obs

    provenance = dict(obs.provenance)
    provenance["source_bucket_start_ms"] = obs.effective_at_ms
    provenance["effective_semantics"] = "closed_bucket_end"

    return replace(
        obs,
        effective_at_ms=end_ms,
        provenance=provenance,
        quality_flags=tuple(
            dict.fromkeys(obs.quality_flags + ("EFFECTIVE_AT_CLOSED_BUCKET_END",))
        ),
    )


class ActivatedKoteCollector(KoteFreeCollector):
    """Schema-locked Kote collector approved for the V1.1 candidate."""

    @classmethod
    def from_env(
        cls,
        *,
        api_key_env: str = "KOTE_API_KEY",
        specs: Sequence[KoteChartSpec] = ACTIVE_KOTE_SPECS,
        timeout: float = 20.0,
    ) -> "ActivatedKoteCollector":
        base = super().from_env(
            api_key_env=api_key_env,
            specs=specs,
            timeout=timeout,
        )
        return cls(
            api_key=base.api_key,
            specs=base.specs,
            base_url=base.base_url,
            timeout=base.timeout,
            min_interval_seconds=base.min_interval_seconds,
            backfill_limit=base.backfill_limit,
        )

    def _get_chart_from_date(self, chart_id: str, *, from_date: str) -> Any:
        """Fetch a documented Kote date range without relying on a large `limit`.

        The live user-machine run showed `limit=1200` returns HTTP 400 while small
        limits work. Kote documents `from`/`to` as supported time-series parameters,
        so bootstrap uses `from=<ISO date>` and remains locally bounded afterwards.
        """
        self._throttle()
        query = urlencode(
            {
                "granularity": "day",
                "includePartial": "false",
                "from": from_date,
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
        if include_backfill:
            # Ask for slightly more calendar depth than the local record cap so
            # closed-day boundaries/weekends cannot leave us short of 1,200 rows.
            lookback_days = max(1, int(self.backfill_limit)) + 7
            from_ms = int(observed_at_ms) - lookback_days * 86_400_000
            from_date = datetime.fromtimestamp(
                from_ms / 1000.0,
                tz=timezone.utc,
            ).date().isoformat()
            payload = self._get_chart_from_date(spec.chart_id, from_date=from_date)
        else:
            payload = self._get_chart(spec.chart_id, limit=5)

        rows = self.parse_payload(
            payload,
            spec=spec,
            observed_at_ms=observed_at_ms,
            include_backfill=include_backfill,
        )
        # Kote may return more rows than requested/ranged in some configurations;
        # the local bound is authoritative for weak-PC memory/storage behavior.
        if include_backfill and len(rows) > self.backfill_limit:
            rows = rows[-self.backfill_limit :]
        return [_closed_bucket_end(obs) for obs in rows]
