### Added (when: reference prefixes and quoted names, WHEN-READS-SOURCE S1, 2026-11-22)

A `when:` column can now be written `source.<name>`, which means the same as the bare name
(the original value). A name with a dot or another character outside letters, digits and `_`
is written in backticks, for example `` `a.b` == 'x' ``. `masked.<name>` is reserved: it is
refused with the new error type `when_masked_reference_unsupported`, because V1 reads original
values only. Every predicate that worked before selects the same rows.

The new reason codes are `config/when_masked_reference_unsupported`,
`plan/when_masked_reference_unsupported` and `runtime/when_masked_reference_unsupported`.
