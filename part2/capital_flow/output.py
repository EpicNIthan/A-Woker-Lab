from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .engine import CapitalFlowFrame

OUTPUT_SCHEMA_VERSION = "cf-output-v1"


@dataclass(frozen=True, slots=True)
class CapitalFlowOutput:
    as_of_ms: int
    known: bool
    flow_state: str
    capital_inflow_score: float | None
    btc_to_liquid_venues_score: float | None
    holder_accumulation_score: float | None
    family_scores: Mapping[str, float | None]
    horizons: Mapping[str, Mapping[str, float | None]]
    flow_strength: float | None
    flow_change: float | None
    flow_persistence: float | None
    family_agreement: float | None
    evidence_independence: float | None
    coverage: float
    data_quality: float | None
    freshness: float | None
    attribution_quality: float | None
    source_agreement: float | None
    flow_clarity: float | None
    unknown_reasons: tuple[str, ...]
    audit_flags: tuple[str, ...]
    asset: str = "BTC"
    specialist: str = "capital_flow"
    schema_version: str = OUTPUT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "specialist": self.specialist,
            "asset": self.asset,
            "as_of_ms": self.as_of_ms,
            "known": self.known,
            "flow_state": self.flow_state,
            "capital_inflow_score": self.capital_inflow_score,
            "btc_to_liquid_venues_score": self.btc_to_liquid_venues_score,
            "holder_accumulation_score": self.holder_accumulation_score,
            "etf_flow": self.family_scores.get("etf"),
            "exchange_btc_flow": self.family_scores.get("exchange_btc"),
            "stablecoin_liquidity": self.family_scores.get("stablecoin"),
            "whale_flow": self.family_scores.get("whale_lth"),
            "miner_flow": self.family_scores.get("miner"),
            "treasury_flow": self.family_scores.get("treasury"),
            "horizons": {name: dict(values) for name, values in self.horizons.items()},
            "flow_strength": self.flow_strength,
            "flow_change": self.flow_change,
            "flow_persistence": self.flow_persistence,
            "family_agreement": self.family_agreement,
            "evidence_independence": self.evidence_independence,
            "coverage": self.coverage,
            "data_quality": self.data_quality,
            "freshness": self.freshness,
            "attribution_quality": self.attribution_quality,
            "source_agreement": self.source_agreement,
            "flow_clarity": self.flow_clarity,
            "unknown_reasons": list(self.unknown_reasons),
            "audit_flags": list(self.audit_flags),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


class CapitalFlowOutputBuilder:
    def build(self, frame: CapitalFlowFrame) -> CapitalFlowOutput:
        horizons = {
            horizon: {
                "capital_inflow_score": axes.get("capital_inflow_score"),
                "btc_to_liquid_venues_score": axes.get("btc_to_liquid_venues_score"),
                "holder_accumulation_score": axes.get("holder_accumulation_score"),
                "flow_strength": axes.get("flow_strength"),
            }
            for horizon, axes in frame.horizon_axes.items()
        }
        return CapitalFlowOutput(
            as_of_ms=frame.as_of_ms,
            known=frame.known,
            flow_state=frame.flow_state,
            capital_inflow_score=frame.capital_inflow_score,
            btc_to_liquid_venues_score=frame.btc_to_liquid_venues_score,
            holder_accumulation_score=frame.holder_accumulation_score,
            family_scores=dict(frame.family_scores),
            horizons=horizons,
            flow_strength=frame.flow_strength,
            flow_change=frame.flow_change,
            flow_persistence=frame.flow_persistence,
            family_agreement=frame.family_agreement,
            evidence_independence=frame.evidence_independence,
            coverage=frame.coverage,
            data_quality=frame.data_quality,
            freshness=frame.freshness,
            attribution_quality=frame.attribution_quality,
            source_agreement=frame.source_agreement,
            flow_clarity=frame.flow_clarity,
            unknown_reasons=frame.unknown_reasons,
            audit_flags=frame.audit_flags,
        )
