### Added (inherit generate type, GEN-INHERIT E1, 2026-11-14)

A generated child column can now copy a column of the parent row its foreign key points at, so a
denormalized attribute agrees with its parent on every row.

- New generate type `inherit` with the required options `via` (an earlier `reference` column of
  the table) and `column` (a column of that reference's parent table). Each row gets the parent
  row's value; a null foreign key or a null parent value gives a null, and nothing is drawn.
  `null_probability` applies after the copy. A column of the child, or of any other table, with
  the same name as `column` is never read. Copies chain across tables, and a conditional
  `categorical` can condition on an inherited column.
- The column has the parent column's Arrow type, nulls and declared `output_type` included, even
  when every copied value is null. `inherit` takes no `output_type` and no `unique`
  (`config/generate_unique_unsupported`).
- Refusals reuse the existing codes: a `via` that is not a `reference`, or whose parent key is not
  a `sequence` column with no `null_probability`, is `config/generate_parent_lookup_key_not_unique`;
  a `via` referencing its own table is `config/generate_parent_lookup_self_reference`; a `via`
  declared later or a `column` missing from the parent table is
  `plan/generate_column_forward_reference`; a `column` naming a per-parent aggregate is
  `config/generate_aggregate_read_before_fill`; a foreign key value with no parent row is
  `runtime/parent_lookup_key_missing`. Pinned compile refuses the type with
  `plan/pinned_relational_option_unsupported` and pinned execute with
  `runtime/pinned_relational_option_unsupported`. Streaming admission declines it, so the run
  stays on the whole-table route. No reason code is added.
- Numeric typing judges the copy with the column it copies: a child `formula` reading the copy as
  text keeps the parent column text in both tables. A per-parent aggregate over an inherited
  column is judged by the column it copies.
- The support bundle's `StrategyKind` gains `inherit`, so a bundle can name the type.
