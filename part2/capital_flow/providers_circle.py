from __future__ import annotations

import json
import re
from datetime import datetime, time, timezone
from html import unescape
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from .contracts import FlowObservation, iso_to_ms

CIRCLE_CIK = "0001876042"
CIRCLE_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIRCLE_CIK}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/1876042"

_TAG_RE = re.compile(r"<[^>]+>")
_USDC_RE = re.compile(
    r"USDC\s+in\s+circulation[^$]{0,160}\$\s*([\d,.]+)\s*(billion|million)",
    re.IGNORECASE,
)
_AS_OF_RE = re.compile(r"(?:as\s+of|at)\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)


class CircleUsdcCirculationCollector:
    """Collect Circle USDC circulation from first-party SEC filings.

    This is context-only stablecoin liquidity evidence. SEC acceptance time is
    the causal availability boundary; filing text supplies the economic as-of
    date. Accessions preserve revision identity so amendments cannot rewrite
    point-in-time history.
    """

    source = "SEC EDGAR Circle Internet Group filings"
    submissions_url = CIRCLE_SUBMISSIONS_URL

    def __init__(
        self,
        *,
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
        fetch_text: Callable[[str], str] | None = None,
    ) -> None:
        self._fetch_json = fetch_json or self._download_json
        self._fetch_text = fetch_text or self._download_text

    @staticmethod
    def _request(url: str) -> Request:
        return Request(
            url,
            headers={
                "User-Agent": "AnataCapitalFlow/1.0 public-specialist-lab",
                "Accept-Encoding": "identity",
            },
        )

    @classmethod
    def _download_json(cls, url: str) -> dict[str, Any]:
        with urlopen(cls._request(url), timeout=20) as response:  # noqa: S310 - fixed SEC HTTPS source
            return json.loads(response.read().decode("utf-8"))

    @classmethod
    def _download_text(cls, url: str) -> str:
        with urlopen(cls._request(url), timeout=20) as response:  # noqa: S310 - fixed SEC HTTPS source
            return response.read().decode("utf-8", errors="replace")

    @staticmethod
    def _filing_url(accession: str, primary_document: str) -> str:
        return f"{SEC_ARCHIVES_BASE}/{accession.replace('-', '')}/{primary_document}"

    @staticmethod
    def _plain_text(document: str) -> str:
        return " ".join(unescape(_TAG_RE.sub(" ", document)).replace("\xa0", " ").split())

    @staticmethod
    def _effective_at_ms(day_text: str) -> int:
        day = datetime.strptime(day_text, "%B %d, %Y").date()
        return int(datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _extract(text: str) -> tuple[float, str] | None:
        lower = text.lower()
        if "circle internet group" not in lower or "usdc" not in lower:
            return None
        amount = _USDC_RE.search(text)
        if amount is None:
            return None
        window = text[max(0, amount.start() - 220): amount.end() + 220]
        as_of = _AS_OF_RE.search(window)
        if as_of is None:
            return None
        multiplier = 1_000_000_000 if amount.group(2).lower() == "billion" else 1_000_000
        return float(amount.group(1).replace(",", "")) * multiplier, as_of.group(1)

    def collect(self, *, observed_at_ms: int, include_backfill: bool = False) -> Iterable[FlowObservation]:
        del include_backfill
        payload = self._fetch_json(self.submissions_url)
        recent = ((payload.get("filings") or {}).get("recent") or {})
        required = ("accessionNumber", "form", "acceptanceDateTime", "primaryDocument")
        if not all(isinstance(recent.get(key), list) for key in required):
            raise ValueError("unexpected SEC submissions schema")

        candidates: list[tuple[int, str, str, str]] = []
        for accession, form, accepted, primary in zip(*(recent[key] for key in required)):
            if str(form) not in {"10-Q", "10-Q/A"} or not accession or not accepted or not primary:
                continue
            available_at_ms = iso_to_ms(str(accepted))
            if available_at_ms <= int(observed_at_ms):
                candidates.append((available_at_ms, str(accession), str(form), str(primary)))

        for available_at_ms, accession, form, primary in sorted(candidates, reverse=True):
            url = self._filing_url(accession, primary)
            parsed = self._extract(self._plain_text(self._fetch_text(url)))
            if parsed is None:
                continue
            value, as_of_text = parsed
            if value <= 0:
                raise ValueError("Circle USDC circulation must be positive")
            effective_at_ms = self._effective_at_ms(as_of_text)
            if effective_at_ms > available_at_ms:
                raise ValueError("Circle filing effective date cannot be after SEC acceptance")
            effective_day = datetime.fromtimestamp(effective_at_ms / 1000, tz=timezone.utc).date().isoformat()
            record_id = f"circle-internet-group:{effective_day}:usdc-circulation"
            yield FlowObservation(
                family="stablecoin",
                metric="issuer_usdc_circulation_context",
                asset="USDC",
                value=value,
                unit="USD",
                effective_at_ms=effective_at_ms,
                available_at_ms=available_at_ms,
                observed_at_ms=int(observed_at_ms),
                source=self.source,
                source_record_id=record_id,
                revision=accession,
                cadence_seconds=90 * 86400,
                attribution_status="DIRECT",
                attribution_quality=1.0,
                data_quality=1.0,
                economic_event_id=record_id,
                dependence_group="circle_sec_usdc_circulation",
                provenance={
                    "url": url,
                    "submissions_url": self.submissions_url,
                    "cik": CIRCLE_CIK,
                    "form": form,
                    "accession_number": accession,
                    "entity_scope": "Circle Internet Group Inc and subsidiaries",
                    "source_as_of_date": as_of_text,
                    "effective_at_basis": "explicit_filing_as_of_date_conservative_end_of_utc_day",
                    "availability_basis": "sec_acceptance_datetime",
                    "publication_timestamp_exposed": True,
                    "context_only": True,
                    "semantic_guard": "usdc_circulation_stock_not_mint_redeem_flow_or_price_direction",
                },
                quality_flags=("CONTEXT_ONLY", "FIRST_PARTY_SEC_FILING"),
            )
            return
        raise ValueError("no eligible Circle USDC circulation filing found")
