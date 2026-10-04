from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .contracts import FlowObservation, SourceContract, iso_to_ms

BITMEX_POR_LISTING_URL = "https://public.bitmex.com/?prefix=data/porl/"
BITMEX_PUBLIC_BASE = "https://public.bitmex.com/"
_HEADER_BYTES = 65536

BITMEX_RESERVES_CONTRACT = SourceContract(
    provider="BitMEX",
    family="exchange_btc",
    metric="published_reserve_btc",
    units="BTC",
    update_cadence="BitMEX states reserve/liability snapshots are published twice weekly (Tuesday/Thursday)",
    historical_depth="public data/porl object archive; collector intentionally selects only the latest reserve proof",
    availability_rule="S3 object LastModified is source-native publication availability; collector receipt must be at or after it",
    revision_behavior="proof objects are immutable snapshot artifacts identified by object key; replacement/new objects are separate evidence",
    rate_limits="public object storage; no rate-limit SLA assumed",
    access_limits="public HTTPS, no API key; collector reads listing plus only the first 64 KiB of latest reserve YAML",
    missing_periods="missing listing, reserve object, LastModified, filename snapshot timestamp, height, or total fails closed",
    attribution_assumptions="published BitMEX-controlled/custodial reserve proof context; reserve level is not deposit/withdrawal flow",
    storage_license_notes="store compact derived observation/provenance only; do not redistribute reserve proof contents",
    fallback_behavior="fail closed and leave BitMEX reserve context missing/stale",
    point_in_time_backfill_safe=False,
    notes="Context-only exchange reserve transparency. Never infer BTC price direction or exchange inflow/outflow from reserve level alone.",
)

_KEY_TS_RE = re.compile(r"(\d{8})D(\d{6})")
_HEIGHT_RE = re.compile(r"(?m)^height:\s*(\d+)\s*$")
_TOTAL_RE = re.compile(r"(?m)^total:\s*(\d+)\s*$")


class BitmexReserveCollector:
    """Collect latest first-party BitMEX BTC reserve-proof context.

    The object-store LastModified clock is the legal availability boundary. The
    proof filename timestamp is the economic snapshot clock. Only the compact
    header fields are retained; raw proof data remains at the first-party source.
    """

    source = "BitMEX Proof of Reserves"
    listing_url = BITMEX_POR_LISTING_URL

    def __init__(
        self,
        *,
        fetch_listing: Callable[[str], str] | None = None,
        fetch_head: Callable[[str], str] | None = None,
    ) -> None:
        self._fetch_listing = fetch_listing or self._download_listing
        self._fetch_head = fetch_head or self._download_head

    @staticmethod
    def _download_listing(url: str) -> str:
        request = Request(url, headers={"User-Agent": "AnataCapitalFlow/1.0"})
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed first-party HTTPS source
            return response.read().decode("utf-8")

    @staticmethod
    def _download_head(url: str) -> str:
        request = Request(
            url,
            headers={"User-Agent": "AnataCapitalFlow/1.0", "Range": f"bytes=0-{_HEADER_BYTES - 1}"},
        )
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed first-party HTTPS source
            return response.read(_HEADER_BYTES).decode("utf-8", errors="strict")

    @staticmethod
    def _snapshot_ms(key: str) -> int:
        match = _KEY_TS_RE.search(key)
        if not match:
            raise ValueError("BitMEX reserve object lacks filename snapshot timestamp")
        dt = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _latest_reserve(xml_text: str) -> tuple[str, str, str | None]:
        root = ElementTree.fromstring(xml_text)
        candidates: list[tuple[int, str, str, str | None]] = []
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1] != "Contents":
                continue
            fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
            key = fields.get("Key", "")
            filename = key.rsplit("/", 1)[-1]
            # BitMEX has used both legacy reserves-... keys and date-prefixed
            # YYYYMMDD-reserves-... keys.  Treat either as reserve snapshots;
            # publication ordering remains the first-party LastModified clock.
            if not (filename.startswith("reserves-") or re.match(r"^\\d{8}-reserves-", filename)):
                continue
            if not key.endswith((".yaml", ".yml")):
                continue
            modified = fields.get("LastModified", "")
            if not modified:
                continue
            candidates.append((iso_to_ms(modified), key, modified, fields.get("ETag") or None))
        if not candidates:
            raise ValueError("BitMEX reserve proof object missing from listing")
        _, key, modified, etag = max(candidates, key=lambda row: (row[0], row[1]))
        return key, modified, etag

    @staticmethod
    def _header_values(text: str) -> tuple[int, int]:
        height_match = _HEIGHT_RE.search(text)
        total_match = _TOTAL_RE.search(text)
        if not height_match or not total_match:
            raise ValueError("BitMEX reserve proof header missing height/total")
        height = int(height_match.group(1))
        total_sats = int(total_match.group(1))
        if height <= 0 or total_sats <= 0:
            raise ValueError("BitMEX reserve proof height/total must be positive")
        return height, total_sats

    def collect(self, *, observed_at_ms: int, include_backfill: bool = False) -> Iterable[FlowObservation]:
        del include_backfill  # old objects are not replayed as if previously collected
        listing = self._fetch_listing(self.listing_url)
        key, modified, etag = self._latest_reserve(listing)
        available_at_ms = iso_to_ms(modified)
        if available_at_ms > int(observed_at_ms):
            raise ValueError("BitMEX publication timestamp is later than collector receipt")
        effective_at_ms = self._snapshot_ms(key)
        if effective_at_ms > available_at_ms:
            raise ValueError("BitMEX snapshot timestamp is later than publication timestamp")

        object_url = BITMEX_PUBLIC_BASE + quote(key, safe="/")
        header = self._fetch_head(object_url)
        height, total_sats = self._header_values(header)
        total_btc = total_sats / 100_000_000.0

        provenance = {
            "url": object_url,
            "listing_url": self.listing_url,
            "provider": "BitMEX",
            "network": "bitcoin-mainnet",
            "object_key": key,
            "object_etag": etag,
            "proof_block_height": height,
            "source_snapshot_timestamp": effective_at_ms,
            "source_publication_timestamp": modified,
            "effective_at_basis": "reserve_object_filename_snapshot_timestamp",
            "availability_basis": "first_party_object_last_modified",
            "publication_timestamp_exposed": True,
            "context_only": True,
            "semantic_guard": "reserve_level_not_exchange_inflow_outflow_or_btc_price_direction",
            "raw_evidence_retained_by_source": True,
            "collector_raw_retention": "compact_header_fields_only",
            "source_contract": BITMEX_RESERVES_CONTRACT.to_dict(),
        }
        yield FlowObservation(
            family="exchange_btc",
            metric="published_reserve_btc",
            asset="BTC",
            value=total_btc,
            unit="BTC",
            effective_at_ms=effective_at_ms,
            available_at_ms=available_at_ms,
            observed_at_ms=int(observed_at_ms),
            source=self.source,
            source_record_id=f"bitmex:por:{key}",
            cadence_seconds=3 * 86400,
            attribution_status="HIGH",
            attribution_quality=0.9,
            data_quality=0.95,
            dependence_group="bitmex_proof_of_reserves",
            provenance=provenance,
            quality_flags=(
                "CONTEXT_ONLY",
                "RESERVE_LEVEL_NOT_FLOW",
                "FIRST_PARTY_PUBLICATION_CLOCK",
                "LATEST_SNAPSHOT_ONLY_NO_RETROACTIVE_BACKFILL",
            ),
        )
