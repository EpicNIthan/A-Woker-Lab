from __future__ import annotations

import json
import re
from datetime import datetime, time, timezone
from html import unescape
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from .contracts import FlowObservation, iso_to_ms

ABTC_CIK = "0001755953"
ABTC_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{ABTC_CIK}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/1755953"

_TAG_RE = re.compile(r"<[^>]+>")
_HOLDINGS_RE = re.compile(
    r"(?:accumulated|held|holds?|totaling)\s+(?:approximately\s+)?([\d,]+)\s+bitcoin(?:s)?"
    r"(?:\s+as\s+a\s+standalone\s+entity)?\s+as\s+of\s+"
    r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


class AmericanBitcoinTreasuryCollector:
    """Collect American Bitcoin Corp BTC reserve from first-party SEC filings.

    SEC acceptance time is the point-in-time availability boundary. Filing text
    supplies the separate economic as-of date and explicit standalone-company
    scope. Accessions are retained as revision identity, so amendments cannot
    rewrite history. This evidence is context-only, never a directional flow.
    """

    source = "SEC EDGAR American Bitcoin Corp filings"
    submissions_url = ABTC_SUBMISSIONS_URL

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
        if "american bitcoin corp" not in lower or "standalone entity" not in lower:
            return None
        match = _HOLDINGS_RE.search(text)
        if match is None:
            return None
        return float(match.group(1).replace(",", "")), match.group(2)

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
                raise ValueError("American Bitcoin BTC holdings must be positive")
            effective_at_ms = self._effective_at_ms(as_of_text)
            if effective_at_ms > available_at_ms:
                raise ValueError("American Bitcoin filing effective date cannot be after SEC acceptance")
            effective_day = datetime.fromtimestamp(effective_at_ms / 1000, tz=timezone.utc).date().isoformat()
            record_id = f"american-bitcoin-corp:{effective_day}:btc-holdings"
            yield FlowObservation(
                family="treasury",
                metric="corporate_holdings_btc_context",
                asset="BTC",
                value=value,
                unit="BTC",
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
                dependence_group="american_bitcoin_sec_corporate_treasury",
                provenance={
                    "url": url,
                    "submissions_url": self.submissions_url,
                    "cik": ABTC_CIK,
                    "form": form,
                    "accession_number": accession,
                    "entity_scope": "American Bitcoin Corp standalone entity",
                    "source_as_of_date": as_of_text,
                    "effective_at_basis": "explicit_filing_as_of_date_conservative_end_of_utc_day",
                    "availability_basis": "sec_acceptance_datetime",
                    "publication_timestamp_exposed": True,
                    "context_only": True,
                    "semantic_guard": "corporate_treasury_holdings_not_flow_or_price_direction",
                },
                quality_flags=("CONTEXT_ONLY", "FIRST_PARTY_SEC_FILING"),
            )
            return
        raise ValueError("no eligible American Bitcoin BTC holdings filing found")
