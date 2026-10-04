from __future__ import annotations

import json
import re
from datetime import datetime, time, timezone
from html import unescape
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from .contracts import FlowObservation, iso_to_ms

STRATEGY_CIK = "0001050446"
STRATEGY_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{STRATEGY_CIK}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/1050446"

_HOLDINGS_RE = re.compile(
    r"(?:holds?|held)(?:\s+an\s+aggregate\s+of)?\s+(?:approximately\s+)?([\d,]+)\s+bitcoin(?:s)?",
    re.IGNORECASE,
)
_AS_OF_RE = re.compile(r"as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


class StrategyTreasuryCollector:
    """Collect Strategy corporate BTC holdings from first-party SEC filings.

    SEC acceptance time is the causal availability boundary. The holdings
    effective date is parsed separately from filing text. Amendments/re-filings
    remain later revisions of the same entity/date record instead of overwriting
    earlier point-in-time state. The observation is context-only and is not one
    of Capital Flow's frozen directional treasury metrics.
    """

    source = "SEC EDGAR Strategy filings"
    submissions_url = STRATEGY_SUBMISSIONS_URL

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
        accession_compact = accession.replace("-", "")
        return f"{SEC_ARCHIVES_BASE}/{accession_compact}/{primary_document}"

    @staticmethod
    def _plain_text(document: str) -> str:
        return " ".join(unescape(_TAG_RE.sub(" ", document)).replace("\xa0", " ").split())

    @staticmethod
    def _effective_at_ms(day_text: str) -> int:
        day = datetime.strptime(day_text, "%B %d, %Y").date()
        return int(datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _entity_scope(text: str) -> str | None:
        lower = text.lower()
        if "strategy, together with its subsidiaries" in lower or "company, together with its subsidiaries" in lower:
            return "Strategy Inc and subsidiaries"
        if "microstrategy, together with its subsidiaries" in lower:
            return "MicroStrategy Incorporated and subsidiaries"
        if "strategy holds" in lower or "strategy inc" in lower:
            return "Strategy Inc"
        if "microstrategy" in lower:
            return "MicroStrategy Incorporated"
        return None

    def collect(self, *, observed_at_ms: int, include_backfill: bool = False) -> Iterable[FlowObservation]:
        del include_backfill  # SEC recent filings are screened by their native acceptance clock.
        payload = self._fetch_json(self.submissions_url)
        recent = ((payload.get("filings") or {}).get("recent") or {})
        required = ("accessionNumber", "form", "acceptanceDateTime", "primaryDocument")
        if not all(isinstance(recent.get(key), list) for key in required):
            raise ValueError("unexpected SEC submissions schema")

        rows = zip(*(recent[key] for key in required))
        candidates: list[tuple[int, str, str, str]] = []
        for accession, form, accepted, primary in rows:
            if str(form) not in {"8-K", "8-K/A"}:
                continue
            if not accession or not accepted or not primary:
                continue
            available_at_ms = iso_to_ms(str(accepted))
            if available_at_ms <= int(observed_at_ms):
                candidates.append((available_at_ms, str(accession), str(form), str(primary)))

        for available_at_ms, accession, form, primary in sorted(candidates, reverse=True):
            url = self._filing_url(accession, primary)
            text = self._plain_text(self._fetch_text(url))
            holding_match = _HOLDINGS_RE.search(text)
            as_of_match = _AS_OF_RE.search(text)
            entity_scope = self._entity_scope(text)
            if holding_match is None or as_of_match is None or entity_scope is None:
                continue
            value = float(holding_match.group(1).replace(",", ""))
            if value <= 0:
                raise ValueError("Strategy BTC holdings must be positive")
            effective_at_ms = self._effective_at_ms(as_of_match.group(1))
            if effective_at_ms > available_at_ms:
                raise ValueError("Strategy filing effective date cannot be after SEC acceptance")

            entity_key = re.sub(r"[^a-z0-9]+", "-", entity_scope.lower()).strip("-")
            effective_day = datetime.fromtimestamp(effective_at_ms / 1000, tz=timezone.utc).date().isoformat()
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
                source_record_id=f"strategy:{entity_key}:{effective_day}:btc-holdings",
                revision=accession,
                cadence_seconds=7 * 86400,
                attribution_status="DIRECT",
                attribution_quality=1.0,
                data_quality=1.0,
                economic_event_id=f"strategy:{entity_key}:{effective_day}:btc-holdings",
                dependence_group="strategy_sec_corporate_treasury",
                provenance={
                    "url": url,
                    "submissions_url": self.submissions_url,
                    "cik": STRATEGY_CIK,
                    "form": form,
                    "accession_number": accession,
                    "entity_scope": entity_scope,
                    "source_as_of_date": as_of_match.group(1),
                    "effective_at_basis": "explicit_filing_as_of_date_conservative_end_of_utc_day",
                    "availability_basis": "sec_acceptance_datetime",
                    "publication_timestamp_exposed": True,
                    "context_only": True,
                    "semantic_guard": "corporate_treasury_holdings_not_flow_or_price_direction",
                },
                quality_flags=("CONTEXT_ONLY", "FIRST_PARTY_SEC_FILING"),
            )
            return
        raise ValueError("no eligible Strategy BTC holdings filing found")
