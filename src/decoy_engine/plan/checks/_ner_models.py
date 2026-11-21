"""The NER model each surface of a run resolves to, for the resume fingerprint.

A resume must not keep tables masked with one model and finish the rest with another, so the
fingerprint records the model of every NER surface. This reads the effective config dict and
walks every strategy site (nested children included) and asks the one resolver in `detection.ner`; it names surfaces and models, never a table or column.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from decoy_engine.config import post_scan_integrity_requested
from decoy_engine.detection.ner import NerSurface, resolve_column_ner, resolve_ner_model
from decoy_engine.plan.checks._strategy_sites import strategy_sites

__all__ = ["run_ner_models"]

_COLUMN_SURFACES = (NerSurface.TEXT_REDACT, NerSurface.TEXT_MASK)


def _ner_model_of(block: object) -> str | None:
    """The resolved model of a scan block that lists `ner` in its detectors, else None."""
    if not isinstance(block, Mapping) or "ner" not in (block.get("detectors") or ()):
        return None
    return resolve_ner_model(block.get("ner_model"))


def run_ner_models(config: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Sorted unique `(surface, model)` pairs for every NER surface the run uses."""
    found: set[tuple[str, str]] = set()
    if (pre := _ner_model_of(config.get("pre_scan"))) is not None:
        found.add((NerSurface.PRE_SCAN.value, pre))
    if post_scan_integrity_requested(config) and (
        (post := _ner_model_of(config.get("post_scan"))) is not None
    ):
        found.add((NerSurface.POST_SCAN.value, post))
    for site in strategy_sites(config):
        if site.strategy not in {s.value for s in _COLUMN_SURFACES}:
            continue
        options = site.config
        model = resolve_column_ner(options.get("ner") if isinstance(options, Mapping) else None)[0]
        if model is not None:
            found.add((str(site.strategy), model))
    return tuple(sorted(found))
