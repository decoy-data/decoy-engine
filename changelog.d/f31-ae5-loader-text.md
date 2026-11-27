### Fixed (config loader refusal text, F31 AE5, 2026-11-25)

Config loader errors now name the field and the expected type, not the supplied value or the file path.

- Every refusal in the name-hint, plan snapshot, joint-mask, code-set, statistical spec, reference table, model-pack and DP provenance loaders is built by one function, `config_refusal`. The text and the `path` come from a position, a closed problem and a closed expected type.
- A YAML value that fails to convert (`!!int text`), a list given where a name belongs, a URL given as a corpus name, a time zone in a Parquet column and a JSON syntax error no longer put their text in the error. A parse error keeps only its line and column.
- The name-hint loader no longer prints the directory path under the CLI policy. It names `pre_scan.name_hints/<file>`.
- A refusal from these loaders has no `__cause__` or `__context__`.
- `verify_corpus` returns `ok=False` for a corpus whose cells cannot be converted. `load_corpus` raises `CODE_SET_CORPUS_READ_ERROR`.
- The joint-mask missing `reference` path now carries the table and column bound by `at_position`, like its two sibling refusals.
- New sentry `tests/sentry/defects/test_config_refusal_text.py` fails on a runtime value in a loader refusal. The remaining sites outside the nine modules sit in a shrink-only baseline, migrated in AE5b.
- A file-system failure on a loader's first probe or read (an unreadable parent directory) is a value-free refusal too, for corpora, name hints and model packs.
- `verify_corpus` shows a report path with any credential removed (the config position under a strict policy).
- A name-hint manifest member given as a URL (`https://host/path/token`, or `//host/path`) shows as `<file>`. Its last path segment is no longer shown.
- A statistical column's `source_column` defaults to the column name only when the key is absent. An explicit `[]`, `{}`, `false` or `0` is refused as a wrong type with `statistical_column_not_in_snapshot`; before, it silently selected the column of the same name.
- One function, `decoy_engine.plan.refusal_error`, turns a built refusal into a `PlanCompileError`. The plan checks and the transforms use it. The sentry fails on a second construction that maps a refusal's `detail` and `key`.
