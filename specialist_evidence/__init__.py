"""Evidence-layer contracts shared by Specialist handoffs.

This package validates causal metadata only. It does not compose evidence,
rank Specialists, predict direction, or grant execution authority.
"""

from .snapshot_quality import HandoffClock, HandoffQuality, assess_handoff_quality

__all__ = ["HandoffClock", "HandoffQuality", "assess_handoff_quality"]
