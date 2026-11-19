"""QualityWarning event shape.

S5 emits events; S10 consumes them into the manifest's `quality_summary`.
Per cross-sprint contracts R14: S5 owns the event shape; S10 owns the
manifest field. No double-definition.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from decoy_engine._value_free import is_plain_name

DetailValue: TypeAlias = str | int | float | bool | None
# What a producer may pass: a scalar, or a list of names the constructor joins with ", ".
DetailInput: TypeAlias = DetailValue | list[str] | tuple[str, ...]


@dataclass(frozen=True)
class QualityWarning:
    """One non-fatal quality observation surfaced by the pool sampler/builder.

    Codes owned by S5:

    - `low_distinct_ratio`: sampled output distinct ratio below target.
    - `pool_scaled_up`: pool size grew to accommodate source distinct count.
    - `pool_scale_up_exceeded_budget`: scale-up would exceed cache budget;
      converted to fall_back instead.
    - `pool_fallback`: pool path bypassed; per-row generation used.
    - `pool_dominates_cache`: single pool occupies >25% of cache budget.

    Codes added by later sprints (same shape, same emission channel; the type
    stays S5-owned per R14):

    - `mimesis_locale_fallback` (S7): an adopted Mimesis provider was asked for
      a locale outside Mimesis coverage; the adapter fell back to Faker for
      that locale + provider. `detail` carries `requested_locale` +
      `mimesis_locales`.
    - `cardinality_collisions` (post-validation cardinality scan): a deterministic `faker` column
      (not `unique`, no `when:`) merged distinct source values into shared outputs. `detail`
      carries `table`, `source_distinct`, `output_distinct`, `distinct_lost` and `pool_size`
      (the effective size, `DEFAULT_POOL_SIZE` when none is declared); names and counts only.
    - `generation_fidelity_below_threshold` (statistical fidelity gate): a generated table's
      overall score, or one comparable column's score, is below `fidelity_warn_threshold`.
      `detail` carries `table`, `snapshot_index`, `overall_score`, `threshold`, `trigger`,
      `worst_columns` and `below_columns` (each `name=score` pairs joined with ", "); scores and names only, never a cell value.
    - `generation_condition_parent_unseen` (conditional statistical column): some rows had a
      `condition_on` parent with no fitted combination and drew from the column's overall counts.
      `detail` carries `table`, `column`, `condition_on`, `rows`, `rows_null_parent`,
      `rows_total`, `parent_values` (a capped count of distinct parent keys) and `parent_values_capped`; names and counts only.
    """

    code: str
    provider: str
    column: str | None = None
    detail: Mapping[str, DetailInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Make the warning evidence-ready, the one place every producer's warning passes.

        `EvidencePayload` refuses a code, provider or column that is not a plain name (see
        `is_plain_name`) and any non-scalar `detail` value. So `provider` names the source (a
        provider, a strategy or a route) and is never empty, and `detail` ends up scalar-only: a list or tuple of names becomes one string joined with
        ", " here and nowhere else, and anything else non-scalar is refused (a per-row map must
        become counts at the producer). Messages name the key, never a value.
        """
        if not is_plain_name(self.code):
            raise ValueError("QualityWarning: code must be a plain name")
        if not is_plain_name(self.provider):
            raise ValueError(f"QualityWarning {self.code!r}: provider must be a plain name")
        if self.column is not None and not is_plain_name(self.column):
            raise ValueError(f"QualityWarning {self.code!r}: column must be None or a plain name")
        scalar: dict[str, DetailValue] = {}
        for key, value in self.detail.items():
            if not isinstance(key, str):
                raise TypeError(f"QualityWarning {self.code!r}: detail keys must be strings")
            if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
                scalar[key] = ", ".join(value)
            elif value is None or isinstance(value, (str, int, float, bool)):
                scalar[key] = value
            else:
                raise TypeError(
                    f"QualityWarning {self.code!r}: detail[{key!r}] must be a str, int, float, "
                    "bool, None or a list of strings"
                )
        object.__setattr__(self, "detail", scalar)


def emit_generation_warning(
    record: QualityWarning,
    log: logging.Logger,
    summary: str,
    on_warning: Callable[[QualityWarning], None] | None,
) -> None:
    """The one emitter for value-free generation warnings: log the summary, then hand the record on.

    `summary` carries names and counts only; the callback sees the structured record.
    """
    log.warning("%s", summary)
    if on_warning is not None:
        on_warning(record)
