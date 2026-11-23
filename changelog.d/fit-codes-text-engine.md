Breaking: an engine older than this release refuses a `distribution-snapshot/v1` or `/v2` snapshot that holds `cell_format.char_class`, and refuses a pinned plan whose stored `cell_format` holds it, with `statistical_cell_format_invalid`; upgrade the engine or refit with the old one

### Added (digit-only text columns generate digit strings, FIT-CODES-TEXT, 2026-11-22)

A fitted `freetext` column whose non-blank cells are all ASCII digits (`0` to `9`) now records
`cell_format.char_class: "digits"`, in both `distribution-snapshot/v1` and `/v2`. The sampler
draws digit strings at the fitted lengths for such a column, leading zeros included, in place of
lorem words. The member is one fixed token and holds no source value, so the redacted fit writes
it for flagged columns too. A snapshot without the member generates the same bytes as before.
Unicode digits (`٣`, `５`, `²`) do not count.
