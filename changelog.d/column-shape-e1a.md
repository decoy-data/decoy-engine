Breaking: a stored plan from an older engine is refused until you compile it again, and every profile hash changes once.

### Changed (column shape in the profile and the plan, COLUMN-SHAPE-RULE E1a, 2026-11-21)

Each profile column now carries a `shape` (`text`, `date`, `timestamp_tz`, `timestamp_naive`, `integer`, `float`, `decimal`, `decimal_wide`, `boolean`, `other` or `unknown`), read from the source format and the Arrow schema. A csv or fixed-width column is always `text`. The shape is part of `profile_hash`, so profile hashes and the physical `plan_hash` change once. A profile saved before this loads with `shape: unknown`. A shape token the engine does not know is refused when the profile is loaded.

`PLAN_VERSION` is now 5 and a plan records `column_shapes` for each column under a strategy that reads the value (today `date_shift`). A stored plan is checked for its version before any other field. A version-4 plan is refused with `plan/plan_recompile_required`; compile it again from its config. A missing, non-integer or newer version is refused with `plan/plan_version_unsupported`, and a stored shape the engine does not know with `plan/stored_shape_unknown`. All three reasons are pending. `compile_plan` gains `source_schemas` and `capture_physical_plan_inputs` gains `source_loader_schemas`, so a source-loader table and a zero-chunk typed input get their shapes too.

No masking output changes: `date_shift` still needs `date_format` on every shape. The shape rule for typed sources lands in later slices.
