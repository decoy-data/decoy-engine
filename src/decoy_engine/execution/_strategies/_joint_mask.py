"""joint_mask strategy handler (engine-v2 SP-08, 2026-06-28).

Thin V2 StrategyHandler wrapping ``decoy_engine.transforms.joint_mask``.
Core logic (HMAC-keyed row selection, gen-mode seeded sampling, config
validation) lives in the transforms module so it can be tested and reused
outside the execution layer.

joint_mask is a MULTI-COLUMN transform: it writes all ``columns`` from the
``joint_masks`` config in a single pass. The handler runs once per joint_mask
group and the ``column`` parameter is the first (alphabetically sorted) column
in the group, used only for adapter-level dispatch tracking.

Config keys accepted via ``plan.provider_config``:
  columns     list[str]  Output columns to write (must match reference table).
  reference   str        Reference table name (e.g. ``us_zip5_city_state``).
  key_by      str        Source column for HMAC-keyed selection (mask mode).
  mode        str        ``"mask"`` (default) or ``"gen"``.
"""

from __future__ import annotations

import pandas as pd

from decoy_engine import fileaccess, reasons
from decoy_engine.execution._adapter import StrategyContext, StrategyOption, provider_config_to_dict
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution.work_order.rows import snapshot_rows
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.transforms.joint_mask import JointMaskConfig, apply_joint_mask


class JointMaskHandler:
    """Reference-tuple masking: replaces coupled columns with a consistent row.

    Delegates to ``decoy_engine.transforms.joint_mask.apply_joint_mask``.
    Config validation runs at execution time, pre-mutation, fail-closed: an invalid
    ``provider_config`` raises ``PlanCompileError`` (via ``JointMaskConfig.from_dict``)
    before any row is processed.
    """

    name: str = "joint_mask"
    namespace_required: bool = False
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = ()
    offer_in_wizard: bool = False

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        cfg = provider_config_to_dict(plan.provider_config)
        mode = str(cfg.get("mode", "mask"))
        with fileaccess.at_position(
            f"tables.{ctx.current_table}.columns.{ctx.nested_outer_column or column}"
        ):
            joint_cfg = JointMaskConfig.from_dict(cfg)
        # Cross-column V1: key_by is a SOURCE key (its docstring: "key_by: Source
        # column"; the FK-key identity analogy), so read its immutable pre-mask
        # value from ctx.group_anchor_snapshots -- the date_shift group-anchor
        # precedent -- never the live (possibly masked) frame. The adapters
        # snapshot every joint_mask key_by (`source_anchor_columns`).
        key_series = None
        if mode == "mask":
            key_series = snapshot_rows(
                ctx,
                ctx.current_table,
                joint_cfg.key_by,
                len(df),
                strategy="joint_mask",
                misaligned=reasons.runtime.JOINT_MASK_KEY_BY_SNAPSHOT_MISALIGNED,
            )
            if key_series is None:
                # Fail closed whenever the required pre-mask snapshot is absent, regardless of
                # whether key_by happens to be a live-frame column. Without the snapshot the only
                # fallback is a masked live read or the synthetic null key, both of which silently
                # select the wrong reference tuple.
                raise StrategyError(
                    code=reasons.runtime.JOINT_MASK_KEY_BY_SNAPSHOT_MISSING,
                    strategy="joint_mask",
                    message=(
                        f"joint_mask on {','.join(joint_cfg.columns)!r} reads key_by "
                        f"{joint_cfg.key_by!r} but no pre-mask source snapshot was provided; "
                        "the run cannot select the reference tuple off the source key "
                        "deterministically. Check that key_by names a source column the "
                        "adapter snapshots pre-mask."
                    ),
                )
        updated_df = apply_joint_mask(
            df,
            joint_cfg,
            mode=mode,
            job_seed=ctx.mask_key,
            namespace=plan.namespace,
            key_series=key_series,
            table=ctx.current_table,
        )
        return updated_df, []
