from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import FlowObservation
from .engine import CapitalFlowEngine, CapitalFlowFrame
from .output import CapitalFlowOutput, CapitalFlowOutputBuilder

REPLAY_SCHEMA_VERSION = "cf-replay-v1"


@dataclass(frozen=True, slots=True)
class ReplayPoint:
    as_of_ms: int
    frame: CapitalFlowFrame
    output: CapitalFlowOutput


class CapitalFlowReplay:
    """Causal replay over archived observations.

    The engine itself enforces `available_at <= as_of`. Keeping replay thin makes
    it difficult for an alternate offline path to accidentally bypass that rule.
    """

    def __init__(self) -> None:
        self.engine = CapitalFlowEngine()
        self.output_builder = CapitalFlowOutputBuilder()

    def at(self, observations: Iterable[FlowObservation], *, as_of_ms: int) -> ReplayPoint:
        frame = self.engine.build(observations, as_of_ms=as_of_ms)
        return ReplayPoint(as_of_ms=as_of_ms, frame=frame, output=self.output_builder.build(frame))

    def series(
        self,
        observations: Iterable[FlowObservation],
        *,
        as_of_times_ms: Iterable[int],
    ) -> list[ReplayPoint]:
        cached = list(observations)
        return [self.at(cached, as_of_ms=int(timestamp)) for timestamp in as_of_times_ms]
