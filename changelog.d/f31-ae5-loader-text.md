### Fixed (config loader refusal text, F31 AE5, 2026-11-25)

Config loader errors now name the field and the expected type, not the supplied value or the file path.

- Every refusal in the name-hint, plan snapshot, joint-mask, code-set, statistical spec, reference table, model-pack and DP provenance loaders is built by one function, `config_refusal`. The text and the `path` come from a position, a closed problem and a closed expected type.
- A YAML value that fails to convert (`!!int text`), a list given where a name belongs, a URL given as a corpus name, a time zone in a Parquet column and a JSON syntax error no longer put their text in the error. A parse error keeps only its line and column.
- The name-hint loader no longer prints the directory path under the CLI policy. It names `pre_scan.name_hints/<file>`.
- A refusal from these loaders has no `__cause__` or `__context__`.
- `verify_corpus` returns `ok=False` for a corpus whose cells cannot be converted. `load_corpus` raises `CODE_SET_CORPUS_READ_ERROR`.
- The joint-mask missing `reference` path now carries the table and column bound by `at_position`, like its two sibling refusals.
- New sentry `tests/sentry/defects/test_config_refusal_text.py` fails on a runtime value in a loader refusal. The remaining sites outside the nine modules sit in a shrink-only baseline, migrated in AE5b.
