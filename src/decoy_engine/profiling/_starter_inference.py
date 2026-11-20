"""The starter decision for one column: which strategy `decoy scan` writes for it.

A behavior-exact port of the CLI's `_infer_strategy_for_column` at 8fba6af (SCAN-MULTI
S3-engine.1). The per-detector choices live in `recommendations.DETECTOR_DESCRIPTORS`; this
module holds only the decision order and the copy for the two cases no detector decides. It
keeps no detector table (`tests/unit/profiling/test_starter_inference.py` fails one).

The review copy was renamed in the port (the retired product word became "The scan"); the
decisions are ported exactly. The port keeps two CLI readings as they were, so the starter YAML does not move when the CLI
hands this over. The confident-match filter reads `confidence_bucket` with a `None` default;
the engine's `DetectorMatch` names that field `confidence`, so on a real match only the 0.5
match-rate rule decides. The ambiguity window is 0.1, strict. A fix to either is its own
change with a CHANGELOG line, and the parity fixture moves with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from decoy_engine.profiling import recommendations

__all__ = ["StarterDecision", "detected_date_config", "infer_starter_strategy"]

_AMBIGUITY_WINDOW = 0.1
_CONFIDENT_BUCKETS = ("high", "medium")
_CONFIDENT_RATE = 0.5

# Used when no detector matched, or the column has no clear default.
_FALLBACK_REVIEW = (
    "The scan did not flag this column as a known PII type. redact is the "
    "safe default; replace with passthrough if this column is intentionally "
    "kept verbatim, or pick a more appropriate strategy if your data "
    "carries PII the detectors missed."
)
# Used when several detectors fire on one column with comparable confidence.
_AMBIGUOUS_TEMPLATE = (
    "The scan detected multiple candidate signals ({signals}). The scaffolder "
    "picked {chosen} but the column may need a different strategy; review "
    "before running."
)
_INTEGER_KEY_REVIEW = (
    "No PII detector fired, but this column is a likely-unique "
    "integer (possible FK key). Hash preserves joinability; "
    "replace with passthrough if the column should be kept "
    "verbatim, or with faker if a real-shape replacement is "
    "preferred."
)


def _empty_mapping() -> Mapping[str, Any]:
    # A dataclass default must be hashable on 3.11+; a mappingproxy is not, so build one per instance.
    return MappingProxyType({})


@dataclass(frozen=True)
class StarterDecision:
    """The choice for one column: strategy, provider, starter settings and the review copy.

    `deterministic` is always False today; it is kept because the CLI's `Inference` carried it
    and the emitter writes `deterministic: true` when it is set.

    `detector_id` names the detector whose descriptor chose the strategy, and
    `confidence_bucket` is that match's bucket. Both are empty when no detector decided (the
    fallback and the integer-key rule), so a review can name what it is confirming.
    """

    strategy: str
    provider: str | None = None
    provider_config: Mapping[str, Any] = field(default_factory=_empty_mapping)
    review: str = ""
    deterministic: bool = False
    detector_id: str = ""
    confidence_bucket: str | None = None


_FALLBACK = StarterDecision(strategy="redact", review=_FALLBACK_REVIEW)


def detected_date_config(choice: recommendations.StarterChoice, match: Any) -> dict[str, Any] | None:
    """The choice's settings with the scan's date format, or None when no format can be written.

    None for a match with no variant, a variant that covers only part of the hits, or any hit
    that does not parse under it (`format_pattern_complete`), so a starter never writes a
    `date_shift` that would fail rows or not compile.
    """
    fmt = getattr(match, "format_pattern", None)
    if not isinstance(fmt, str) or getattr(match, "format_pattern_complete", False) is not True:
        return None
    return {**choice.provider_config, "date_format": fmt}


def _from_descriptor(detector_id: str, bucket: str | None, match: Any = None) -> StarterDecision:
    choice = recommendations.starter_choice(detector_id)
    if choice is None:
        return _FALLBACK
    provider_config: Mapping[str, Any] = choice.provider_config
    if choice.detected_date_format:
        detected = detected_date_config(choice, match)
        if detected is None:
            return _FALLBACK
        provider_config = MappingProxyType(detected)
    return StarterDecision(
        strategy=choice.strategy,
        provider=choice.provider,
        provider_config=provider_config,
        review=choice.review,
        detector_id=detector_id,
        confidence_bucket=bucket,
    )


def infer_starter_strategy(field_stats: Any) -> StarterDecision:
    """Pick a strategy for one column from its `FieldStats`.

    Decision order:
      1. A detector match that is confident (bucket high or medium, or match rate of 0.5 or
         more): take the starter choice of the highest-rate one. When a second confident match
         is within 0.1 of it, the review names up to three candidates and the top choice stays.
      2. No confident match and a likely-unique integer column: `hash` (a possible FK key).
      3. Otherwise `redact` with the louder review.

    Reads attributes only, so any object with `detector_matches`, `inferred_type` and
    `is_likely_unique` works.
    """
    matches = getattr(field_stats, "detector_matches", None) or []
    confident = [
        m
        for m in matches
        if getattr(m, "confidence_bucket", None) in _CONFIDENT_BUCKETS
        or getattr(m, "match_rate", 0.0) >= _CONFIDENT_RATE
    ]

    if confident:
        confident.sort(key=lambda m: -getattr(m, "match_rate", 0.0))
        top = confident[0]
        bucket = getattr(top, "confidence", None)
        base = _from_descriptor(
            getattr(top, "detector_id", ""), bucket if isinstance(bucket, str) else None, top
        )
        ambiguous = (
            len(confident) > 1
            and getattr(top, "match_rate", 0.0) - getattr(confident[1], "match_rate", 0.0)
            < _AMBIGUITY_WINDOW
        )
        if not ambiguous:
            return base
        signals = ", ".join(getattr(m, "detector_id", "?") for m in confident[:3])
        return StarterDecision(
            strategy=base.strategy,
            provider=base.provider,
            provider_config=base.provider_config,
            review=_AMBIGUOUS_TEMPLATE.format(signals=signals, chosen=base.strategy),
            deterministic=base.deterministic,
            detector_id=base.detector_id,
            confidence_bucket=base.confidence_bucket,
        )

    if getattr(field_stats, "inferred_type", "") == "integer" and getattr(
        field_stats, "is_likely_unique", False
    ):
        return StarterDecision(strategy="hash", review=_INTEGER_KEY_REVIEW)

    return _FALLBACK
