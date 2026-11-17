### Changed (Postgres source prep, CLI-DB-SRC E1, 2026-11-17)

The Postgres snapshot primitive now shares its session helpers with the coming Postgres source and target. The connection, extension load and identifier rule moved to `connectors/_postgres_session.py`. `connectors/postgres_catalog.py` adds `relation_columns`, which reads a relation's columns before any row, and a shape guard: a `RelationSelection` with `whole_relation=True` is refused with `relation_shape_changed` if the relation's columns changed inside the snapshot transaction. `validate_identifier` and `POSTGRES_SOURCE_USAGE_CODES` are new names in `postgres_snapshot`.

Snapshot errors no longer keep DuckDB's text as `__context__`, so a connection string cannot reach a traceback. A DuckDB interrupt that is not the deadline (Ctrl-C) is raised as `KeyboardInterrupt` and no longer reported as `export_failed`. On DuckDB 2.x the extension directory is set through `extension_directories`.

New connector reason codes `connector/relation_shape_changed` and `connector/column_name_unsupported` are unreleased. Ten connector codes now have outcome `configuration` and retry class `configuration_repair`: `ambiguous_name`, `column_name_unsupported`, `column_not_found`, `duplicate_relation`, `extension_unavailable`, `extension_untrusted_location`, `relation_not_found`, `relation_shape_changed`, `unsupported_column_type` and `value_not_representable`. The registry version and manifests change at the release.

A merge-required `pg-gate` CI job runs every `pg_integration` test against a Postgres service container and fails on any skip.
