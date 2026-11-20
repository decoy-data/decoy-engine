### Fixed (Source metadata no longer rides on in-memory output tables, OUTPUT-METADATA-LEAK E2, 2026-11-20)

The out-of-core builders, the resident transform route and the faker degenerate pin used to copy the source file's schema metadata into the tables they return. Each now builds its schema without metadata and attaches only the sanitized pandas blob, so a returned table carries no source schema key and no pandas `attributes`. A sentry fails any new place that hands source metadata to a schema.
