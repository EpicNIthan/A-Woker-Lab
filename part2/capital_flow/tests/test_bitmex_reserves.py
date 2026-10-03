from __future__ import annotations

import pytest

from part2.capital_flow.providers_bitmex import BitmexReserveCollector


def _listing(*items: tuple[str, str, str]) -> str:
    rows = "".join(
        f"<Contents><Key>{key}</Key><LastModified>{modified}</LastModified><ETag>{etag}</ETag></Contents>"
        for key, modified, etag in items
    )
    return f'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{rows}</ListBucketResult>'


def test_bitmex_reserve_collector_uses_latest_first_party_publication_clock() -> None:
    old = ("data/porl/reserves-900000-20260929D120000000000000.yaml", "2026-09-29T12:05:00.000Z", '"old"')
    latest = ("data/porl/20261001-reserves-900288-20261001D120000000000000.yaml", "2026-10-01T12:07:30.000Z", '"new"')
    seen: list[str] = []
    collector = BitmexReserveCollector(
        fetch_listing=lambda _url: _listing(old, latest),
        fetch_head=lambda url: seen.append(url) or "height: 900288\nchain: main\ntotal: 1234567890123\nkeys:\n",
    )
    rows = list(collector.collect(observed_at_ms=1790856600000))
    assert len(rows) == 1
    obs = rows[0]
    assert obs.family == "exchange_btc"
    assert obs.metric == "published_reserve_btc"
    assert obs.value == pytest.approx(12345.67890123)
    assert obs.available_at_ms == 1790856450000
    assert obs.effective_at_ms == 1790856000000
    assert obs.provenance["proof_block_height"] == 900288
    assert obs.provenance["context_only"] is True
    assert obs.provenance["availability_basis"] == "first_party_object_last_modified"
    assert "RESERVE_LEVEL_NOT_FLOW" in obs.quality_flags
    assert seen == ["https://public.bitmex.com/data/porl/20261001-reserves-900288-20261001D120000000000000.yaml"]


def test_bitmex_reserve_collector_fails_closed_when_publication_is_in_future() -> None:
    item = ("data/porl/reserves-900288-20261001D120000000000000.yaml", "2026-10-01T12:07:30.000Z", '"x"')
    collector = BitmexReserveCollector(
        fetch_listing=lambda _url: _listing(item),
        fetch_head=lambda _url: "height: 900288\ntotal: 123456789\n",
    )
    with pytest.raises(ValueError, match="later than collector receipt"):
        list(collector.collect(observed_at_ms=1790856400000))


@pytest.mark.parametrize(
    "listing,header,error",
    [
        (_listing(("data/porl/liabilities-900288-proof.dat", "2026-10-01T12:07:30Z", '"x"')), "height: 1\ntotal: 1\n", "reserve proof object missing"),
        (_listing(("data/porl/reserves-900288-20261001D120000.yaml", "2026-10-01T12:07:30Z", '"x"')), "height: 900288\nkeys:\n", "header missing"),
    ],
)
def test_bitmex_reserve_collector_preserves_explicit_missingness(listing: str, header: str, error: str) -> None:
    collector = BitmexReserveCollector(fetch_listing=lambda _url: listing, fetch_head=lambda _url: header)
    with pytest.raises(ValueError, match=error):
        list(collector.collect(observed_at_ms=1790856600000))


def test_bitmex_reserve_contract_is_context_only_and_not_backfill_safe() -> None:
    from part2.capital_flow.providers_bitmex import BITMEX_RESERVES_CONTRACT

    assert BITMEX_RESERVES_CONTRACT.family == "exchange_btc"
    assert BITMEX_RESERVES_CONTRACT.point_in_time_backfill_safe is False
    assert "not deposit/withdrawal flow" in BITMEX_RESERVES_CONTRACT.attribution_assumptions
