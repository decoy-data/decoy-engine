Breaking: a `when:` predicate that reads a column named `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith` or `endswith` is refused with `when_outside_closed_grammar`; rename the column.

### Changed (`when:` reserves nine more names, FREEZE-S5, 2026-11-20)

`RESERVED_NAMES` gains `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith` and `endswith`, so the grammar can grow these words later without another breaking change. Matching is exact and case-sensitive: a column named `NULL` or `Between` is still a column. An exact snapshot test pins the set, and a sentry fails when a keyword is added to `when_grammar.lark` and not reserved.
