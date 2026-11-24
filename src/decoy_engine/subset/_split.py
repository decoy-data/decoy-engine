"""Split a pipeline config into the run config and the subset request it carries.

The run config keeps the `subset` key (set to `None`) so its dump, and the config hash the
plan stamps, equal those of a config that never had a subset block. The fingerprint is the
subset half of a run's identity: a subset run shares its config hash with the full run on
purpose, so the pair `(pipeline_config_hash, fingerprint)` is what tells them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from decoy_engine.subset._api import subset_request_from_config
from decoy_engine.subset._edges import build_subset_edges
from decoy_engine.subset._policy import resolve_edge_directions
from decoy_engine.subset._scope import SubsetRequest


@dataclass(frozen=True)
class SubsetSplit:
    run_config: dict[str, Any]
    request: SubsetRequest | None
    fingerprint: str | None


def drop_subset_block(config: dict[str, Any]) -> dict[str, Any]:
    """The run config: `config` with its `subset` block set to `None`, or `config` itself when
    it has no block (a missing key and `None` hash differently, so none is added)."""
    if config.get("subset") is None:
        return config
    return {**config, "subset": None}


def split_subset_config(config: dict[str, Any]) -> SubsetSplit:
    """Split off the `subset:` block. Refuses a bad edge direction here, before any source is
    read, so every caller that splits a config gets the check (`_compute` repeats it for a
    hand-built request)."""
    request = subset_request_from_config(config)
    if request is None:
        return SubsetSplit(config, None, None)
    resolve_edge_directions(build_subset_edges(request.relationships), request.policy)
    return SubsetSplit(drop_subset_block(config), request, request.fingerprint())
