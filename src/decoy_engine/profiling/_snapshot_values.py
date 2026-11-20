"""The distribution snapshot `decoy fit` writes, with value-sensitive columns' cells withheld.

Sensitive columns, stats and the marker come from `_value_redaction.py`, as for a scan document;
this module applies the rules that need the data.

Every column the profiler did not flag gets a floor (`SNAPSHOT_FLOOR_STATS`): no label, joint
cell or year range is held by fewer than `MIN_RELEASE_COUNT` rows, and a numeric range is top and
bottom coded. A column too small to floor is flagged and listed. Minimum frequency rule, top and
bottom coding, global recoding: Hundepool et al., Statistical Disclosure Control (Wiley 2012),
sections 3.4 and 4.2; R sdcMicro `topBotCoding` and `globalRecode`; R synthpop `sdc()`.
Pattern: statistical disclosure control global recoding; HIPAA Safe Harbor year-only dates.
The 1, 2, 5 step ladder: Heckbert, "Nice numbers for graph labels" (Graphics Gems, 1990). The
finest level that passes is searched for as in ARX and Samarati's lattice of recodings.

A flagged numeric column is one coarse interval on a power-of-ten grid strictly outside its
cells; near float max the bounds are the fixed (-1.5, 1.5). Datetimes are bounded by the years
around them (HIPAA Safe Harbor, 45 CFR 164.514(b)(2)(i)(C)).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from itertools import islice, pairwise
from typing import Any, Final

import numpy as np
import pandas as pd

from decoy_engine import reasons
from decoy_engine.contracts.distribution_snapshot import (
    MAX_SAMPLED_YEAR,
    SCHEMA_VERSION_V2,
    DatetimeBucket,
    encode_datetime_buckets,
)
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.internal.pandas_compat import finite_numeric_cells
from decoy_engine.profiling._value_redaction import (
    DATA_RULES,
    MIN_RELEASE_COUNT,
    REDACTED_COLUMNS_KEY,
    REDACTED_POLICIES,
    VALUE_POLICY_KEY,
    Rule,
    _apply,
    snapshot_floor_rules,
    snapshot_keeper,
    snapshot_rules,
    stamp_value_policy,
    value_sensitive_names,
)
from decoy_engine.profiling.cell_format import add_cell_format, scrub_cell_format
from decoy_engine.profiling.profiler import profile_columns
from decoy_engine.quality.snapshot import (
    DEFAULT_CATEGORICAL_TOP_K,
    DEFAULT_CONTINGENCY_TOP_K,
    DEFAULT_NUMERIC_BINS,
    DistributionSnapshotError,
    check_contingency_top_k,
    compute_distribution_snapshot,
    freetext_stats,
    numeric_stats,
)

# 12 decimal places are written, so a finer grid step could not be.
_FLOOR: Final = Decimal(1).scaleb(-12)
_PRECISION: Final = 80
_FALLBACK_DOMAIN: Final = (-1.5, 1.5)
_NICE_MANTISSAS: Final = (1, 2, 5)  # Heckbert steps
_MAX_STEP_TRIES: Final = 64
_SHAPE_BLOCKS: Final = ("quantile_grid", "exact_values")  # a fallback domain pops these
# A string column whose median label has this many words reads as sentences, so it is free text.
FREETEXT_MIN_WORDS: Final = 3


def _grid_step(d_lo: Decimal, d_hi: Decimal) -> Decimal:
    """The power-of-ten step that exceeds the range, never below the writable floor. Call inside a context."""
    span = d_hi - d_lo if d_hi > d_lo else max(abs(d_lo), Decimal(1))
    mag = max(abs(d_lo), abs(d_hi), Decimal(1))
    return max(
        Decimal(1).scaleb(span.adjusted() + 1),
        Decimal(1).scaleb(mag.adjusted() - 12),
        _FLOOR,
    )


def _grid_edges(lo: float, hi: float) -> tuple[Decimal, Decimal]:
    """Bounds on a power-of-ten grid strictly outside `[lo, hi]`, in exact decimal arithmetic.

    Float arithmetic put a real extreme back on the grid for about 7% of decimal-grid inputs,
    so everything starts from the written float's repr. The step exceeds the range, so each
    extreme is known only to within a step wider than the range itself.
    """
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        d_lo, d_hi = Decimal(repr(lo)), Decimal(repr(hi))
        step = _grid_step(d_lo, d_hi)
        lower = (d_lo / step).to_integral_value(ROUND_FLOOR) * step - step
        upper = (d_hi / step).to_integral_value(ROUND_FLOOR) * step + 2 * step
    return lower, upper


def _coarse_domain(lo: float, hi: float, cells: np.ndarray) -> tuple[float, float]:
    """The one-bin domain for a numeric column: grid bounds, or a fixed domain near float max.

    The fallback never reads the data, so it reveals nothing even when it equals a cell.
    """
    lower, upper = _grid_edges(lo, hi)
    try:
        flo, fhi = float(lower), float(upper)
    except OverflowError:
        flo, fhi = math.inf, math.inf
    if math.isfinite(flo) and math.isfinite(fhi) and flo < cells.min() and fhi > cells.max():
        return flo, fhi
    return _FALLBACK_DOMAIN


def _coarse_range(non_null: pd.Series, stats: dict[str, Any], keys: Collection[str]) -> None:
    if stats.get("min") is None:
        return  # no finite cell, so nothing here is a value
    cells = finite_numeric_cells(non_null)
    domain = _coarse_domain(stats["min"], stats["max"], cells)
    coarse = numeric_stats(non_null, bins=1, domain=domain)
    for key in keys:
        stats[key] = coarse[key]


def _year_edge(rule: Rule, stats: dict[str, Any]) -> str | None:
    """The flagged column's bound, one year outside the folded ranges (read after `fold_year_bins`)."""
    ranges = stats.get("year_bins", [])
    if not ranges:
        return None
    # Clamp to the calendar's ends: year 0 and year 10000 do not parse back as datetimes.
    if rule is Rule.PREVIOUS_YEAR_START:
        return f"{max(ranges[0]['start_year'] - 1, 1):04d}-01-01T00:00:00"
    return f"{min(ranges[-1]['end_year'] + 1, 9999):04d}-12-31T23:59:59"


def _collapse_counted_items(
    container: dict[str, Any],
    item_key: str,
    keep: Callable[[dict[str, Any]], bool] | None = None,
) -> None:
    """Move counts of a value-keyed list into `other_count`, so the row mass survives its labels.

    Without `keep` every count moves and the caller empties the list. With it, only the items it
    rejects move and the rest stay in order.
    """
    items = container.get(item_key)
    if not isinstance(items, list):
        return
    moved = items
    if keep is not None:
        moved = [item for item in items if not keep(item)]
        container[item_key] = [item for item in items if keep(item)]
    container["other_count"] = container.get("other_count", 0) + sum(
        item["count"] for item in moved
    )


def _held_by_k(item: dict[str, Any]) -> bool:
    return bool(item["count"] >= MIN_RELEASE_COUNT)


def fold_ranges_under_k(
    ranges: Sequence[tuple[int, int, int | float]],
) -> list[tuple[int, int, int | float]]:
    """Merge adjacent `(start, end, count)` ranges, in order, until each holds `MIN_RELEASE_COUNT`.

    A short last range joins the one before it, so only a column with fewer than K rows in all can
    end with a short range. The total count never changes. Statistical disclosure control global
    recoding (Hundepool et al., 2012, section 3.4.2). The one fold for year buckets.
    """
    out: list[tuple[int, int, int | float]] = []
    start: int | None = None
    end = 0
    running: int | float = 0
    for first, last, count in ranges:
        start = first if start is None else start
        end, running = last, running + count
        if running >= MIN_RELEASE_COUNT:
            out.append((start, end, running))
            start, running = None, 0
    if start is not None:
        if out:
            head_start, _, head_count = out.pop()
            out.append((head_start, end, head_count + running))
        else:
            out.append((start, end, running))
    return out


def labels_read_as_sentences(labels: Collection[str]) -> bool:
    """True when the median distinct label has `FREETEXT_MIN_WORDS` or more words.

    The one free-text test: a short string column that passes it is written as free text, never
    as categorical. `labels` are the distinct cells as strings.
    """
    return bool(labels) and (
        statistics.median(len(label.split()) for label in labels) >= FREETEXT_MIN_WORDS
    )


def _kth_index(ranges: Sequence[tuple[int, int, int | float]]) -> int:
    """Index of the range that holds the `MIN_RELEASE_COUNT`-th row, counting in the order given."""
    running: int | float = 0
    for i, (_, _, count) in enumerate(ranges):
        running += count
        if running >= MIN_RELEASE_COUNT:
            return i
    raise ValueError("fewer than MIN_RELEASE_COUNT rows")


def release_ranges_at_k(
    ranges: Sequence[tuple[int, int, int | float]],
) -> list[tuple[int, int, int | float]]:
    """Bottom and top code ordered `(start, end, count)` ranges at the K-th row, then fold them.

    Ranges below the one holding the K-th lowest row count under it, and likewise above the K-th
    highest, so the outer edges never name one of the K-1 end rows. Then `fold_ranges_under_k`
    merges until each range holds K rows. Under 2K-1 rows release nothing, as numeric columns do.
    Top and bottom coding: R sdcMicro `topBotCoding`; Hundepool et al. (Wiley 2012), section 3.4.
    """
    counts = [count for _, _, count in ranges]
    if sum(counts) < MIN_RELEASE_COUNT:
        return []
    low, high = _kth_index(ranges), len(ranges) - 1 - _kth_index(ranges[::-1])
    if low > high:
        return []
    if low == high:
        return [(ranges[low][0], ranges[low][1], sum(counts))]
    first = (ranges[low][0], ranges[low][1], sum(counts[: low + 1]))
    last = (ranges[high][0], ranges[high][1], sum(counts[high:]))
    return fold_ranges_under_k([first, *ranges[low + 1 : high], last])


def fold_year_bins(stats: dict[str, Any]) -> None:
    """Replace a datetime column's one-year bins with folded v2 ranges, flagged or not.

    A column with fewer than K rows in all has nothing it may release, so it keeps no range. A
    year past the last sampled year (a 9999 sentinel) is counted under the last sampled year: a
    multi-year range cannot end later, and a bucket of its own would hold the few sentinel rows.
    The years are then coded and folded by `release_ranges_at_k`.
    """
    raw = stats.get("year_bins")
    if not raw:
        return
    by_year: Counter[int] = Counter()
    for b in raw:
        by_year[min(b["year"], MAX_SAMPLED_YEAR)] += b["count"]
    kept = release_ranges_at_k([(y, y, c) for y, c in sorted(by_year.items())])
    stats["year_bins"] = encode_datetime_buckets([DatetimeBucket(*r) for r in kept])


def _withhold(container: dict[str, Any], scope: str) -> None:
    """Aggregate then empty the value containers of `scope`, and null any key the registry lacks."""
    rules = snapshot_rules(scope)
    for key, rule in rules.items():
        if rule is Rule.EMPTY_LIST:
            _collapse_counted_items(container, key)
    applied = {k: r for k, r in rules.items() if r not in DATA_RULES}
    _apply(container, applied, snapshot_keeper(scope), denied_value=None)


def _redact_column(non_null: pd.Series, col: dict[str, Any]) -> None:
    _apply(col, {}, snapshot_keeper("column"), denied_value=None)
    kind, stats = col["kind"], col["stats"]
    if kind == "datetime":
        fold_year_bins(stats)
    if "cell_format" in col:
        col["cell_format"] = scrub_cell_format(kind, col["cell_format"])
    data_keys = {k: r for k, r in snapshot_rules(kind).items() if r in DATA_RULES}
    coarse = [k for k, r in data_keys.items() if r is Rule.COARSE_RANGE]
    if coarse:
        _coarse_range(non_null, stats, coarse)
    for key, rule in data_keys.items():
        if rule is not Rule.COARSE_RANGE and key in stats:
            stats[key] = _year_edge(rule, stats)
    _withhold(stats, kind)


def _nice_steps(width: Decimal) -> Iterator[Decimal]:
    """Heckbert steps from the largest at or below `width` upward, none below the writable floor."""
    exp = width.adjusted()
    idx = max(i for i, m in enumerate(_NICE_MANTISSAS) if Decimal(m).scaleb(exp) <= width)
    while True:
        step = Decimal(_NICE_MANTISSAS[idx]).scaleb(exp)
        if step >= _FLOOR:
            yield step
        idx += 1
        if idx == len(_NICE_MANTISSAS):
            idx, exp = 0, exp + 1


def _writable(stats: dict[str, Any], bins: int) -> bool:
    """True when the written histogram has `bins` bins on finite, strictly increasing edges."""
    edges = stats.get("bin_edges", [])
    return (
        len(edges) == bins + 1
        and len(stats.get("bin_counts", ())) == bins
        and all(math.isfinite(e) for e in edges)
        and all(x < y for x, y in pairwise(edges))
    )


def _one_bin(
    non_null: pd.Series, low: float, high: float, held: list[float]
) -> dict[str, Any] | None:
    """One bin on the one-bin grid bounds of `[low, high]` if writable and it holds `held`."""
    try:
        lower, upper = _grid_edges(low, high)
        stats = numeric_stats(non_null, bins=1, domain=(float(lower), float(upper)))
    except (OverflowError, ValueError):
        return None
    e = stats["bin_edges"]
    return stats if _writable(stats, 1) and e[0] <= min(held) and e[-1] >= max(held) else None


def _top_coded_stats(
    non_null: pd.Series,
    finite: np.ndarray[Any, np.dtype[np.float64]],
    numeric_bins: int,
    shape_values: list[float],
) -> tuple[dict[str, Any], bool]:
    """Numeric stats that depend only on the K-th smallest and largest cells (top and bottom coding).

    A released shape block (`shape_values` non-empty) gets one bin on the one-bin grid bounds.
    Otherwise the grid is the finest Heckbert step, from the requested width up, at which every
    bin holds 0 or at least K rows. The flag is True when the fixed public domain was used.
    """
    ordered = np.sort(finite)
    low, high = float(ordered[MIN_RELEASE_COUNT - 1]), float(ordered[-MIN_RELEASE_COUNT])
    if shape_values:
        one = _one_bin(non_null, low, high, shape_values)
        return (
            (one, False)
            if one
            else (numeric_stats(non_null, bins=1, domain=_FALLBACK_DOMAIN), True)
        )
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        d_low, d_high = Decimal(repr(low)), Decimal(repr(high))
        width = (d_high - d_low) / numeric_bins if d_low < d_high else _grid_step(d_low, d_high)
        for step in islice(_nice_steps(width), _MAX_STEP_TRIES):
            start = (d_low / step).to_integral_value(ROUND_FLOOR) * step
            bins = max(1, int(((d_high - start) / step).to_integral_value(ROUND_CEILING)))
            domain = (float(start), float(start + step * bins))
            if not all(math.isfinite(edge) for edge in domain):
                break
            inner = [float(start + step * i) for i in range(1, bins)]
            cum = np.searchsorted(ordered, inner, side="left")
            counts = np.diff(cum, prepend=0, append=ordered.size).tolist()
            if any(0 < c < MIN_RELEASE_COUNT for c in counts):
                continue
            try:
                stats = numeric_stats(non_null, bins=bins, domain=domain)
            except (OverflowError, ValueError):
                break
            if _writable(stats, bins) and stats["bin_counts"] == counts:
                return stats, False
    return numeric_stats(non_null, bins=1, domain=_FALLBACK_DOMAIN), True


def _k_tail_quantiles(quantiles: dict[str, float], finite_count: int) -> dict[str, float]:
    """Keep `pNN` only when K rows lie on each side, so type 7 interpolation reads no tail cell."""
    floor = 100 * MIN_RELEASE_COUNT
    return {
        key: value
        for key, value in quantiles.items()
        if int(key[1:]) * finite_count >= floor and (100 - int(key[1:])) * finite_count >= floor
    }


def _kept_year_edge(rule: Rule, stats: dict[str, Any]) -> str:
    """The first or last instant of the folded ranges, so a draw is never clamped at a bound."""
    ranges = stats["year_bins"]
    if rule is Rule.KEPT_YEAR_START:
        return f"{ranges[0]['start_year']:04d}-01-01T00:00:00"
    return f"{ranges[-1]['end_year']:04d}-12-31T23:59:59.999999"


def _is_bool(non_null: pd.Series) -> bool:
    """A bool dtype, or an object column of bools (what a CSV with blanks reads as)."""
    if pd.api.types.is_bool_dtype(non_null):
        return True
    return bool(
        non_null.dtype == object
        and len(non_null) > 0
        and non_null.map(lambda cell: isinstance(cell, (bool, np.bool_))).all()
    )


def _reads_as_free_text(non_null: pd.Series, col: dict[str, Any]) -> bool:
    """G4: a plain short string column whose labels read as sentences."""
    if col["kind"] != "categorical" or col["stats"].get("high_cardinality"):
        return False
    return not _is_bool(non_null) and labels_read_as_sentences(
        non_null.astype(str).unique().tolist()
    )


def _too_small_to_release(non_null: pd.Series, col: dict[str, Any]) -> bool:
    """G5: the floor would leave this column nothing to release."""
    kind, stats = col["kind"], col["stats"]
    if kind == "numeric":
        return 0 < finite_numeric_cells(non_null).size < 2 * MIN_RELEASE_COUNT
    if kind == "categorical":
        return not _is_bool(non_null) and not any(_held_by_k(t) for t in stats["top_values"])
    if kind == "datetime":
        return bool(stats.get("year_bins")) and not any(_held_by_k(b) for b in stats["year_bins"])
    return False


def _floor_column(non_null: pd.Series, col: dict[str, Any], *, numeric_bins: int) -> None:
    """Apply the registry's floor rules to one unflagged column."""
    kind, stats = col["kind"], col["stats"]
    by_rule: dict[Rule, list[str]] = {}
    for key, rule in snapshot_floor_rules(kind).items():
        by_rule.setdefault(rule, []).append(key)
    finite = finite_numeric_cells(non_null) if kind == "numeric" else None
    if finite is not None and finite.size > 0 and stats.get("min") is not None:
        shape_values = [v for b in _SHAPE_BLOCKS for v in (stats.get(b) or {}).get("values", ())]
        top_coded, shape_outside = _top_coded_stats(non_null, finite, numeric_bins, shape_values)
        for key in by_rule.get(Rule.TOP_CODED_RANGE, ()):
            stats[key] = top_coded[key]
        for block in _SHAPE_BLOCKS if shape_outside else ():
            stats.pop(block, None)
        for key in by_rule.get(Rule.K_TAIL_QUANTILES, ()):
            stats[key] = _k_tail_quantiles(stats[key], int(finite.size))
    if kind == "datetime" and stats.get("year_bins"):
        fold_year_bins(stats)
        for rule in (Rule.KEPT_YEAR_START, Rule.KEPT_YEAR_END):
            for key in by_rule.get(rule, ()):
                stats[key] = _kept_year_edge(rule, stats)
    if kind == "categorical" and not _is_bool(non_null):
        for key in by_rule.get(Rule.FOLD_UNDER_K, ()):
            _collapse_counted_items(stats, key, keep=_held_by_k)


def _to_freetext(df: pd.DataFrame, name: Any, col: dict[str, Any], *, numeric_bins: int) -> None:
    """Rewrite a sentence-like categorical column as free text: length statistics only."""
    only = df[[name]]
    col["kind"] = "freetext"
    col["stats"] = freetext_stats(only[name].dropna().astype(str), bins=numeric_bins)
    add_cell_format({str(name): col}, only.rename(columns=str))


def _floor_document(
    df: pd.DataFrame, doc: dict[str, Any], flagged: list[str], *, numeric_bins: int
) -> list[str]:
    """Withhold the flagged columns and floor the rest; return the names to list as redacted.

    Order matters: a column joins the withheld set before any joint is read, so a joint that
    names a G5 or free-text column is withheld, not folded.
    """
    labels = {str(c): c for c in df.columns}
    withheld = set(flagged)
    listed = list(flagged)
    for name, col in doc["columns"].items():
        non_null = df[labels[name]].dropna()
        if name in withheld:
            _redact_column(non_null, col)
            continue
        if _reads_as_free_text(non_null, col):
            _to_freetext(df, labels[name], col, numeric_bins=numeric_bins)
            withheld.add(name)
        elif _too_small_to_release(non_null, col):
            _redact_column(non_null, col)
            withheld.add(name)
            listed.append(name)
        else:
            _floor_column(non_null, col, numeric_bins=numeric_bins)
    for joint in doc["joints"]:
        if withheld & set(joint["columns"]):
            _withhold(joint, "joint")
        else:
            # A joint cell is a combination, not a vocabulary word, so bool columns get no exemption.
            for key in snapshot_floor_rules("joint"):
                _collapse_counted_items(joint, key, keep=_held_by_k)
    doc["schema_version"] = SCHEMA_VERSION_V2
    return listed


def _refuse_raised_cap_on_raw_kinds(doc: dict[str, Any]) -> None:
    """A cap above the default keeps more cells, so only plain categorical labels may fill them.

    A numeric, datetime, freetext or empty column, or a `high_cardinality` one, would put raw
    values into the extra cells of a snapshot that withholds values.
    """
    for joint in doc["joints"]:
        for name in joint["columns"]:
            col = doc["columns"][name]
            kind = col["kind"]
            if kind == "categorical" and col["stats"].get("high_cardinality"):
                kind = "high_cardinality"
            if kind != "categorical":
                raise DistributionSnapshotError(
                    code=reasons.quality.CONTINGENCY_TOP_K_KIND_UNSUPPORTED,
                    message=(
                        f"joint column {name!r} has kind {kind}; a joint cell cap above "
                        f"{DEFAULT_CONTINGENCY_TOP_K} needs plain categorical columns "
                        "unless values are included."
                    ),
                )


def snapshot_joint_warnings(doc: dict[str, Any], *, contingency_top_k: int) -> list[QualityWarning]:
    """One warning per joint whose cell cap cut combinations out of `doc`.

    `cap_dropped` is what the cap cut; `policy_dropped` is what a value policy removed from the
    kept head afterwards, so a reader never raises the cap to recover those. Joints whose values
    the writer withheld get no record. Details hold names and counts only, never a cell label.
    """
    withheld = (
        set(doc.get(REDACTED_COLUMNS_KEY, ()))
        if isinstance(doc.get(VALUE_POLICY_KEY), str) and doc[VALUE_POLICY_KEY] in REDACTED_POLICIES
        else set()
    )
    check_contingency_top_k(contingency_top_k)
    out: list[QualityWarning] = []
    for joint in doc["joints"]:
        if len(joint["cells"]) > contingency_top_k:
            raise DistributionSnapshotError(
                code=reasons.quality.CONTINGENCY_TOP_K_INVALID,
                message="contingency_top_k is smaller than the cells a joint in the document holds.",
            )
        cell_count = joint["cell_count"]
        cap_dropped = max(0, cell_count - contingency_top_k)
        if cap_dropped == 0 or withheld & set(joint["columns"]):
            continue
        cells_kept = len(joint["cells"])
        out.append(
            QualityWarning(
                code=reasons.warning.FIT_JOINT_CELLS_TRUNCATED,
                provider="snapshot",
                column=",".join(joint["columns"]),
                detail={
                    "columns": list(joint["columns"]),
                    "cell_count": cell_count,
                    "cells_kept": cells_kept,
                    "cap_dropped": cap_dropped,
                    "policy_dropped": min(contingency_top_k, cell_count) - cells_kept,
                    "other_count": joint["other_count"],
                },
            )
        )
    return out


def distribution_snapshot_document(
    df: pd.DataFrame,
    *,
    source_label: str = "<frame>",
    include_values: bool = False,
    joint_columns: Sequence[tuple[str, str]] | None = None,
    numeric_bins: int = DEFAULT_NUMERIC_BINS,
    categorical_top_k: int = DEFAULT_CATEGORICAL_TOP_K,
    contingency_top_k: int = DEFAULT_CONTINGENCY_TOP_K,
    high_cardinality_columns: Collection[str] = (),
    fanout_columns: Collection[str] = (),
    profile_row_cap: int | None = None,
) -> dict[str, Any]:
    """The snapshot JSON to write for `df`: the raw snapshot with sensitive columns' values withheld.

    Every other column is floored at `MIN_RELEASE_COUNT` rows and the document is
    `distribution-snapshot/v2`. `compute_distribution_snapshot` stays raw for in-memory callers. `include_values=True`
    keeps every value and adds a `raw` policy marker. `profile_row_cap` limits the rows the
    sensitivity profile sees, the way `decoy scan` samples.
    """
    if type(include_values) is not bool:
        raise TypeError(f"include_values must be a bool, not {type(include_values).__name__}")
    if profile_row_cap is not None:
        if type(profile_row_cap) is not int:
            raise TypeError(
                f"profile_row_cap must be an int or None, not {type(profile_row_cap).__name__}"
            )
        if profile_row_cap < 1:
            raise ValueError(f"profile_row_cap must be at least 1, not {profile_row_cap}")
    doc = compute_distribution_snapshot(
        df,
        joint_columns=joint_columns,
        numeric_bins=numeric_bins,
        categorical_top_k=categorical_top_k,
        contingency_top_k=contingency_top_k,
        high_cardinality_columns=high_cardinality_columns,
        fanout_columns=fanout_columns,
        cell_format=True,
    )
    if not include_values and contingency_top_k > DEFAULT_CONTINGENCY_TOP_K:
        _refuse_raised_cap_on_raw_kinds(doc)
    profiled = df if profile_row_cap is None else df.head(profile_row_cap)
    profile = profile_columns(profiled, source_label)
    names = value_sensitive_names(profile.to_dict()["fields"])
    if not include_values:
        names = _floor_document(df, doc, names, numeric_bins=numeric_bins)
    return stamp_value_policy(doc, names, include_values=include_values)
