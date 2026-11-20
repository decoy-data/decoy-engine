Breaking: a `when:` predicate over an integer column now selects blank rows with one rule on every route and column class (`!=`, `not in` and `not (...)` select them), so FK keys, declared integers, `date_shift` anchors, `top_code` columns and `group_key` siblings mask more rows than before.

### Changed (`when:` on integer columns is exact and has one blank-row rule, FREEZE-O1, 2026-11-18)

Integer comparisons in `when:` are exact beyond 2**53. A value or an integer literal outside the range a float64 holds exactly, and any comparison of an integer column with a float literal, is compared as Python integers. Before, a plain integer column with a blank was widened to float64 and `id == 9007199254740993` also selected `9007199254740992`.

A blank integer cell is `NaN` for the predicate on the whole-frame, sequential, chunked, native and unified routes. `!=`, `not in` and a `not` around a comparison that is false for the blank select it; `==`, `in` and the ordering tests do not. FK keys, declared integers, `date_shift` anchors, `top_code` columns and `group_key` siblings used the pandas `NA` rule, which selected no blank row for `!=`, so they now mask more rows.

`lossless_int_columns` in `execution/_fk_keys.py` is the one construction of the columns every ingestion site reads as exact integers. It adds the columns a `when:` reads. A null-bearing integer column that a `when:` reads and that passes through is written as `int64` instead of `double` on every route (CSV text `5`, not `5.0`). A job with such a column can now take the unified full-frame route.
