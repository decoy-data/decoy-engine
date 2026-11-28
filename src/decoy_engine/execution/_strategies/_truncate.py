"""truncate strategy (engine-v2 S9): keep the first (or last) N characters.

Logic carried from V1 `transforms/truncate.py` (config keys `length` >= 1,
`from_end` bool; nulls preserved). No backend.

MG-1 S3 extension (2026-06-01): adds `mask_char` + `keep` so the
V1 "keep last 4, replace rest with *" use case works. When both new
fields are unset, the byte-identical V1 behavior is preserved.

Sprint 13 / coercion-13 S3 (2026-07-03, finding 0.4): the invalid-config
branches used to `return df, []` (silent passthrough of the source
value -- a masking strategy leaking source PII on a bad config). They now
raise `StrategyError`. `check_truncate_config` (plan/_checks_truncate.py)
rejects the same three shapes at compile time, so this is a defense-in-
depth backstop: unreachable through a compiled plan, but a masking
primitive must never silently emit source values even if some future
caller invokes the handler directly with an unvalidated config. Follows
the `hash_requires_namespace` pattern in `_hash.py`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from decoy_engine import reasons
from decoy_engine._config_text import Problem, config_position, config_refusal
from decoy_engine.contracts.label_text import is_mask_char
from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    option,
    pandas_column_to_kernel_input,
    provider_config_to_dict,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.kernel import truncate_array
from decoy_engine.plan._types import ColumnSeed

_KEEP_SIDES = ("head", "tail")


def truncate_params(cfg: dict[str, Any]) -> tuple[int, str, str | None]:
    """Resolve the legacy from_end setting before validating the kernel arguments."""
    keep = cfg.get("keep")
    if keep is None:
        keep = "tail" if cfg.get("from_end") else "head"
    return validated_truncate_params(cfg.get("length"), keep, cfg.get("mask_char"))


def validated_truncate_params(
    length: Any, keep: Any, mask_char: Any
) -> tuple[int, str, str | None]:
    """Validate all three runtime routes before a truncate kernel sees the source."""
    if not isinstance(length, int) or length < 1:
        refusal = config_refusal(
            config_position("provider_config", "length"),
            Problem.NOT_ALLOWED,
            got=length,
            hint="length must be an integer >= 1.",
        )
        raise StrategyError(
            code=reasons.runtime.TRUNCATE_LENGTH_INVALID, strategy="truncate", message=refusal.text
        )
    if keep not in _KEEP_SIDES:
        keep_refusal = config_refusal(
            config_position("provider_config", "keep"),
            Problem.NOT_ALLOWED,
            got=keep,
            hint="keep must be 'head' or 'tail'.",
        )
        raise StrategyError(
            code=reasons.runtime.TRUNCATE_KEEP_INVALID,
            strategy="truncate",
            message=keep_refusal.text,
        )
    if mask_char is not None and not is_mask_char(mask_char):
        mask_refusal = config_refusal(
            config_position("provider_config", "mask_char"),
            Problem.NOT_ALLOWED,
            got=mask_char,
            hint="mask_char must be a single character that encodes as UTF-8.",
        )
        raise StrategyError(
            code=reasons.runtime.TRUNCATE_MASK_CHAR_INVALID,
            strategy="truncate",
            message=mask_refusal.text,
        )
    return length, keep, mask_char


class TruncateHandler:
    """Keep the first `length` chars of each value (or last, if from_end).

    MG-1 S3 (2026-06-01):
      - `keep`: 'head' (default) or 'tail'. Replaces the
        from_end boolean which survives as a deprecation-warned
        synonym for keep='tail'.
      - `mask_char`: when set, the truncated portion is replaced
        with mask_char repeated to fill the dropped span instead
        of being dropped entirely. Output length matches input
        length. When unset, the V1 byte-identical drop behavior
        is preserved.
    """

    name: str = "truncate"
    namespace_required: bool = False
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = (
        option("length", "int", 3, required=True),
        option("keep", "str", "tail", choices=_KEEP_SIDES),
        option("mask_char", "str", "*"),
    )
    offer_in_wizard: bool = True

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        cfg = provider_config_to_dict(plan.provider_config)
        length, keep, mask_char = truncate_params(cfg)
        # SC1 port (2026-07-07): computation now runs through the shared
        # Arrow kernel (`decoy_engine.kernel.truncate_array`) so this handler
        # and the out-of-core route apply byte-identical truncate logic from
        # one source of truth. Byte-identical to the prior inline pandas
        # implementation for every (length, keep, mask_char) combination.
        masked = truncate_array(
            pandas_column_to_kernel_input(df[column]),
            length=length,
            keep=keep,
            mask_char=mask_char,
        )
        df[column] = masked.to_pylist()
        return df, []
