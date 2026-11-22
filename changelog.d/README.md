# Changelog fragments

A PR that changes behavior adds one file here, `changelog.d/<slice-slug>.md`, instead of editing
`CHANGELOG.md`. `CHANGELOG.md` keeps an empty `## [Unreleased]` heading; release prep compiles
the fragments into the dated section with `scripts/release/stamp_release.py`, then deletes them.

A fragment holds exactly the block that used to go under `[Unreleased]`:

```
Breaking: one line, only when a consumer must change something

### Added (short title, SLICE-ID, 2026-11-10)

Body text.
```

- The `Breaking:` first line is optional. It becomes a bullet in the release's
  "Breaking for consumers" list.
- A `Breaking:` line names each broken public name in backticks and, for a parameter change, the
  parameter too (`compile_plan` requires `sources`). The signature sentry
  (`tests/sentry/release/test_public_signatures.py`) reads one line at a time, so one line carries
  both names. A false break (for example a default constant renamed with the same value) gets a
  reviewed `SIGNATURE_EXEMPTIONS` row in `tests/sentry/release/_signatures.py`, keyed to the current
  base tag, instead of a misleading Breaking line. Remove the row in the first PR after the next tag.
- One `### <Type> (<title>, <slice>, <date>)` heading, with `<Type>` one of Added, Changed,
  Fixed, Deprecated, Removed or Security. Use `####` for any sub-headings.
- The file name is lowercase letters, digits and hyphens, ending in `.md`.
- `scripts/dev/check_fragment.py` (the `changelog-fragment` PR workflow) fails a PR that changes
  `src/` without a fragment, unless every commit is a `test`, `docs`, `ci`, `chore` or `refactor`.
  The grammar lives in `stamp_release.parse_fragment`; the checker and the compiler share it.
- Tests that read unreleased wording go through `tests/_changelog.unreleased_text()`.
