from __future__ import annotations

from .contracts import FAMILIES, FlowObservation
from .engine import CORE_FAMILIES, STALE_AFTER_SECONDS, CapitalFlowEngine, _mean


class CapitalFlowEngineV11(CapitalFlowEngine):
    """V1.1 engine wrapper with source-cadence-aware freshness.

    Directional scoring and state classification remain inherited from the frozen
    deterministic engine. Only freshness/staleness semantics are upgraded so a
    legitimate daily source is not judged by the 12-hour limit intended for a
    faster exchange-flow feed.
    """

    @staticmethod
    def _freshness(
        observations: list[FlowObservation],
        as_of_ms: int,
    ) -> tuple[float | None, bool]:
        family_scores: list[float] = []
        stale_core = False

        for family in FAMILIES:
            family_obs = [
                obs
                for obs in observations
                if obs.family == family and obs.available_at_ms is not None
            ]
            if not family_obs:
                continue

            candidate_scores: list[float] = []
            candidate_is_fresh: list[bool] = []

            for obs in family_obs:
                age = max(0.0, (as_of_ms - obs.effective_at_ms) / 1000.0)
                limit = float(STALE_AFTER_SECONDS[family])

                # Preserve the original family limit for fast sources. For a slower
                # source, allow up to two source cadences after the completed bucket
                # becomes effective. This is source-aware rather than silently
                # relaxing every exchange observation to a daily threshold.
                if obs.cadence_seconds:
                    limit = max(limit, 2.0 * float(obs.cadence_seconds))

                score = max(0.0, 1.0 - age / limit)
                candidate_scores.append(score)
                candidate_is_fresh.append(age <= limit)

            # A family is usable when at least one current source representation is
            # still fresh under its own cadence. This supports graceful multi-source
            # fallback without letting an old stale source poison a newer one.
            family_scores.append(max(candidate_scores))
            if family in CORE_FAMILIES and not any(candidate_is_fresh):
                stale_core = True

        return _mean(family_scores), stale_core
