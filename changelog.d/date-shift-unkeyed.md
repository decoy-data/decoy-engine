### Changed (unkeyed date_shift is refused and the MD5 path is gone, row 24zb, 2026-11-16)

An unkeyed `date_shift` already stopped with `keyed_strategy_requires_secret` before any source read. That behavior is now pinned on every run route, and the dead code that held the reversible MD5 offset is deleted: `decoy_engine.transforms.date_shift.DateShiftStrategy` and its private helpers `_parse_date`, `_shift_for_value_md5` and `_shift_for_value_keyed` are removed. None of them was exported from `decoy_engine` or `decoy_engine.transforms`. `_detect_format` and `_COMMON_FORMATS` stay. Keyed `date_shift` output does not change.

`keyed_columns_for_config` and `secret_requirements_for_config` now classify the mask `columns` of a raw table dict that also holds `generate_columns`. Before, they skipped such a dict. A validated config cannot have both kinds, so schema-valid input gives the same result.

A source-hygiene sentry now fails on any MD5 call or `noqa: S324` waiver in `src/decoy_engine`, and a keyed-strategy sentry fails when a handler that reads `mask_key` is classified unkeyed or a `StrategyContext` is built without `require_mask_key`. The `mask.date_shift` draw-site entry now names the live handler (metadata only; no output changes).
