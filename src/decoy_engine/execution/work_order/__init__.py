"""Work-order support for plans whose ordinary dispatch order has a cycle.

A plan that orders today keeps its order and output byte for byte. Only when the ordinary sort
raises `cyclic_work_ordering` do these helpers apply: handlers still run in an order that
satisfies every value dependency (`ranks.fallback_order`), and each column's final value is
committed in dispatch-rank order, the last writer winning (`commits.FallbackCommits`).
"""

from decoy_engine.execution.work_order.commits import FallbackCommits, allocate_creator_targets
from decoy_engine.execution.work_order.ranks import commit_rank, fallback_order

__all__ = ["FallbackCommits", "allocate_creator_targets", "commit_rank", "fallback_order"]
