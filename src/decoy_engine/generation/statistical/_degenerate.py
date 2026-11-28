"""The one degenerate-snapshot rule: what makes a fitted distribution unsampleable.

A snapshot is degenerate when the column has nothing to draw from: a histogram without a
bin, counts or weights that are negative or not finite, or weights that add up to nothing
(an aggressively DP-noised release can clamp every count to zero). The sampler, window
admission and the compile check `check_statistical_columns` all ask this module, so a
config that `decoy validate` accepts is one `decoy run` accepts, with the same code.

Messages name the column and the member only, never a snapshot value or count.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING, NoReturn

from decoy_engine import reasons
from decoy_engine._config_text import Name, Problem, config_position, config_refusal
from decoy_engine.contracts.distribution_snapshot import (
    MAX_BIN_YEAR,
    SAMPLED_YEARS_RULE,
    names_unsupported_year,
    names_year_beyond,
)

if TYPE_CHECKING:
    from decoy_engine.generation.statistical._spec import StatisticalSpec

_REFIT_HINT = "Refit, or use a larger epsilon if the snapshot was DP-noised."


def column_label(column: object) -> str:
    """What a message calls a statistical column: the name when it is a plain approvable string,
    `<name>` for anything else (a list, a URL-shaped value), so a malformed name is never
    rendered."""
    return Name(column).shown()


def refuse_degenerate(column: str, why: str) -> NoReturn:
    """Raise the one coded refusal for an unsampleable snapshot of `column`."""
    # Lazy: `_spec` imports the modules that import this one.
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    raise StatisticalSpecError(
        code=reasons.plan.STATISTICAL_STATS_DEGENERATE,
        message=f"statistical column {column!r}: {why}.",
    ) from None


def _weights_unusable(weights: Sequence[float]) -> bool:
    """True for a negative or non-finite weight, or a total that is not finite and positive.

    Finite weights can add up to inf, which would pass a bare `total > 0`."""
    total = sum(weights)
    return (
        any(w < 0 or not math.isfinite(w) for w in weights)
        or not math.isfinite(total)
        or not total > 0
    )


def _histogram_finding(
    stats: dict, edges_key: str, counts_key: str, what: str
) -> tuple[str, str] | None:
    try:
        edges = [float(e) for e in stats.get(edges_key) or []]
        counts = [float(c) for c in stats.get(counts_key) or []]
    except (TypeError, ValueError, OverflowError):
        return edges_key, f"{edges_key} or {counts_key} is not numeric"
    if len(edges) < 2 or len(counts) != len(edges) - 1:
        return edges_key, f"snapshot {what} needs two edges and one count per bin"
    if _weights_unusable(counts):
        return counts_key, f"snapshot {what} counts are negative, not finite or add up to zero"
    return None


def _freetext_finding(spec: StatisticalSpec) -> tuple[str, str] | None:
    found = _histogram_finding(
        spec.stats, "length_bin_edges", "length_bin_counts", "length histogram"
    )
    if found is not None:
        return found
    edges = [float(e) for e in spec.stats["length_bin_edges"]]
    # A negative edge or any descending pair (endpoint or interior, e.g. [0, 100, 10]) makes the
    # sampler clamp every cell to one length, silently collapsing the distribution. Ties are fine.
    if edges[0] < 0 or any(b < a for a, b in pairwise(edges)):
        return "length_bin_edges", "length edges are negative or not non-decreasing"
    return None


def _categorical_finding(spec: StatisticalSpec) -> tuple[str, str] | None:
    # Lazy: `_sample` imports this module.
    from decoy_engine.generation.statistical._sample import (
        _categorical_tables,
        _conditional_tables,
    )

    try:
        values, weights = _categorical_tables(spec)
        other = float(spec.stats.get("other_count") or 0)
        conditional = _conditional_tables(spec) if spec.condition_on else {}
    except (TypeError, ValueError, KeyError, OverflowError):
        return "top_values", "top_values entries are malformed"
    if not values:
        return "top_values", "snapshot has no top_values"
    if _weights_unusable(weights):
        return "top_values", "top_values counts are negative, not finite or all zero"
    if other < 0 or not math.isfinite(other):  # a tail count that is never drawn is still a count
        return "other_count", "other_count is negative or not finite"
    if any(_weights_unusable(w) for _, w in conditional.values()):
        return "joint", "a conditional row has no usable weight"
    return None


def _datetime_finding(spec: StatisticalSpec) -> tuple[str, str] | None:
    buckets = spec.datetime_buckets
    if buckets is None:
        # A year outside the sampled range is unbounded, which window admission reports; any
        # other shape the decoder refused is a malformed block.
        if names_unsupported_year(spec.stats):
            return None
        return "year_bins", "year_bins entries are malformed"
    weights = [float(b.count) for b in buckets]
    if not buckets:
        return "year_bins", "snapshot has no year_bins"
    if _weights_unusable(weights):
        return "year_bins", "year_bins counts are negative, not finite or all zero"
    # An inverted range passes the per-bound checks but makes the sampler clamp every row to
    # `max` silently (a wrong value, not a crash). A missing, unparseable or mixed-timezone bound
    # is not this rule's business: window admission refuses those as unbounded.
    try:
        lo = datetime.fromisoformat(str(spec.stats["min"]))
        hi = datetime.fromisoformat(str(spec.stats["max"]))
        if lo > hi:
            return "min", "datetime min is after max"
    except (KeyError, ValueError, TypeError):
        pass
    return None


def names_far_year(spec: StatisticalSpec) -> bool:
    """True when a live year bin lies outside years 1 to 9999 (a zero-weight bin is never drawn)."""
    buckets = spec.datetime_buckets
    if buckets is None:
        return names_unsupported_year(spec.stats)
    return names_year_beyond(buckets, MAX_BIN_YEAR)


def degenerate_finding(spec: StatisticalSpec) -> tuple[str, str] | None:
    """`(property, reason)` for the first degenerate rule `spec` breaks, else None.

    The property names the snapshot member (`bin_counts`, `year_bins`, ...) so a caller that
    reports a position, like window admission, can name it. A flag token that is not
    canonical raises its own coded error from the table read; this rule does not mask it."""
    if spec.kind == "numeric":
        return _histogram_finding(spec.stats, "bin_edges", "bin_counts", "histogram")
    if spec.kind == "freetext":
        return _freetext_finding(spec)
    if spec.kind == "categorical":
        return _categorical_finding(spec)
    if spec.kind == "datetime":
        return _datetime_finding(spec)
    return None


def _refuse_far_year(spec: StatisticalSpec) -> NoReturn:
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    refusal = config_refusal(
        config_position("statistical", Name(spec.column)),
        Problem.NOT_ALLOWED,
        hint=SAMPLED_YEARS_RULE,
    )
    raise StatisticalSpecError(code=reasons.plan.GENERATION_UNBOUNDED_COLUMN, message=refusal.text)


def check_degenerate(spec: StatisticalSpec) -> None:
    """Raise `STATISTICAL_STATS_DEGENERATE` when `spec`'s snapshot cannot be sampled, or
    `GENERATION_UNBOUNDED_COLUMN` when a datetime snapshot names a year the sampler cannot hold."""
    if spec.kind == "datetime" and names_far_year(spec):
        _refuse_far_year(spec)
    finding = degenerate_finding(spec)
    if finding is not None:
        refuse_degenerate(column_label(spec.column), f"{finding[1]}. {_REFIT_HINT}")
