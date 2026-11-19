# Output file metadata

Status: current

A masked Parquet file must not carry text from the source file that masking never looked at. A
Parquet footer holds key/value metadata at two levels: on the schema, and on each field. A source
file can put a comment, an owner name or an email address in either place. The 1.0 default is to
remove all of it and keep one allow-listed key.

## What an output file carries

- Schema level: one key at most, `b"pandas"`, in a rebuilt form. Every other key is absent,
  including `PANDAS_ATTRS`, which `DataFrame.to_parquet` writes for `df.attrs`.
- Field level: no metadata on any field at any nesting depth. This includes `PARQUET:field_id`
  and the keys of an unregistered Arrow extension.
- Extension types: a column whose type is an extension is written as its storage type, because
  the type name, vendor name, dimension names or serialized parameters can hold source text.
  The exceptions are types with no free-text parameter: `arrow.uuid`, `arrow.bool8`,
  `arrow.json`, and the pandas period and interval types (kept only when their one short
  parameter has the known shape and their storage holds no metadata). This covers
  `arrow.opaque`, fixed-shape tensors and any type a Python program registered.
- `ARROW:schema`: the writer's serialization of the cleaned schema. Pyarrow stores the schema a
  second time in this footer value, so a field comment that a plain byte search cannot find is
  still removed here.

Masked values, column names, Arrow types, nullability and row-group layout do not change. An
output from a source with no custom metadata is byte-identical to the output before this rule.

## The rebuilt pandas blob

Pandas readers use the `b"pandas"` blob to restore dtypes such as nullable integers and
categoricals. The engine keeps a blob so those dtypes survive, but it never copies one. Each
member comes from the output schema, the running pyarrow and pandas versions, or the descriptor
table in `src/decoy_engine/_pandas_meta/`:

| Member | Written value |
|---|---|
| `columns` | one entry per output field with a known Arrow type. The pandas and numpy types are the pair the source names if that pair is listed for the output Arrow type, otherwise the default pair. The column metadata (time zone, decimal precision and scale, categorical order) comes from the Arrow type |
| `index_columns` | names that equal an output field name and have a `columns` entry, once each. A range-index object is dropped, because its name is user text and its stop is a source row count |
| `column_indexes` | pyarrow's default entry when an index column is kept, otherwise empty |
| `attributes` | always `{}`. The source's `attrs` are never copied |
| `creator`, `pandas_version` | the running pyarrow and pandas versions |

A blob that is not a JSON object is dropped and the write goes on. The sanitizer never raises on
metadata content, and no log line names a key or a value.

## Where the rule runs

`safe_output.output_schema` is the one place that decides output metadata. The output writers of
`fileaccess/adapters/arrow.py` (`write_output_table`, `output_parquet_writer`) call it, and the
engine's published-file sites write through them: the staged sink, the streamed writer and
`publish_tables`. The writer is built from the cleaned schema before the file is created, so
batches that still carry metadata cannot add to the footer.

Files Decoy never publishes are outside the rule: scratch spill, the isolated child's source
handoff, declared-cast staging, the out-of-core key stage, vault segments and the Postgres
snapshot. Some of them read their own metadata on purpose. The sentry lists each by name with a
reason in `tests/sentry/baselines/parquet-intermediate-writers.json`, and the list can only
shrink. The subset output is published and is written by Polars, which reads no Arrow key/value
metadata; a canary test guards it.

In-memory tables that a run returns to a Python caller are not covered. The caller already holds
the source.

## Tests

`tests/security/test_output_metadata_canary.py` plants a canary in every carrier and runs every
route. The helper decodes `ARROW:schema`, so it sees field metadata that a raw byte search misses.
`tests/sentry/defects/test_output_metadata_choke_point.py` fails on a Parquet write outside the
output writers and the baseline.

## Later

F38 (an opt-in preserve or redact policy) is a 1.x feature. It can add a keyword-only `policy`
argument to `output_schema` and `output_table` with this strip behavior as the default, and
nothing else here changes.
