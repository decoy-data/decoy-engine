Breaking: a `when:` condition now reads the original value of every column it names, as documented. Before, on the pandas routes, it read a value that a column earlier in work order had already masked, so the rows it selected depended on column names. The native lanes no longer decline a `when:` that names a column masked earlier; the reason codes `route.when_reads_masked_column` and `runtime.when_predicate_reads_masked_column` are deprecated and no longer produced.

### Fixed (when: reads the original value, WHEN-READS-SOURCE S2, 2026-11-23)

A `when:` picks rows by the row's original values, from any column. "Mask `email` only on rows
where the original `country` = 'US'" now holds when the job also masks `country`. Before, a job
that hashed `status` and gated `zz_email` on `status == 'active'` compared the hash to `'active'`,
selected no rows and wrote every email unmasked; renaming `zz_email` to `aa_email` changed the
result. Output is now independent of column order and names. A config whose `when:` named a column
masked earlier masks different rows than before.

The chunked native route and the unified slice already read the original values, and they now take
these tables instead of declining them. Their evidence no longer lists
`when_predicate_reads_masked_column`, and `executed_backend` is the native backend.
Out-of-core still refuses `when:`.

A route that forgets the pre-mask snapshot of a `when:` column fails with the new runtime error
`when_source_snapshot_missing`. No supported route does.

On the pandas routes, a `when:` on a masked column must name columns the table holds before masking
starts (source columns and `derive` targets). For a config that passes the existing declaration
and stored-index checks (which can refuse first with their own codes), a name that only a masking
column creates fails with `when_expression_error` before that table is masked. Main raised the
same error when the creating column ran after the gated one, and read the created values when it
ran before. On main, a read missing from the table could resolve to a stored pandas index when the
engine's internal alias for that read (`_w0`, `_w1`, ...) matched the index name. It now fails
with `when_expression_error`. If the gate should read index values, materialize them as a data
column and use that column's name in `when:`. A `when:` on an FK child column or a composite
bundle is not evaluated, as on main, and those jobs run as before. The refusal follows each
route's existing failure contract: a transactional sink publishes nothing, and a plain callable
sink or a chunk stream may already hold earlier tables or chunks.

Work order is unchanged: the order of masking nodes is the order it was before, a plan raises
`cyclic_work_ordering` exactly when it did, and nodes write into the live frame one at a time.

Fixed: a `when:` gate, a gated `joint_mask` and a `date_shift` with `group_by` now pick rows and
their pre-mask source values by position. A source that stores a repeated, unsorted or string
index (a Parquet file written from a pandas frame) no longer gives a gated joint mask both source
keys, and the stored index comes back unchanged in the output.

Added: the runtime reason code `runtime/when_source_snapshot_missing` (value-free) is raised when a route evaluates a `when:` without the pre-mask snapshot of a column it reads.

Changed: a gated joint mask feeding deterministic Faker on a rewritten nullable-int column now fails closed (`float_canonicalization_unsupported`) until S2b. Before, Faker keyed from the integers the source held before the rewrite.
