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

A column that reads a composite's output (`derived` over `email`, written by a
`composite_name_email` node keyed on `first_name`) now runs after that composite and reads its
value. Before, it could run first and read the source value. The `when:` snapshots and the carry's
untouched set read one write declaration; the ordering reads what dispatch really writes from it.
A composite that is an FK child writes only its own column, so it adds no edge for the rest of its
bundle. A column that a `derived` (or other creating) entry adds and a composite also writes is
created first and then takes the composite's value.

Fixed: a `when:` predicate or a derived expression that read a bundle's output, a creator's target, or a column rewritten by a joint mask now sees the value the plan's ordering defines instead of a stale source value. A plan whose columns used to fail with `cyclic_work_ordering` because of a creator, a bundle and a foreign key sharing columns now runs, and a real value cycle still raises that code.

Added: the runtime reason code `runtime/when_source_snapshot_missing` (value-free) is raised when a route evaluates a `when:` without the pre-mask snapshot of a column it reads.

Changed: a gated joint mask feeding deterministic Faker on a rewritten nullable-int column now fails closed (`float_canonicalization_unsupported`) until S2b. Before, Faker keyed from the integers the source held before the rewrite.
