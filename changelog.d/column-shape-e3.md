Breaking: `bucketize` and `top_code` on text need an F06 numeric declaration, and a decimal under `bucketize` has a 15-digit, integer-width bound.

### Changed (numeric strategies read the column shape, COLUMN-SHAPE-RULE E3, 2026-11-21)

`bucketize` and `top_code` no longer read numbers out of text on their own. A CSV, fixed-width or string column needs an F06 declaration (`logical_type: integer` with a `parse_format`; `bucketize` also takes a `decimal` of at most 15 digits). Without one, plan compile refuses it with `plan/column_shape_required`. A handler that meets a column the plan does not list as typed refuses with `runtime/column_shape_required`. Typed integer and float sources run with no declaration, as before.

A column the strategy cannot compute exactly is refused at compile with `plan/column_shape_mismatch`: a date, timestamp, boolean or other type under `bucketize` or `top_code`; any decimal under `top_code`; a decimal under `bucketize` with more than 15 digits, a negative scale or a width that is not an integer from 1 to 10^15. Today these run with wrong buckets or fail at run time. `fpe` is refused on typed float, decimal, date, timestamp and boolean columns; text and integer columns run as before. A `nested` child has no declaration of its own, so a `bucketize` child of `nested` is refused with `plan/column_shape_required`.

The F06 proof now admits `top_code` on a declared integer and `bucketize` on a declared decimal with an integer width. `bucketize` takes its width from one contract, `contracts/bucketize_width.py`, shared by the handler, the compile check and the shape rule.

Plans record a shape for every `bucketize`, `top_code` and `fpe` column, so the plan and physical plan hashes of pipelines that use them change once. All three reasons are pending: `plan/column_shape_required`, `plan/column_shape_mismatch` and `runtime/column_shape_required`.
