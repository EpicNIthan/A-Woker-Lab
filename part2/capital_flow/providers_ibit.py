from __future__ import annotations

import csv
from datetime import datetime, time, timezone
from io import StringIO
from typing import Callable, Iterable
from urllib.request import Request, urlopen

from .contracts import FlowObservation

IBIT_HOLDINGS_URL = "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf/latest-holdings.csv"


class IbitHoldingsCollector:
    """Collect first-party iShares IBIT BTC holdings as context-only evidence.

    The iShares file exposes a holdings *date* but no trustworthy item-level
    publication timestamp.  We therefore use collector receipt as the causal
    availability boundary and never backdate availability to the holdings date.
    The date is conservatively represented as end-of-day UTC for economic age.
    This evidence validates issuer holdings; it is not relabelled as ETF cash flow.
    """

    source = "iShares IBIT official holdings"
    url = IBIT_HOLDINGS_URL

    def __init__(self, *, fetch_text: Callable[[str], str] | None = None) -> None:
        self._fetch_text = fetch_text or self._download

    @staticmethod
    def _download(url: str) -> str:
        request = Request(url, headers={"User-Agent": "AnataCapitalFlow/1.0"})
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS source
            return response.read().decode("utf-8-sig")

    @staticmethod
    def _effective_ms(as_of_text: str) -> int:
        day = datetime.strptime(as_of_text.strip(), "%b %d, %Y").date()
        dt = datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def collect(self, *, observed_at_ms: int, include_backfill: bool = False) -> Iterable[FlowObservation]:
        del include_backfill  # latest-holdings is intentionally current-only
        text = self._fetch_text(self.url)
        rows = list(csv.reader(StringIO(text)))
        if len(rows) < 3 or not rows[0] or "iShares Bitcoin Trust" not in rows[0][0]:
            raise ValueError("unexpected IBIT holdings header")

        holdings_date: str | None = None
        header_index: int | None = None
        for index, row in enumerate(rows):
            if len(row) >= 2 and row[0].strip() == "Fund Holdings as of":
                holdings_date = row[1].strip()
            if row and row[0].strip() == "Ticker" and "Quantity" in row:
                header_index = index
                break
        if holdings_date is None or header_index is None:
            raise ValueError("IBIT holdings date/table not found")

        header = [cell.strip() for cell in rows[header_index]]
        ticker_i = header.index("Ticker")
        quantity_i = header.index("Quantity")
        btc_row = next(
            (row for row in rows[header_index + 1 :] if len(row) > max(ticker_i, quantity_i) and row[ticker_i].strip().upper() == "BTC"),
            None,
        )
        if btc_row is None:
            raise ValueError("IBIT BTC holding row not found")
        quantity = float(btc_row[quantity_i].replace(",", "").strip())
        if quantity <= 0:
            raise ValueError("IBIT BTC quantity must be positive")

        effective_at_ms = self._effective_ms(holdings_date)
        source_day = datetime.fromtimestamp(effective_at_ms / 1000, tz=timezone.utc).date().isoformat()
        yield FlowObservation(
            family="etf",
            metric="issuer_holdings_btc",
            asset="BTC",
            value=quantity,
            unit="BTC",
            effective_at_ms=effective_at_ms,
            available_at_ms=int(observed_at_ms),
            observed_at_ms=int(observed_at_ms),
            source=self.source,
            source_record_id=f"IBIT:{source_day}:BTC",
            cadence_seconds=86400,
            attribution_status="DIRECT",
            attribution_quality=1.0,
            data_quality=0.98,
            dependence_group="blackrock_ibit_official",
            provenance={
                "url": self.url,
                "issuer": "BlackRock/iShares",
                "product": "IBIT",
                "source_as_of_date": holdings_date,
                "effective_at_basis": "source_as_of_date_conservative_end_of_utc_day",
                "availability_basis": "collector_receipt_first_known",
                "publication_timestamp_exposed": False,
                "context_only": True,
                "semantic_guard": "issuer_btc_holdings_not_etf_cash_flow",
            },
            quality_flags=("NO_SOURCE_NATIVE_PUBLICATION_TIMESTAMP", "CURRENT_ONLY_FIRST_KNOWN_PIT"),
        )
