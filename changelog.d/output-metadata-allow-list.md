Breaking: published Parquet files no longer carry the source file's custom metadata, field metadata or pandas `attrs`, and extension-type columns (opaque, tensors, custom types) are written as their storage type

### Security (output Parquet metadata allow-list, OUTPUT-METADATA-LEAK E1, 2026-11-19)

Out-of-core output files written from pandas-made sources change bytes: the source's pandas metadata is replaced by a cleaned copy, and custom keys and field metadata are removed.

Before, the out-of-core route copied the source schema's key/value metadata into the masked file. A custom key such as `table_comment`, the field metadata of a column and the pandas blob, including the frame's `attrs`, reached the output footer. Now every Parquet file the engine publishes carries only an allow-list. In 1.0 the list holds one schema key, `b"pandas"`, rebuilt from the output schema, the running pyarrow and pandas versions and one descriptor table. No field has metadata at any nesting depth. An extension-type column other than `arrow.uuid`, `arrow.bool8`, `arrow.json` and the pandas period and interval types is written as its storage type, because its type name or parameters can hold source text. Masked values, column names, other Arrow types, nullability and row groups do not change, and an output from a source with no custom metadata is byte-identical to before.

`output_schema` and `output_table` are new public names. The Arrow adapter gains `write_output_table` and `output_parquet_writer`, and the engine sinks and `publish_tables` write through them. A new sentry fails on a Parquet write that skips them. The in-memory tables a run returns are unchanged. See `docs/security/output-metadata.md`.
