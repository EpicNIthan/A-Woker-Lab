from __future__ import annotations

import json
from typing import Callable, Iterable
from urllib.request import Request, urlopen

from .contracts import FlowObservation, SourceContract, iso_to_ms

MEMPOOL_HASHRATE_URL = "https://mempool.space/api/v1/mining/hashrate/1m"

MEMPOOL_MINER_NETWORK_CONTRACT = SourceContract(
    provider="mempool.space",
    family="miner",
    metric="network_hashrate_hs",
    units="H/s",
    update_cadence="source rolling estimates; collector uses latest returned point",
    historical_depth="endpoint-selected trailing 1 month",
    availability_rule="collector receipt is the legal available_at; source timestamps are effective_at only",
    revision_behavior="rolling/estimated network hashrate may be recomputed; no historical publication ledger is assumed",
    rate_limits="public endpoint; no rate-limit SLA assumed",
    access_limits="public HTTPS API, no key",
    missing_periods="empty/malformed series is explicit collection failure",
    attribution_assumptions="network-wide context; no miner entity attribution",
    storage_license_notes="store compact derived observations/provenance, not redistributed raw responses",
    fallback_behavior="fail closed and leave miner-network context missing/stale",
    point_in_time_backfill_safe=False,
    notes="Context-only miner/network capacity evidence; never a BTC price direction or miner-flow inference.",
)


class MempoolMinerNetworkCollector:
    """Collect first-party mempool.space Bitcoin network mining context.

    Source timestamps describe the measured network period, not when mempool.space
    first published a revision. Causal availability is therefore bounded by local
    collector receipt. The observations are context-only and cannot refresh or
    score the frozen miner family by themselves.
    """

    source = "mempool.space official API"
    url = MEMPOOL_HASHRATE_URL

    def __init__(self, *, fetch_text: Callable[[str], str] | None = None) -> None:
        self._fetch_text = fetch_text or self._download

    @staticmethod
    def _download(url: str) -> str:
        request = Request(url, headers={"User-Agent": "AnataCapitalFlow/1.0"})
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS source
            return response.read().decode("utf-8")

    @staticmethod
    def _timestamp_ms(value: object) -> int:
        if value is None:
            raise ValueError("mempool mining point timestamp missing")
        return iso_to_ms(value)  # accepts source epoch seconds/ms or timezone-aware ISO

    def collect(self, *, observed_at_ms: int, include_backfill: bool = False) -> Iterable[FlowObservation]:
        del include_backfill  # historical rows lack source-native publication timestamps
        payload = json.loads(self._fetch_text(self.url))
        if not isinstance(payload, dict):
            raise ValueError("unexpected mempool hashrate payload")

        hashrates = payload.get("hashrates")
        if not isinstance(hashrates, list) or not hashrates:
            raise ValueError("mempool hashrate series missing")
        point = hashrates[-1]
        if not isinstance(point, dict):
            raise ValueError("mempool latest hashrate point malformed")
        effective_at_ms = self._timestamp_ms(point.get("timestamp"))
        hashrate = float(point.get("avgHashrate"))
        if hashrate <= 0:
            raise ValueError("mempool network hashrate must be positive")

        common_provenance = {
            "url": self.url,
            "provider": "mempool.space",
            "network": "bitcoin-mainnet",
            "source_effective_timestamp": point.get("timestamp"),
            "effective_at_basis": "source_measurement_timestamp",
            "availability_basis": "collector_receipt_first_known",
            "publication_timestamp_exposed": False,
            "context_only": True,
            "semantic_guard": "network_mining_context_not_miner_btc_flow_or_price_direction",
            "source_contract": MEMPOOL_MINER_NETWORK_CONTRACT.to_dict(),
        }
        flags = ("NO_SOURCE_NATIVE_PUBLICATION_TIMESTAMP", "CURRENT_ONLY_FIRST_KNOWN_PIT", "CONTEXT_ONLY")

        yield FlowObservation(
            family="miner",
            metric="network_hashrate_hs",
            asset="BTC",
            value=hashrate,
            unit="H/s",
            effective_at_ms=effective_at_ms,
            available_at_ms=int(observed_at_ms),
            observed_at_ms=int(observed_at_ms),
            source=self.source,
            source_record_id=f"mempool:hashrate:{effective_at_ms}",
            cadence_seconds=86400,
            attribution_status="NOT_APPLICABLE",
            data_quality=0.95,
            dependence_group="mempool_network_mining",
            provenance=common_provenance,
            quality_flags=flags,
        )

        difficulty = payload.get("currentDifficulty")
        if difficulty is not None:
            difficulty_value = float(difficulty)
            if difficulty_value <= 0:
                raise ValueError("mempool network difficulty must be positive")
            yield FlowObservation(
                family="miner",
                metric="network_difficulty",
                asset="BTC",
                value=difficulty_value,
                unit="difficulty",
                effective_at_ms=effective_at_ms,
                available_at_ms=int(observed_at_ms),
                observed_at_ms=int(observed_at_ms),
                source=self.source,
                source_record_id=f"mempool:difficulty:{effective_at_ms}",
                cadence_seconds=1209600,
                attribution_status="NOT_APPLICABLE",
                data_quality=0.98,
                dependence_group="mempool_network_mining",
                provenance={**common_provenance, "semantic_guard": "network_difficulty_context_not_miner_btc_flow_or_price_direction"},
                quality_flags=flags,
            )
