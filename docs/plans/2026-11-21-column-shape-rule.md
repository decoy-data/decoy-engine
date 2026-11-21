Status: plan (revision 5, 2026-11-21; Dennis round 1, Codex rounds 1 to 3 GO-WITH-FIXES remediated. Round 3: one bucketize width contract that covers presets, `Plan.column_shapes` in the physical plan hash, strict stored shape tokens. Round 2: stored version-4 plans need a recompile, decimal admission bounds scale, magnitude and width, E0b masks out-of-range dates on every route, the empty-string rule moved to V2, the observed shape is a typed input, the zero-chunk schema is routed through the oracle preflight, and the E0 reason choke point is required before merge)

# COLUMN-SHAPE-RULE: declare a column's type and format only where the engine would otherwise guess

Owner: Cam. Author: Opus (plan author). Date: 2026-11-21. Roadmap row: COLUMN-SHAPE-RULE, to be added to the 1.0 table of `docs/roadmap/groups/mask.md` by slice C0.

Anchors: a path with no prefix is in this repository (decoy CLI); `E:` is decoy-engine. Read at CLI `origin/main` `1eb0289c` and engine `origin/main` `e96d9b48` (0.28.2 released). Slice E0 is read from engine PR #745 (`3689700fd`, base `4a07e8a2c`). Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN contract), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `api-and-compatibility.md`, `data-and-migrations.md` (stored profile and plan formats), `cross-cutting-concerns.md`, `architecture.md`, `testing.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `security.md` (value-free messages), `documentation.md`, `workspace-and-vcs.md`.

## 1. Frame

### 1.1 Problem

The engine reads a date or a number out of a cell in several different ways today:

- `date_shift` refuses at plan compile when `provider_config.date_format` is missing (`date_shift_requires_date_format`, engine #728). The check is config-only (`E:src/decoy_engine/contracts/strategy_requirements.py`), so it also refuses a Parquet or DuckDB column that is already a native date and has nothing to parse. The only exemption is an F06 declared column (`date_shift_owns_declared_format`).
- `bucket_perturb` detects a format from the cells when `date_format` is missing (`_detect_format`). On engine main, when detection fails it returns the whole column unchanged with a log line, and a non-null cell that does not parse keeps its source value with no row error, on the pandas and native paths. Slice E0 (engine PR #745, merged 2026-11-21) fixes both pass-throughs; section 8.1 records what it changed.
- `bucketize` coerces with `pd.to_numeric(errors="coerce")` (`E:src/decoy_engine/execution/_strategies/_bucketize.py:101`) and `top_code` uses its own exact parser (`E:src/decoy_engine/execution/_strategies/_top_code.py:105-131`). Both accept CSV text with no declaration. `bucketize` turns `Decimal` cells into binary floats; `top_code` refuses a column that holds a finite fractional value.
- `windowed_date` accepts text anchors only in one fixed ISO grammar (`_ISO_ANCHOR`). That grammar is a fixed, documented format, not a guess, so this row leaves `windowed_date` as it is (open question Q9).

Typed sources have a second problem. `date_shift` on a typed column calls `_canonicalize_source` on the raw value. A `datetime.date` digests as its ISO text, but a tz-naive `pd.Timestamp` hard-errors at run time (`timezone_naive_datetime`). The typed path writes `shifted.astype(str)`, so a typed date comes out as text.

### 1.2 Owner decisions (quoted)

Owner, 2026-11-21, "go with recommended":

> Column type and format declarations are optional by default and required only where the engine would otherwise guess:
> - Typed sources (Parquet, DuckDB, database, Arrow) with a native date or number column: type and format come from the source schema; no declaration needed. A declaration is an explicit override and a mismatch is refused.
> - Untyped input (CSV, or a string column holding dates or numbers) used by a strategy that interprets the value (date: `date_shift`, `windowed_date`, `bucket_perturb` on dates; numeric: `bucketize`, `top_code`, `bucket_perturb` numeric; `fpe` where it depends on charset/shape): the type plus its format is required, refused at plan compile with a coded reason if missing.
> - Value-opaque strategies (`hash`, `redact`, `tokenize`, faker replacement, `shuffle`, `categorical`): never need a declaration.
> - Never guess at run time. Detection happens only in `decoy scan` and the starter config, which write the detected format for the user to confirm (`.decoy` uses the `?` review marker so `decoy run` refuses until cleared).
> - One rule in one place: extend `src/decoy_engine/contracts/strategy_requirements.py` (today config-only) so a requirement can depend on the resolved source column type; the check runs at plan compile against the source schema. No per-strategy copies.
>
> Concrete changes: (1) `date_shift` stops requiring `date_format` on native date columns; (2) `bucket_perturb` stops auto-detecting a date format from cells and requires it on text dates (adds a refusal: freeze item, must land before 1.0); (3) the numeric strategies follow the same rule.

Owner, 2026-11-21, on the language:

> Since decoy language is primary pipeline writer now, we can express more details in code far easier than devs writing YAML, so we should watch for ways to abstract details or explicitly inform the engine now that we have this format to compile down to a plan.

Three facts from the code change how the decision reads:

- The engine has no numeric `bucket_perturb`. `VALID_BUCKETS` is week, month and quarter, and the module docstring calls it a datetime strategy. This plan treats `bucket_perturb` as a date strategy only (open question Q1).
- The engine already has one declared-type system: F06 (`logical_type` plus `parse_format`, `E:src/decoy_engine/contracts/declared_casting.py`). It parses text into a typed value at the boundary on every route (`pre_mask_cast` is in every route's capability set in `E:src/decoy_engine/declared_casting/_eligibility.py`). This plan uses F06 as the numeric declaration instead of adding a second parser.
- The numeric strategies do not compute exactly on every decimal. `bucketize` computes in float64, which is exact for a decimal of at most 15 significant digits and an integer width, and can put a wider decimal in the wrong bucket. `top_code` computes on integers only. So this row admits only what they compute exactly (section 3.2), and widening them is a later row (section 9.4).

### 1.3 The guarantee

After this row, for every column whose strategy reads the value:

1. The plan compiler knows the column's shape (text, date, timestamp, integer, float, decimal, wide decimal, boolean, other, unknown) from one classifier that reads the source format, the Arrow type and the config's declarations. Every executed source gives its Arrow schema to it: file sources, resident tables, source-loader (database) tables, and chunked inputs, including a chunked input with zero chunks.
2. On a text column, the strategy runs only with an explicit declaration. A missing declaration is a coded refusal at plan compile. When the source format alone proves the column is text (CSV, fixed width), the refusal comes before any data row is read.
3. On a typed column, no declaration is needed. A declaration of the wrong kind, or a typed column the strategy cannot compute exactly, is a coded refusal.
4. No strategy detects a format from cells at run time. No strategy returns a source value unchanged because it could not parse it.
5. The rule is one table in `contracts/strategy_requirements.py`, read by the plan check, the handler backstops, the strategy catalog, the starter config and the language. Strategies with a rule: `date_shift`, `bucket_perturb`, `bucketize`, `top_code`, `fpe`.
6. A saved profile and a saved plan carry the shapes, so a compile or a run from a stored artifact gives the same result as from the in-memory one.

Non-goals: date spans in free text under `text_mask` and `text_redact` (detection inside free text is not a column shape, so their `_detect_format` stays); `windowed_date` (keeps its fixed ISO anchor grammar); generate tables (generators make typed values); `truncate`, `geo_generalize`, `code_set`; typed CSV reading (the CSV reader stays all-text); a canonical digest for tz-naive timestamps; the F06 output formatter; exact decimal arithmetic in `bucketize` and fractional values in `top_code` (section 9.4). `nested` children are in scope: they resolve to `text`, so a `bucket_perturb` or `date_shift` child needs `date_format`, and the shape check walks them the way `E:src/decoy_engine/plan/_checks_bucket_perturb.py:71` walks `nested` entries today.

## 2. Established solutions

Search run 2026-11-21 (web, plus engine and CLI code).

- Frictionless Table Schema: each field has a `type` and an optional `format`. A `date` takes `default` (ISO), a strptime pattern, or `any` (guess). A `number` takes `decimalChar` and `groupChar`. Source: https://specs.frictionlessdata.io/table-schema/ . The design follows its pair of type plus format, and drops `any`, which is the guess the owner forbids.
- Apache Spark CSV: `inferSchema` is off by default, and `dateFormat` applies only to columns typed as dates. Inference has had bugs in both directions (SPARK-19228, SPARK-45424). Source: https://spark.apache.org/docs/3.5.6/sql-data-sources-csv.html . This supports "never infer at run time; text stays text unless declared".
- dbt model contracts: with `contract: enforced`, every column needs a `data_type`, and a mismatch with the built model fails the build. Source: https://docs.getdbt.com/reference/resource-configs/contract . This is the "declaration is checked against the real type; a mismatch is refused" half.
- IEEE 754 binary64 carries 15 significant decimal digits exactly (DBL_DIG = 15, C11 `<float.h>`). This is the bound for the `decimal` shape that `bucketize` admits.
- In the engine: F06 already has strict integer and decimal lexers (`integer/ascii/v1`, `decimal/plain/v1`, `decimal/grouped/v1`) and date parse formats, routed through one eligibility decision. `strategy_requirements.py` is already the one table of required settings, read by the plan check, `strategy_catalog` and `starter_config`. `DeclarationRequest.for_run` already reads every source schema from headers, footers and the source-loader schemas before any data row.

Custom code that remains: the shape classifier (a short mapping from source format, Arrow type and config declarations to a closed enum), the shape assembler, and the shape-aware descriptor. No new parser is written.

## 3. Behaviour

### 3.1 Shape resolution

One classifier and one assembler.

Two mapping functions, both in a new leaf `E:src/decoy_engine/contracts/column_shape.py`. They are the only code that maps a type to a shape:

- `classify_column(*, source_format: str | None, arrow_type: pa.DataType | None) -> ColumnShape` maps what the data is: the text source format row, then the Arrow rows of the table below. It uses `is_text` from `E:src/decoy_engine/_arrow_types.py` for the text test and does not repeat it. `arrow_type=None` means "no schema here" and gives `unknown`.
- `declared_shape(*, logical_type: str, parse_format: Mapping[str, Any] | None) -> ColumnShape` maps an F06 declaration (the first row of the table below).
- `build_column_shapes(config, *, profile=None, source_schemas=None) -> ColumnShapes` in a new `E:src/decoy_engine/plan/checks/_column_shapes.py`. It reads the config facts (source format, F06 declarations, `nested` entries) for every column under a shape-reading strategy and gives each one shape. It is the only function the plan check, `compile_plan` and `run_config_only_checks` call to get shapes.

`classify_column` has exactly two allowed callers and `declared_shape` has one, named in the sentry (section 6):

1. `walk_dataframe` in `E:src/decoy_engine/profile/_walk.py`. It already receives `arrow_schema` (`:51`, read at `:133`). It gains `source_format` and stores `ColumnProfile.shape` from `classify_column(source_format=..., arrow_type=...)`. This is the observed shape of the data.
2. `build_column_shapes`. For each column it takes the first that applies, in this order: (a) an F06 declaration gives `declared_shape(...)`; (b) a `nested` child gives `text`; (c) a source format in `TEXT_SOURCE_FORMATS` gives `text`; (d) the profile has the column: its `ColumnProfile.shape` is used as it is (it is already a `ColumnShape`, so it is never passed to `classify_column` as an Arrow type); (e) `source_schemas` has the column: `classify_column(source_format=..., arrow_type=<that field's type>)`; (f) otherwise `unknown`. Rule (c) is repeated here, ahead of (d), so a profile taken before a format edit cannot override the config's text format.

Every executed source reaches the assembler with its schema:

| Source | Where its schema comes from | Change |
|---|---|---|
| File source with a config descriptor (local, S3, GCS) | the descriptor's reader; `profile_source` calls `walk_dataframe` at `E:src/decoy_engine/profile/_source.py:238-245` and `:283-291` with `arrow_schema=_nested_capable_schema(reader)` | `profile_source` passes the descriptor's `format` as `source_format` |
| Resident caller table | the table's schema, through `ResidentTableSource` (`_source.py:178`) | `source_format` is the source kind `table` |
| Source-loader table (database, DuckDB) | `source_loader_schemas`, already passed to `DeclarationRequest.for_run` at `E:src/decoy_engine/execution/pipeline/_routing_facts.py:74`, but not to `profile_source` at `:89-94`, and the profile has no entry for these tables | `build_routing_facts` passes `source_schemas = {**caller schemas, **source_loader_schemas}` to `compile_plan`, which hands them to `build_column_shapes`; a table the profile lacks takes its shape from that map |
| Public chunked entries: `run_mask_pipeline_chunked` (requires `source_schema`, `E:src/decoy_engine/execution/_chunked.py:382-388`) and `run_mask_chunked` (`E:src/decoy_engine/execution/native/_chunked_entry.py:589`, schema only from a `_FixedSchemaChunks` input, captured at `:435`) | the first chunk's schema, or the entry's schema when there are zero chunks | `walk_one_table` (`E:src/decoy_engine/execution/_chunked_profile.py:36`) passes `arrow_schema=table.schema` and the source format. Today the schema is dropped before `empty_input_profile` (`:120`), so E1a adds a keyword `source_schema: pa.Schema \| None = None` along the whole path: `_mask_pipeline_chunked` (`_chunked_oracle.py:507`) passes its `source_schema` to `_mask_declared` (`:551`), which passes it to `_oracle_preflight` (`:90`), which passes it to `_oracle_preflight_admitted` (`:167`), which passes it to `empty_input_profile(config, *, table, engine_version, source_schema=None)` at `:238`. The native `_run_chunked` (`_chunked_entry.py:410`) passes its `captured_schema` to `_oracle_preflight` at `:436`. `empty_input_profile` builds its empty frame from that schema, with `arrow_schema=source_schema`, instead of object placeholders from config names. An arbitrary iterable with zero chunks has no schema, so its columns stay `unknown` and a declaration is required (fail closed) |
| A caller with no schema (internal tests, `--no-profile`) | none | `unknown` |

The classifier table, in precedence order (the first row that matches wins):

| Input | Shape |
|---|---|
| F06 declared column (`logical_type` set) | the declared logical type: `date`; `integer`; `decimal` when the bounded-decimal rule below holds for `parse_format.precision` and `parse_format.scale`, else `decimal_wide`; `currency` counts as decimal by the same rule; `string` is `text`. The boundary casts it before the strategy runs |
| `nested` child | `text` |
| Source format `csv` or `fixed_width` (known from the config) | `text`, whatever the reader inferred. The cloud CSV reader infers numbers; this keeps CSV untyped on every reader |
| Arrow `string`, `large_string` | `text` |
| Arrow `date32`, `date64` | `date` |
| Arrow `timestamp` with a time zone | `timestamp_tz` |
| Arrow `timestamp` with no time zone | `timestamp_naive` |
| Arrow signed or unsigned int | `integer` |
| Arrow float | `float` |
| Arrow decimal for which the bounded-decimal rule holds | `decimal` |
| Any other Arrow decimal (precision above 15, or a negative scale) | `decimal_wide` |
| Arrow bool | `boolean` |
| Any other Arrow type | `other` |
| No Arrow type (config-only pass on a Parquet, database or caller-table source; a caller with no schema) | `unknown` |

The bounded-decimal rule: `0 <= scale <= precision <= EXACT_FLOAT_DECIMAL_DIGITS` (15). It bounds the magnitude below `10^15` and makes every value a multiple of `10^-scale`, so `floor(value / width) * width` fits in `int64` and float64 rounding never moves a value across an admitted bucket boundary (the argument is under 3.2). Arrow allows a negative scale: `decimal128(15, -5)` holds values up to `9.99999999999999E+19`, which `_bucketize.py:101` rounds through float64 and then fails to cast to `Int64` (reproduced by Codex round 2). A negative scale is therefore `decimal_wide`, which `bucketize` refuses at compile.

`ColumnProfile.shape` holds the result of rows 3 onward (what the data is). The F06 and `nested` rows are config facts, applied by `build_column_shapes`. So a profile saved before a config edit still gives the right shape after it.

A column made by a `derive` transform takes the Arrow type the transform produced (open question Q6). `unknown` is never treated as typed. The config-only pass defers it. At compile, `unknown` gets the same rule as `text`: a declaration is required.

### 3.2 Behaviour table (source kind by strategy family)

"Text declaration" means:

- date strategies: `provider_config.date_format`. For `date_shift` only, an F06 date declaration also counts (today's exemption).
- numeric strategies: an F06 declaration with `logical_type` `integer` (both strategies) or `decimal` that meets the bounded-decimal rule of 3.1 (`bucketize` only, with an effective width that is an integer from 1 to `10^15`). The effective width is what `resolve_bucketize_width` returns: the preset's width when `preset` is set (every preset is an integer from 1 to 10000, so `by_decade` and the others are admitted), else `width`.

| Strategy | `text` (CSV, fixed width, string column, nested child) | `date` | `timestamp_tz` | `timestamp_naive` | `integer`, `float` | `decimal` | `decimal_wide` | `boolean`, `other` |
|---|---|---|---|---|---|---|---|---|
| `date_shift` | text declaration required, else `date_shift_requires_date_format` (kept) | runs with no declaration; output keeps the source type | runs; whole-day shift, zone kept | refused `column_shape_mismatch` (today it fails at run time with `timezone_naive_datetime`) | refused `column_shape_mismatch` | refused | refused | refused `column_shape_mismatch` |
| `bucket_perturb` | `date_format` required, else `column_shape_required` (new refusal; today it detects) | runs with no declaration; output keeps the source type | refused `column_shape_mismatch` (Q5) | refused `column_shape_mismatch` | refused `column_shape_mismatch` | refused | refused | refused `column_shape_mismatch` |
| `windowed_date` | unchanged: no shape rule in this row | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |
| `bucketize` | F06 `integer`, or F06 bounded `decimal` with an integer effective width (a preset or `width`) from 1 to `10^15`, required, else `column_shape_required` | refused `column_shape_mismatch` | refused | refused | runs with no declaration (as today) | runs with an integer effective width (a preset or `width`) from 1 to `10^15`; any other width is refused `column_shape_mismatch` | refused `column_shape_mismatch` ("more than 15 digits or a negative scale; float64 would mis-bucket") | refused `column_shape_mismatch` |
| `top_code` | F06 `integer` required, else `column_shape_required`; F06 `decimal` refused `column_shape_mismatch` | refused | refused | refused | runs with no declaration (as today) | refused `column_shape_mismatch` (Q11) | refused | refused |
| `fpe` | runs. The charset (default `digits`) is the shape; a value outside the charset is refused per row (as today) | refused `column_shape_mismatch` | refused | refused | `integer` runs (base-10 text, as today); `float` refused (Q4) | refused | refused | refused |
| `hash`, `redact`, `tokenize`, `faker`, `shuffle`, `categorical`, `passthrough` and every other strategy | no declaration, no check | same | same | same | same | same | same | same |

Why the decimal cells are cut this way: `bucketize` floors `value / width` in float64 (`_bucketize.py:101-102`). The guarantee is not that float64 keeps every digit; it is that rounding never crosses an admitted bucket boundary. Under the bounded-decimal rule a value `v` and every boundary `k * width` are multiples of `10^-scale`, so a value that is not on a boundary is at least `10^-scale` away from it. The float64 error of `v / width` is below `2^-52 * |v| / width`, and with `|v| < 10^(15 - scale)` that is under a quarter of `10^-scale / width`, the smallest distance of the quotient from an integer. A value on a boundary is an integer below `2 * 10^15 < 2^53`, so it and its quotient are exact. Each value therefore lands in its true bucket. A wider decimal, or a width such as `0.1`, can put a value in the next bucket down. The width bound keeps the output range inside `int64`: with `|value| < 10^15` and `width <= 10^15`, the lower bound, the upper bound and the midpoint all stay below `2 * 10^15`. An integer `width` above the `int64` range raises today in the `Int64` cast, so the bound is checked at compile for the decimal cells.

One width contract. Today the handler (`_resolve_width`, `E:src/decoy_engine/execution/_strategies/_bucketize.py:146-153`) and the compile check (`E:src/decoy_engine/plan/_checks_bucketize.py:76-95`) each decide the effective width, and they share only `_PRESETS` (`_bucketize.py:51-59`). The shape rule would be a third. So E3 moves `_PRESETS` and the resolution into a new leaf `E:src/decoy_engine/contracts/bucketize_width.py`: `BUCKETIZE_PRESETS` and `resolve_bucketize_width(provider_config) -> int | float | None` (a known preset gives its width and `width` is ignored, as today; an unknown preset gives `None`; else a positive non-boolean number, else `None`). The handler, `_checks_bucketize.py` and the shape rule all call it, and none of them reads `preset` or `width` itself. The sentry of section 6 pins the three callers. Behaviour for today's configs does not move. Typed `integer` and `float` columns keep today's behaviour, including today's handling of large values and large widths (non-goal of this row). `top_code` reads integers exactly and fails the whole column on a fractional value (`_top_code.py:108-131`), so admitting a decimal declaration would compile a job that fails at run time.

A declaration on a typed column:

| Declaration | On a typed column of the same kind | On a typed column of another kind |
|---|---|---|
| `date_format` on a `date` column | accepted and not used; value-free plan warning `column_shape_format_unused`; output keeps the source type | refused `column_shape_mismatch` |
| F06 declaration on any non-string column | refused by F06 as today (`declared_cast_input_type_incompatible`): F06 parses text only | same |

This is how the plan reads "a declaration is an explicit override and a mismatch is refused": on a typed column the declaration is checked, and it is never used to parse the value again (open question Q2). The override check runs on every source kind in section 3.1, including source-loader tables (test in E1b).

### 3.3 Outputs on typed columns

- `date_shift` and `bucket_perturb` on a `date` column write a date of the same Arrow type (`date32` stays `date32`). On `timestamp_tz`, `date_shift` keeps the unit, the zone and the time of day.
- The digest input of a typed date is `_canonicalize_source(date)`, which is its ISO text. So a Parquet date and the CSV text `2024-01-15` in the same namespace get the same offset. The builder must make sure the handler passes `datetime.date` values (or the calendar date) to the digest, never a tz-naive `Timestamp`.
- `preserve_values` on a typed date column needs no `date_format`. The sentinel stays a typed date (`date_preserve._is_typed_date` exists).

### 3.4 `windowed_date` anchors

No change in this row. Text anchors keep the fixed `_ISO_ANCHOR` grammar (`E:src/decoy_engine/transforms/windowed_date.py:77`) with no declaration. A required `anchor_format` with one allowed value would be ceremony. A later optional `anchor_format` (default `iso8601`, strftime values allowed) is additive and is listed in section 9.4.

### 3.5 When the check runs

- Config-only (`run_config_only_checks`, a separate entry point at `E:src/decoy_engine/plan/_compile.py:485`, whose `check_required_strategy_settings` call is at `:565`, plus the early call in `build_run_context`): `build_column_shapes(config)` with no profile and no schemas. Shapes come from the config alone (CSV, fixed width, nested, F06). `unknown` columns are deferred, not refused. So `decoy validate` on a CSV pipeline still refuses a missing `date_format` before any read. On a Parquet pipeline the refusal moves from `decoy validate` to compile. This move lands in E1a and is in E1a's compatibility note.
- Plan compile (`compile_plan`, `_compile.py:124`; its `check_required_strategy_settings` call is at `:254`): `build_column_shapes(config, profile=profile, source_schemas=source_schemas)`. `compile_plan` gains the keyword `source_schemas`, which `build_routing_facts` fills (section 3.1). Every compile site gets the shapes, including the chunked first-chunk profile and the zero-chunk profile.
- The plan records the shape of each column under a shape-reading strategy (`Plan.column_shapes`).
- The one backstop rule: a handler skips the declaration only when the plan lists the column as typed (`date`, `timestamp_tz`, `integer`, `float`, or `decimal`). In every other case (`text`, `unknown`, a column the plan does not list, a `--no-profile` run, a caller that skipped compile) the handler refuses when the declaration is missing. Handlers never look at the pandas dtype: a Parquet date and a CSV string both arrive as `object`. `declared_date_shift_columns(plan)` becomes `typed_date_columns(plan)`: F06 dates plus native dates.

### 3.6 Stored profiles and plans

- Profile JSON. `_column_to_dict` (`E:src/decoy_engine/profile/_serialize.py:107-111`) is hand-listed on purpose; E1a adds `"shape"` to it, and `_column_from_dict` (`:165-187`) reads it. A profile written before E1a has no `shape`: it loads as `unknown`, which fails closed (a typed column then needs a declaration until the user profiles again). A `shape` value this engine does not know is refused at load: `profile_from_json` raises its existing `ValueError` that names the field (`_serialize.py`, the same path as any other bad field). A stored token is never mapped to `other`. `shape` goes into `profile_hash` (`_data_shape_bytes`, `_serialize.py:50-75`). It cannot stay out like `avg_length`: it changes masking, and it is not a function of the pandas `dtype` (an Arrow `date32` column and a text column can both be `object`). So the pinned digest in `test_hash_regression.py` moves once in E1a, recorded as a pre-GA note. Because `profile_hash` is a part of the physical `compute_plan_hash` (`E:src/decoy_engine/execution/physical/_inputs.py:287`, `:305`), a shape change also changes the physical plan hash. Profile `schema_version` stays 1: the field is additive and the reader defaults it.
- Plan YAML. `PLAN_VERSION` (`E:src/decoy_engine/plan/_compile.py:120`) goes from 4 to 5. `_plan_to_dict` (`E:src/decoy_engine/plan/_serialize.py:94-117`) writes `column_shapes` only when it is not empty, as `declared_casting` is written, so a plan with no shape-reading strategy differs from its version-4 form only by the version line. `_plan_from_dict` (`:275-303`) reads it with an empty default. An unknown shape token is refused at load with the new code `plan/stored_shape_unknown` (F12), never mapped to `other`. `Plan.column_shapes` goes into the physical plan hash: a loader table takes its shapes from `source_loader_schemas`, and `compute_plan_hash` (`E:src/decoy_engine/execution/physical/_inputs.py:287-348`) hashes only `source_loader_present` (`:320`) for loaders, so two runs that differ only in a loader schema would otherwise share a hash. E1a adds one part to `compute_plan_hash`: the canonical JSON of `Plan.column_shapes`, sorted by table and then column. `capture_physical_plan_inputs` (`E:src/decoy_engine/execution/physical/_snapshot.py:49`) accepts a loader but cannot pass its schema to compile today, so E1a adds a `source_loader_schemas` keyword to it and passes it to `compile_plan(..., source_schemas=...)`, the same map `build_routing_facts` builds.
- Older plans need a recompile. A version-4 plan has no `column_shapes`, and an empty map would refuse plans that are valid today: typed `bucketize` and `top_code` columns run with no F06 declaration, and `bucket_perturb` may omit `date_format`. A second, legacy rule set for version-4 plans would be a second copy of the rule. So E1a refuses a plan with `plan_version` below `PLAN_VERSION` at load with the new code `plan/plan_recompile_required` (F11): "this plan was written by an older engine (plan_version `<n>`); compile it again from its config." The config is unchanged, so `decoy validate compile` or the run itself gives a version-5 plan. This is allowed before 1.0 (the CLI's pre-GA rule: breaking changes need no migration adapter) and is a pre-GA note. E1a carries one version-4 fixture plan per family that is valid today (`date_shift` with `date_format`; `date_shift` on an F06 date; `bucket_perturb` with and without `date_format`; `bucketize` and `top_code` on a typed number and on CSV text; `fpe`): each is refused with F11 at load, and its config compiled again on the new engine gives a version-5 plan that runs, or is refused only by a freeze item of section 12.
- Newer and malformed artifacts. Today `_plan_from_dict` accepts any `plan_version` (`data["plan_version"]`, `:282`). E1a checks it first, before any other field: a missing key, a boolean, a string, a float or any other non-`int` value, and an `int` above `PLAN_VERSION`, are each refused with the new code `plan/plan_version_unsupported` (F10), so an engine from E1a on never runs a plan whose fields it would drop. The refusal is raised with `from None` and its message holds the version only when it is an `int`, so no stored value reaches the error text or its `__cause__` and `__context__`.
- Rollback. Code rollback is safe and needs no data recovery: an engine before E1a reads a version-5 plan, ignores `column_shapes` and applies its older rule (a `date_format` on every `date_shift` column), and it ignores the profile's `shape`. Neither artifact is rewritten in place.

## 4. Failure modes and reason codes

All new codes are registered with `since` unreleased. Messages name the table, column, strategy and config field. They never hold a cell value or a config value.

| # | Failure | Code | Where | Message (fixed text, by family) |
|---|---|---|---|---|
| F1 | `date_shift` on text with no date declaration | `plan/date_shift_requires_date_format` (kept) | compile; runtime twin kept | "date_shift needs provider_config.date_format, the strftime format of its dates." |
| F2 | date or numeric strategy on text or `unknown` with no declaration | `plan/column_shape_required` (new) | compile | date: "`<strategy>` reads dates from text; set provider_config.date_format." numeric: "`<strategy>` reads numbers from text; declare logical_type integer with a parse_format." (`bucketize` adds "or decimal with precision 15 or less") |
| F3 | The strategy family, declaration kind, decimal width or `width` does not match the column | `plan/column_shape_mismatch` (new) | compile | "column `<c>` in table `<t>` is a `<shape>` column; `<strategy>` cannot read it." Plus one hint per cell of 3.2. For `timestamp_naive`: "cast it to a date or a zoned timestamp, or write it as text with a date_format." For `decimal_wide`: "more than 15 significant digits cannot be bucketed exactly; reduce the precision or cast to float." |
| F4 | `bucket_perturb` gets no usable format: in E0, no `date_format` and detection found none; from E2, no `date_format` on a column the plan does not list as typed | `runtime/bucket_perturb_requires_date_format` (built in E0, `reasons/runtime/_part2.py`) | the pandas transform `apply_bucket_perturb`, so every route that calls it; the native routes admit an explicit format only, so they never reach this case | "bucket_perturb needs provider_config.date_format, the strftime format of its dates." |
| F5 | `date_format` on a typed date column | `plan/column_shape_format_unused` (new, warning) | compile warning | "date_format is not used: the source column is already a date." |
| F6 | A handler receives a column the plan does not list as typed, with no declaration | `runtime/column_shape_required` (new) | `bucketize`, `top_code` backstops (E3); `bucket_perturb` uses F4 | same text as F2 |
| F7 | A non-null `bucket_perturb` cell does not parse under `date_format` | existing `RowError`, trigger `format_error`, reason "value is not a parseable date under bucket_perturb" (built in E0) | pandas handler; native sequential, chunked and shadow (physical) routes | the reason text above, no value |
| F8 | The classifier meets an Arrow type it does not list | shape `other`, never a crash | classifier | none |
| F9 | A `bucket_perturb` cell does not parse on a path with no row-error channel (the out-of-core route; a direct transform call with no `format_errors` list) | `runtime/bucket_perturb_unparseable_no_row_channel` (built in E0) | `out_of_core/_bucket_native.py`, `apply_bucket_perturb` | "bucket_perturb: `<n>` non-null value(s) do not parse under date_format and this route has no row error channel." (a count, no value) |
| F10 | A stored plan has a `plan_version` above this engine's, or a missing or non-`int` one | `plan/plan_version_unsupported` (new) | plan load | newer: "this plan was written by a newer engine (plan_version `<n>`); upgrade decoy-engine or compile the plan again." malformed: "this plan has no valid plan_version; compile the plan again." (no stored value) |
| F11 | A stored plan has a `plan_version` below this engine's | `plan/plan_recompile_required` (new) | plan load | "this plan was written by an older engine (plan_version `<n>`); compile it again from its config." |
| F12 | A stored plan has a `column_shapes` token this engine does not know | `plan/stored_shape_unknown` (new) | plan load | "column `<c>` in table `<t>` has a stored shape this engine does not know; compile the plan again." (no token) |

Removed in E0: the `bucket_perturb` path "could not detect date format; column values passed through unchanged", and the per-cell keep of unparseable values on every route. Removed in E2: every use of `_detect_format` by `bucket_perturb`.

## 5. Design notes

- One place per fact. The shape vocabulary and the classifier are in `contracts/column_shape.py`. The per-strategy rule (family, subject path, declaration fields, admitted shapes, code) is in `contracts/strategy_requirements.py` as a new frozen descriptor `ShapeRequirement` in a second table, `SHAPE_REQUIREMENTS_BY_STRATEGY`. Descriptors are data only, with no callable predicate, so a refusal cannot echo config data (the module's existing rule).
- One classifier, a named caller list. The config-only pass and the profile both need shapes, so a rule of "one call site" cannot hold. The rule is: `classify_column` is the only type-to-shape mapping, and only `profile/_walk.py::walk_dataframe` and `plan/checks/_column_shapes.py::build_column_shapes` call it. The sentry pins both the mapping and the caller list (section 6).
- Typed context over flags. The check takes a `ColumnShapes` mapping `(table, column) -> ColumnShape` from `build_column_shapes`. No strategy function gets a `typed: bool` flag. `preserve_config_problem` takes the resolved shape.
- Handlers do not learn about shapes. They read the plan's `typed_date_columns` set and the plan's `column_shapes`, which is the existing seam made wider.
- Extend the existing check; do not add a sibling. `check_required_strategy_settings(config, *, sources, shapes=None)` walks both tables. `_compile.py` (670 lines, ceiling 700) changes by one keyword argument, one call and one plan field.
- Principles applied: one source of truth (the requirement table), open for new strategies without edits elsewhere (a strategy adds one descriptor row), fail closed on an unknown shape at run time and on an unknown stored value.
- Rejected alternative: a per-strategy `number_format` option with its own parser. It would be a second numeric parser beside F06 and a per-strategy copy of the rule.
- Rejected alternative: exact decimal arithmetic in `bucketize` inside this row. It is a strategy change with its own output contract (string formatting of `Decimal` bounds) and belongs in its own row (section 9.4). This row refuses what the strategy cannot compute exactly.

## 6. Choke point and sentries

| Concern | Choke point | Guard test | Mutation that must turn it red |
|---|---|---|---|
| No run-time format detection (main sentry) | import rule: `transforms.date_shift._detect_format` is imported only by `transforms/text_mask.py` and `transforms/text_redact.py` (allowlist) | `E:tests/sentry/test_no_runtime_format_detection.py` (new, E2), import-graph walk of `src/decoy_engine/` including `execution/native/` | import `_detect_format` in `transforms/bucket_perturb.py` |
| Date parsing reads the declared format | `shape_declaration(plan, ...)` | same sentry, AST case: in `execution/_strategies/`, `transforms/` and `execution/native/`, every `pd.to_datetime(` call under a strategy in `SHAPE_REQUIREMENTS_BY_STRATEGY` passes `format=` from that helper or from the transform's required `date_format` parameter. `pd.to_numeric` has no format argument, so numeric strategies are covered by the F06 boundary and the E3 refusal tests, not by this case. `text_mask` and `text_redact` are allowlisted | add `fmt = cfg.get("date_format") or _detect_format(series)` back to `bucket_perturb` |
| No value pass-through on a parse failure | the `bucket_perturb` row-error channel (E0) | `E:tests/unit/strategies/test_bucket_perturb_safety.py::test_unparseable_cell_is_row_error`, `::test_native_unparseable_cell_is_reported_like_the_oracle`, `::test_transform_without_a_row_channel_refuses_instead_of_passing_through` | restore `continue  # preserve null / unparseable values` with no position recorded |
| Capability facts match the handlers | `execution/native/_capabilities.py` `bucket_perturb` entry and the `bucket_perturb` `OperatorSpec` in `execution/_operator_registry.py` | `E:tests/native/test_capabilities.py::test_row_error_strategies_are_exactly_the_six_emitters` (renamed from `_five_`), and a unified-slice admission test that a `bucket_perturb` node with the `format_error` obligation still admits | drop `row_error_modes=("format_error",)` from `bucket_perturb` |
| One classifier, named callers | `classify_column` in `contracts/column_shape.py` | `E:tests/sentry/test_column_shape_classifier.py` (new): (a) `classify_column` is called only from `profile/_walk.py` and `plan/checks/_column_shapes.py`, and `declared_shape` only from `plan/checks/_column_shapes.py` (AST walk of `src/decoy_engine/`); (b) within `plan/`, `profile/`, `execution/_strategies/` and `declared_casting/`, the `pa.types.is_date*`, `is_timestamp`, `is_decimal` predicates are used for shape only in `contracts/column_shape.py` | add an `is_date32` branch in `plan/checks/_required_settings.py`; call `classify_column` from `execution/_chunked_profile.py` |
| Catalog and starter agree with the table | `strategy_catalog()` `StrategyInfo.shape` | `E:tests/unit/test_strategy_catalog.py::test_shape_matches_requirement_table` | drop `top_code` from the table |

### 6.1 Class table

These rows use the defect classes of the plan contract.

| # | Class | Applies here | Structure that closes it | Test | Mutation that turns it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new refusal and warning messages; row errors and the no-channel refusal from `bucket_perturb` | messages are fixed text plus table, column, strategy and field names, or a count; row errors use the existing value-free `RowError` | `::test_messages_value_free` in E0 (built), E1b, E2, E3 (marker values in fixtures) | put the bad cell into the F7 reason or the F9 message |
| 2 | Cleanup missing on an exit path | a compile refusal after a partial read; the F9 refusal on the out-of-core route | refusals happen at plan compile, before any output is opened; F9 raises inside the kernel's existing `except BaseException: del mask_key; raise` path, before the batch is written | existing run-refusal tests extended by `test_codes_reach_cli_with_exit_1` (C1); E0's out-of-core refusal test | none new: no write path is added |
| 3 | Stale state | a shape recorded in a saved profile or plan that no longer matches the source at run time; a version-4 plan with no shapes | `shape` is in `profile_hash`, and the canonical `Plan.column_shapes` is a part of the physical `compute_plan_hash`, so a loader schema change also changes the hash; the run reads the same profile the plan was built from; a version-4 plan is refused at load (F11); a missing stored shape is `unknown`; the one backstop rule refuses any column the plan does not list as typed when its declaration is missing | `::test_handler_backstop_keys_on_plan` (E1b), `::test_handler_refuses_unlisted_column` (E2), `::test_v4_plans_need_recompile` (E1a) | make the backstop skip the check on an `object` dtype |
| 4 | Route parity | full frame, sequential, chunked, native (sequential, chunked, shadow), mixed and out-of-core routes; source-loader and resident sources | one check at compile; handlers read one plan field; E0 transports native format-error positions on every native route and refuses where no channel exists | `::test_parquet_date32_runs_without_format` over three routes; E0's pandas, native and pipeline tests (section 10); `::test_csv_top_code_with_integer_declaration_runs_on_every_route`; `::test_loader_table_shape_from_loader_schema` | drop the positions in `_bucket_perturb_ext.py` only |
| 5 | Referential integrity | `date_shift` on a key column shared by a CSV table and a Parquet table | the digest input of a typed date is its ISO text, the same bytes as the text form, so one namespace gives one offset | `::test_typed_offset_equals_iso_text_offset` | digest `str(pd.Timestamp(v))` for typed dates |
| 6 | Untrusted producer | a source schema from a file footer or a loader; a stored profile or plan; a `.decoy` `as` clause | the classifier maps every Arrow type to a closed enum (unknown types become `other`); a stored unknown shape token is refused at load (F12 for a plan, the existing `ValueError` for a profile); a newer, missing or non-`int` `plan_version` is refused (F10) with no stored value in the message, `__cause__` or `__context__`; the language checks the shape name and family before lowering | `::test_unlisted_arrow_type_is_other`, `::test_unknown_stored_shape_loads_as_other`, `::test_newer_plan_version_refused`, `::test_malformed_plan_version_refused`, `test_shapes.py` error tests | map an unlisted type to `date` |
| 7 | Check then use (TOCTOU) | the schema read at compile, then the data read at run | the schema read and the data read are the same files the declaration gate already pins (`prepare_declared_sources`); the source loader is wrapped by `declared.checked_loader` against the same `source_loader_schemas` (`E:src/decoy_engine/execution/_pipeline_context.py:374`); a changed type between them meets the handler backstop and fails closed | `::test_handler_backstop_keys_on_plan` | remove the backstop |
| 8 | Weak tests and overclaimed evidence | every acceptance test in section 10; #745 rewrote many old tests that expected pass-through | each slice names its mutation; tests assert output types and bytes, not only the absence of an error; the E0 gate checks that each rewritten test now asserts the refusal or a valid-date output, and that no golden was re-recorded | reviewer reruns the named mutations on the final head | removing a named mutation from the evidence is a gate finding |
| 9 | Behavior-preserving refactor drift | E1a moves the `date_shift` rule into the new descriptor and renames `declared_date_columns` | E1a keeps today's rule for every shape; the existing #728 tests run unchanged | `::test_date_shift_rule_unchanged_on_every_shape`; the existing `date_shift_requires_date_format` tests | make the E1a descriptor skip `date` shapes |
| 10 | Frozen contract drift | reason registry, `StrategyRequirement`, `StrategyInfo`, `strategy_catalog`, Profile JSON, plan format, `.decoy` grammar | codes are append-only; `StrategyRequirement` keeps its fields; `StrategyInfo.shape` is additive with a default; Profile JSON gains a defaulted field; `PLAN_VERSION` 4 to 5 with a load rule for older, newer and malformed versions; the language surface fixture records the grammar change | `tests/sentry/test_reason_baseline_frozen.py`, `tests/sentry/release/test_public_census.py`, `::test_profile_round_trip_keeps_shape`, `::test_plan_round_trip_keeps_column_shapes`, CLI `tests/unit/lang/test_language_freeze.py` | rename `date_shift_requires_date_format` |

## 6.2 Enumerations

### Fields

| Set | Members | Owner |
|---|---|---|
| `ColumnShape` | `text`, `date`, `timestamp_tz`, `timestamp_naive`, `integer`, `float`, `decimal`, `decimal_wide`, `boolean`, `other`, `unknown` | `contracts/column_shape.py` (new) |
| `TEXT_SOURCE_FORMATS` | `csv`, `fixed_width` | `contracts/column_shape.py`, checked against `FILE_FORMATS` in `E:src/decoy_engine/profile/_lazy_build.py` by the classifier test |
| `EXACT_FLOAT_DECIMAL_DIGITS` | 15 | `contracts/column_shape.py` |
| Config fields read | `provider_config.date_format`, `provider_config.width` (`bucketize`), F06 `logical_type` and `parse_format` (`precision`) | `SHAPE_REQUIREMENTS_BY_STRATEGY` beside `REQUIREMENTS_BY_STRATEGY` at `E:src/decoy_engine/contracts/strategy_requirements.py:60` |
| Profile field added | `ColumnProfile.shape`, beside `avg_length` at `E:src/decoy_engine/profile/_types.py:103` (`shape` is in `profile_hash`, `avg_length` is not; both in the full JSON) | `profile/_types.py`, `profile/_serialize.py` |
| Plan field added | `Plan.column_shapes`, `PLAN_VERSION = 5` | `plan/_types.py`, `plan/_serialize.py`, `plan/_compile.py` |
| Strategies with a shape rule | `date_shift`, `bucket_perturb`, `bucketize`, `top_code`, `fpe` | `SHAPE_REQUIREMENTS_BY_STRATEGY` |
| Language shapes | `date(fmt)`, `integer`, `decimal(precision, scale)` | `src/decoy/lang/_shapes.py`; YAML targets come from `StrategyInfo.shape` |
| New reason codes | E0 (built): `runtime/bucket_perturb_requires_date_format`, `runtime/bucket_perturb_unparseable_no_row_channel`. This row: `plan/column_shape_required`, `plan/column_shape_mismatch`, `plan/column_shape_format_unused`, `runtime/column_shape_required`, `plan/plan_version_unsupported`, `plan/plan_recompile_required`, `plan/stored_shape_unknown` | `reasons/runtime/_part2.py` (E0, as built), `reasons/plan/_part3.py`, `reasons/runtime/_part3.py` |

### Routes

Every route reads the shape from the plan; none resolves it again.

| Route | Where the shape check runs | Evidence |
|---|---|---|
| Config-only (`decoy validate`, early `build_run_context`) | `check_required_strategy_settings(config, shapes=build_column_shapes(config))` | `run_config_only_checks`, `E:src/decoy_engine/plan/_compile.py:485`, call at `:565` |
| Compile in a run | the `check_required_strategy_settings` call in `compile_plan`, `E:src/decoy_engine/plan/_compile.py:254`, with the shapes from the profile and `source_schemas` | the profile comes from `build_routing_facts`, `E:src/decoy_engine/execution/pipeline/_routing_facts.py:74` (`DeclarationRequest.for_run`), `:89-94` (`profile_source`), then `compile_plan` |
| Source-loader (database, DuckDB) tables | compile, from `source_loader_schemas` through `source_schemas` | `_routing_facts.py:74`; the loader is wrapped at `_pipeline_context.py:374` |
| Public chunked entry, non-empty and zero-chunk | compile on `first_chunk_profile` or on `empty_input_profile(source_schema=...)` | `E:src/decoy_engine/execution/_chunked_oracle.py:238-240`, `_chunked.py:388` |
| Full frame, sequential, chunked, mixed, out of core | the one backstop rule on `typed_date_columns`, today `declared_date_columns` at `E:src/decoy_engine/execution/_strategies/_date_shift.py:102` | F06 `pre_mask_cast` is in every route's set, `E:src/decoy_engine/declared_casting/_eligibility.py:43` and `:52` |
| Native `bucket_perturb` (sequential, chunked, shadow, out of core) | admits explicit formats only; E0 transports row errors on the first three and refuses on out of core | E0 tests (section 10) |
| Native `date_shift` | admits explicit formats only; unchanged by E0 | existing parity tests |

### Exit paths

| Path | Outcome |
|---|---|
| Compile refusal (F1 to F3) | `PlanValidationError` with the code; CLI config-refusal exit; no output opened |
| Plan load refusal (F10, F11, F12) | coded refusal before any run step |
| Compile warning (F5) | plan warning; run continues |
| Handler backstop or transform refusal (F4, F6) | runtime refusal with the code; the run stops before writing that table |
| Row error (F7) | existing row-error accounting; the run fails, or the row is quarantined when quarantine covers `format_error`; never a pass-through |
| No row-error channel (F9) | runtime refusal with the code; the batch is not written |
| F06 cast failure on a declared numeric column | F06 `error_policy` (default fail) |

### FK shapes

A `date_shift` column used as a key across tables keeps one offset per value only when every table gives the digest the same bytes.

- CSV text and Parquet `date32` in one namespace: same ISO bytes, same offset (`::test_typed_offset_equals_iso_text_offset`).
- Two Parquet tables with `date32` keys: same type, same bytes.
- A `timestamp_tz` key: UTC ISO bytes, as today.
- A `timestamp_naive` key: refused at compile (F3).
- Numeric strategies as keys: not join-safe today, and unchanged.

### Output surfaces

| Surface | Change |
|---|---|
| Masked data, typed date columns | keeps the Arrow type; today text from `shifted.astype(str)` at `E:src/decoy_engine/execution/_strategies/_date_shift.py:340` |
| Masked data, `bucket_perturb` text | unchanged for valid rows (E0 checked this against main with fixed inputs); unparseable cells become row errors |
| Profile JSON | adds `shape` per column |
| Plan YAML | `plan_version: 5`; adds `column_shapes` when not empty |
| Refusal and warning messages | fixed text plus names, or a count (class 1) |
| Starter YAML and `.decoy` init output | `date_format` or `as date(...)` for text only |
| `strategy_catalog()` | `StrategyInfo.shape` |

## 6.3 Reuse inventory

| Need | Reused | Not built |
|---|---|---|
| Parse integers and decimals from text | F06 lexers `integer/ascii/v1`, `decimal/plain/v1`, `decimal/grouped/v1` | a `number_format` option |
| Read the source schema before data | `DeclarationRequest.for_run`, `source_loader_schemas`, the chunked entry's `source_schema`, and the profile built in `build_routing_facts` | a second schema reader |
| One table of strategy requirements | `contracts/strategy_requirements.py` and its readers | a per-strategy check |
| Typed dates in sentinels | `date_preserve._is_typed_date` | new sentinel code |
| Row errors | the existing `RowError` channel, `format_error` trigger, and `StepResult.format_error_positions` (E0 widened it from `date_shift` only) | a new error type |
| Stored-format defaults | the hand-listed `_column_to_dict` and the `declared_casting` omit-when-empty pattern in `plan/_serialize.py` | a new serializer |
| Review gate on detected formats | the `.decoy` `?` mark and `lang.unreviewed` (DECOY-LANG) | a new confirm step |
| Shape mapping from Arrow | `pyarrow.types` predicates | a hand-written type parser |

## 6.4 Frozen contracts

Touched frozen or public surfaces, and what stays fixed:

- `plan.checks.StrategyRequirement` (public census): fields unchanged. `ShapeRequirement` is a new name and is listed as documented internal until 1.0.
- `strategy_catalog()` and `StrategyInfo`: one additive field, `shape`, with a default of `None` for value-opaque strategies.
- Reason registry: append-only. `date_shift_requires_date_format` keeps its code, path and text.
- Profile JSON: `shape` is added per column; old profiles load as `unknown`; `profile_hash` moves once because `shape` is hashed (the pinned digest in `test_hash_regression.py` is updated in E1a with this reason). Recorded as a pre-GA note.
- Plan format: `PLAN_VERSION` 4 to 5; `column_shapes` is added; `pipeline_config_hash` does not move; the physical plan hash moves through `profile_hash` and the new `column_shapes` part; version-4 plans are refused with a recompile message (F11), newer and malformed versions are refused (F10). Recorded as a pre-GA note.
- `.decoy` syntax: the CLI already freezes the language as a 1.0 surface (`tests/unit/lang/test_language_freeze.py`, fixture `tests/fixtures/release_freeze/lang-surface.json`, rule in `docs/release/frozen-surfaces.md`: a new construct may only take a place where today's grammar gives a syntax error, and codes are never renamed or removed). `as` after the names of a `mask` rule is such a place today (`mask: names ":" treatment`, `src/decoy/lang/_grammar.py:85`), and `as` is not in `_KEYWORDS` (`_grammar.py:18-24`), so existing programs keep their meaning. C2 regenerates the fixture with `python -m tests.unit.lang.surface`, records the grammar and the three new codes in `CHANGELOG.md`, and must not change any existing code.
- CLI exit codes: unchanged. Every new refusal uses the existing config-refusal exit.

## 6.5 Pre-mortem

Assume the row shipped and failed. The likely causes, and what in the plan stops each:

| Failure | Stopped by |
|---|---|
| A Parquet `date_shift` run gives offsets that differ from the CSV run of the same data, breaking joins | `::test_typed_offset_equals_iso_text_offset`; class 5 |
| Cloud CSV reads infer `int64`, so a CSV `top_code` runs with no declaration on S3 but is refused locally | shape keys on source format first; `::test_csv_is_text_even_when_reader_inferred_int` |
| A database table is refused as `unknown` because its schema never reached the shapes | `source_schemas` from `source_loader_schemas`; `::test_loader_table_shape_from_loader_schema` |
| A zero-row chunked Parquet input is refused while the same input with rows runs | `empty_input_profile(source_schema=...)`; `::test_zero_chunk_input_takes_source_schema_shape` |
| A saved profile compiles differently from the in-memory one | `shape` in Profile JSON; `::test_profile_round_trip_keeps_shape` |
| A high-precision or negative-scale decimal lands in the wrong bucket or fails the run | the bounded-decimal rule and the width bound; `::test_bucketize_wide_decimal_refused`, `::test_bucketize_negative_scale_decimal_refused`, `::test_bucketize_decimal_boundary_exact` |
| A stored version-4 plan that runs today is refused after the upgrade | F11 names the cause and the fix (compile again); the per-family v4 fixtures prove a recompile restores each one |
| A new strategy reads dates with its own `pd.to_datetime` and skips the rule | the section 6 sentry over `execution/_strategies/` and `transforms/` |
| `bucket_perturb` users with dirty dates see runs fail after the upgrade | the refusal and row errors are listed freeze items with compatibility notes and docs; `preserve_values` keeps sentinels; the starter writes the format |
| Doc examples break, so new users hit the refusal on the first try | C1's engine-checking docs test runs every program and YAML example through `run_config_only_checks` |
| `decoy validate` passes a Parquet config that `decoy run` then refuses | documented as a moved refusal; `validate compile` catches it; `::test_config_only_defers_unknown` pins the split |
| `_serialize.py` or `_compile.py` passes the size ceiling | the Placement table names the sibling file and the line budget |

## 7. Placement

| File | Change | Why there | Size after (goal 600, ceiling 700) |
|---|---|---|---|
| `E:src/decoy_engine/contracts/column_shape.py` (new) | `ColumnShape` enum, `TEXT_SOURCE_FORMATS`, `EXACT_FLOAT_DECIMAL_DIGITS`, `classify_column`, `declared_shape`, `ColumnShapes`, `SourceFacts` with `build_source_facts` and `source_facts_of` (the one value that says which tables the caller supplied and their schemas), `source_format_for`, `is_nested_type` | CODEMAP "Versioned contracts" row: a leaf contract beside `strategy_requirements.py`; imports `pyarrow`, `_arrow_types` (for `is_text`) and `reasons` only | about 100 |
| `E:src/decoy_engine/contracts/strategy_requirements.py` | `ShapeRequirement`, `SHAPE_REQUIREMENTS_BY_STRATEGY`, `shape_requirement_for`, `shape_problem` | named by the owner; the existing one table of strategy requirements | 124 to about 240 |
| `E:src/decoy_engine/plan/checks/_column_shapes.py` (new) | `build_column_shapes(config, *, profile=None, sources)` (`sources` is a required `SourceFacts`); the second allowed caller of `classify_column` | `plan/checks/` holds the config walks the check reads (10 modules, room under the fan-out limit); `plan/` itself is frozen at 30 | about 120 |
| `E:src/decoy_engine/plan/checks/_required_settings.py` | `check_required_strategy_settings(config, *, sources, shapes=None)` walks the shape table; the `date_format` special case moves into the descriptor | the existing check; no sibling copy | 126 to about 200 |
| `E:src/decoy_engine/profile/_types.py`, `profile/_walk.py`, `profile/_source.py`, `profile/_serialize.py` | `ColumnProfile.shape` (defaulted `unknown`, in `profile_hash`); `walk_dataframe` gains `source_format` and calls `classify_column`; `profile_source` passes the format or source kind; `_column_to_dict` and `_column_from_dict` carry `shape` | every compile site already receives the profile; the serializer is hand-listed on purpose | +15, +15, +10, +8 (197 to about 205) |
| `E:src/decoy_engine/execution/_chunked_profile.py`, `execution/_chunked_oracle.py`, `execution/native/_chunked_entry.py` | `walk_one_table` passes `arrow_schema=table.schema` and the format; `empty_input_profile(config, *, table, engine_version, source_schema=None)` builds its frame from the schema; `source_schema: pa.Schema \| None = None` is added to `_mask_declared`, `_oracle_preflight` and `_oracle_preflight_admitted` and passed down from `_mask_pipeline_chunked`; the native `_run_chunked` passes `captured_schema` | the chunked compile sites and the one path between them | 303 to about 330; +8; +1 |
| `E:src/decoy_engine/execution/pipeline/_routing_facts.py` | pass `source_facts_of(caller_sources, source_loader_schemas)` as the required `sources` of `compile_plan` | the one place that holds both | 113 to about 118 |
| `E:src/decoy_engine/plan/_types.py`, `plan/_serialize.py`, `plan/_compile.py` | `Plan.column_shapes`; serialized when not empty; `PLAN_VERSION = 5`; the `plan_version` load check (F10, F11), first in `_plan_from_dict`; `compile_plan(..., sources)` (required `SourceFacts`)` builds the shapes | handlers key on the plan | +20; the shapes (de)serializer goes in `plan/_serialize_declared.py`, which holds the other optional plan block, so `_serialize.py` grows by +6 (586 to about 592) and `plan/` gains no module; +6 |
| `E:src/decoy_engine/declared_casting/_boundary.py` | `declared_date_shift_columns` becomes `typed_date_columns(plan)` | the existing seam the routes call | +10 |
| `E:src/decoy_engine/execution/_adapter.py` | rename `declared_date_columns` to `typed_date_columns` | internal context field | 0 |
| `E:src/decoy_engine/execution/_strategies/_date_shift.py` | typed output keeps the source type; backstop keys on `typed_date_columns` | the handler | 355 to about 380 |
| `E:src/decoy_engine/transforms/date_preserve.py` | `preserve_config_problem(cfg, shape)` | its one rule site | 252 to about 262 |
| `E:src/decoy_engine/transforms/bucket_perturb.py`, `execution/_strategies/_bucket_perturb.py` | E0 (built): refusal on a `None` format, `format_errors` channel, row errors. E2: remove detection, make `date_format` a required parameter, typed path | the strategy | 286 to about 280; 160 to about 185 |
| `E:src/decoy_engine/execution/native/_bucket_perturb_ext.py`, `_operator_step.py`, `_sequential_native_ops.py`, `_sequential_native.py`, `_chunked_row_errors.py`, `_chunked_entry.py`, `physical/_shadow_operators.py`, `out_of_core/_bucket_native.py` | E0 (built): positions returned and carried on `StepResult.format_error_positions`; each consumer records the `bucket_perturb` reason; out of core refuses (F9) | the native error transport | as built in #745 |
| `E:src/decoy_engine/execution/native/_capabilities.py`, `execution/_operator_registry.py`, `tests/native/test_capabilities.py` | E0 fix before merge: `bucket_perturb` gets `row_error_modes=("format_error",)` and its `OperatorSpec` gets `routed_diagnostics=frozenset({"reduce_row_error:format_error"})` together; the test's emitter set gains `bucket_perturb` | the capability facts must match the handler (section 8.1) | 581 +1; 294 +1 |
| E0b: `E:src/decoy_engine/transforms/date_preserve.py` (the shared text-date parse beside the shared sentinel helpers), `transforms/bucket_perturb.py`, `execution/_strategies/_date_shift.py`, the two native date kernels and, only if a kernel cannot compute the range, its admission entry in `execution/native/_capabilities.py` | one parse used by both date strategies; every route masks the full date range | `date_preserve.py` already holds what the two date strategies share | +40 in `date_preserve.py`; +10 at each caller |
| `E:src/decoy_engine/plan/_checks_declared_casting.py` | `strategy_output_logical`: `top_code` on `integer` gives `string`; `bucketize` on `decimal` with an integer width gives `string` for every format | F06 owns which strategies are proven for a declared column | 266 to about 280 |
| `E:src/decoy_engine/contracts/bucketize_width.py` (new, E3) | `BUCKETIZE_PRESETS` (moved from `_bucketize.py:51-59`), `resolve_bucketize_width` (moved from `_bucketize.py:146-153`) | CODEMAP "Versioned contracts" row, beside `strategy_requirements.py`; the one width rule the handler, the compile check and the shape rule share | about 40 |
| `E:src/decoy_engine/plan/_checks_bucketize.py` | calls `resolve_bucketize_width` instead of reading `preset` and `width` | the existing compile check | about -10 |
| `E:src/decoy_engine/execution/physical/_inputs.py`, `execution/physical/_snapshot.py` | `compute_plan_hash` hashes the canonical `Plan.column_shapes`; `capture_physical_plan_inputs(..., source_loader_schemas=None)` | the physical hash and its capture entry | +6; +6 |
| `E:src/decoy_engine/execution/_strategies/_bucketize.py`, `_top_code.py` | backstop through `shape_problem`; `bucketize` calls `resolve_bucketize_width` | the strategies | +10 each |
| `E:src/decoy_engine/profiling/_starter_config.py`, `_starter_inference.py`, `profiling/recommendations.py` | write `date_format` only for a text column; a typed date gets `date_shift` with no format | the one starter | 457 to about 475 |
| `E:src/decoy_engine/execution/_strategies/__init__.py` (catalog) | `StrategyInfo.shape` (family, declaration field, admitted shapes) | the public catalog the language reads | +15 |
| `E:src/decoy_engine/reasons/plan/_part3.py`, `reasons/runtime/_part3.py` | the new codes of this row (E0's two are in `runtime/_part2.py`, as built) | the registry | +15 |
| `src/decoy/lang/_grammar.py`, `_ast.py`, `_parse.py`, `_print.py`, `_convert.py`, `_codes.py`, new `src/decoy/lang/_shapes.py`; `tests/fixtures/release_freeze/lang-surface.json` | the `as <shape>` clause (section 9); the regenerated freeze fixture. `_lower.py` is 380 lines, so the lowering goes in `_shapes.py` beside `_links.py` and `_subset.py` | the language package | `_shapes.py` about 120; others +10 to +30 |
| `tests/unit/lang/test_docs_engine.py` (new, C1) | runs `run_config_only_checks` on every doc program and YAML example | `test_docs.py` stays the language-only check | about 80 |

No directory gains a module past its fan-out limit. The new engine files are in `contracts/` (8 modules, 10 after `column_shape.py` and `bucketize_width.py`) and `plan/checks/` (10 modules). No module is added to `plan/` (frozen at 30).

Consumer pairs (proportionality exception): `ColumnProfile.shape`, `Plan.column_shapes` and `build_column_shapes` land in E1a; their behaviour consumers are E1b, E2 and E3, which must merge before the row closes. `StrategyInfo.shape` lands in E5; its consumer is C2.

## 8. Slices

Engine slices first, then CLI. Each merges alone and leaves main green.

| Slice | What | Risk | After | Size (code, tests) |
|---|---|---|---|---|
| E0 | MERGED (engine #745, 2026-11-21). `bucket_perturb` safety fix (section 8.1). Before merge: the capability fix in section 8.1 | R2 (safety, output change) | none | as built: 37 files, +746, -351 |
| E0b | Out-of-range valid dates (Q12): one shared text-date parse for `date_shift` and `bucket_perturb` that parses a valid date outside the pandas nanosecond range (such as `9999-12-31`) at day precision; a perturbed or shifted date past `9999-12-31` or before `0001-01-01` is a `format_error` row error. Every supported route masks such a date: full frame, sequential, chunked, native sequential, native chunked, shadow (physical) and out of core. A native kernel computes the same output at day precision, or its admission declines the node before any data is read, so the run takes a route that masks it. A coded refusal on valid data does not meet this slice. The empty-string rule (Q13) is V2 (section 8.1) | R2 (output change, both date strategies) | E0 | about 80, 220 |
| E1a | Shape vocabulary, classifier, assembler, `ColumnProfile.shape` with Profile JSON, `Plan.column_shapes` with `PLAN_VERSION` 5 and the `plan_version` load check (F10, F11), `source_schemas` from the routing facts and both chunked entries, `ShapeRequirement` table, `check_required_strategy_settings(config, shapes)`, the classifier sentry. The table holds only `date_shift` with today's rule (every shape requires `date_format`), so no masking behaviour moves. Profile JSON gains `shape` and `profile_hash` moves once; version-4 plans need a recompile | R2 (stored formats) | 0.28.2 (released) | about 450, 450 |
| E1b | `date_shift` on typed dates: no declaration, typed output, `timestamp_naive` refused at compile, `date_format` unused warning, `preserve_values` on typed columns, backstop on `typed_date_columns` | R2 | E1a | about 200, 320 |
| E2 | `bucket_perturb`: `date_format` required on text at compile, detection removed, `date_format` becomes a required parameter of `apply_bucket_perturb`, typed date path for plan-listed columns, the no-detection import sentry | R2 (refusal) | E0, E1a | about 150, 300 |
| E3 | `bucketize` and `top_code` on text need an F06 numeric declaration; the decimal cut of section 3.2; typed mismatch; F06 proof widened for `top_code` on integer and `bucketize` on decimal; `fpe` typed rule | R2 | E1a | about 160, 340 |
| E5 | Starter and scan: shape on `FieldStats`, starter writes formats only for text, `StrategyInfo.shape`, engine docs (`strategies.md`, `compatibility-contract.md`, CHANGELOG, CODEMAP), engine release | R1 | E1b, E2, E3 | about 120, 200 |
| C0 | Roadmap row, link to this plan | R1 | none | docs |
| C1 | Repin to the release with E0 to E5; CLI docs and templates (section 11); error table; the engine-checking docs test | R1 | E5 | about 120, docs |
| C2 | Language `as <shape>` clause: grammar, lowering through `StrategyInfo.shape`, printer and converter round trip, codes, freeze fixture, guide pages | R2 (frozen language surface) | C1; DECOY-LANG S1 | about 250, 300 |
| C3 | `decoy init` and scan output: `.decoy` rules carry `as date("...")` for text sources and no `as` for typed ones, under the `?` mark; YAML init writes `date_format` only for text | R1 | C2; DECOY-LANG S6 | about 40, 150 |

E0 merges first, in the 0.28.x train. E0b follows it; it is V1-blocking (section 8.1) but does not block E1a. E2 and E3 do not depend on each other and can run in parallel after E1a. The former E4 (`windowed_date` `anchor_format`) is dropped (Q9).

### 8.1 E0 as built (engine PR #745)

Per-strategy error transport, every native mode:

- Pandas transform (`transforms/bucket_perturb.py`): with no format it raises F4 instead of returning `series.copy()`. It takes a `format_errors` list and appends the position of each non-null cell that does not parse; with no list it raises F9, so a caller with no channel cannot lose them. The cell stays as it was in the frame and the run's row-error policy decides fail or quarantine. The shared reason text is `FORMAT_ERROR_REASON` in that module.
- Pandas handler (`execution/_strategies/_bucket_perturb.py`): passes the list, rebases positions past `preserve_values` rows, and appends one `RowError(trigger="format_error")` per position.
- Native kernel (`execution/native/_bucket_perturb_ext.py`): `native_bucket_perturb` returns `(array, positions)`, rebased past preserved rows.
- Native step (`execution/native/_operator_step.py`): `StepResult.format_error_positions` now carries `bucket_perturb` positions as well as `date_shift` ones.
- Native sequential (`_sequential_native_ops.py`, `_sequential_native.py`): `bucket_row_errors` builds the records with the `bucket_perturb` reason.
- Native chunked (`_chunked_row_errors.py`, `_chunked_entry.py`): `format_error_records` takes the set of `bucket_perturb` columns and picks the reason per column. A chunked row error stops the chunk, as the oracle leg does.
- Shadow (physical) route (`physical/_shadow_operators.py`): `run_operator` picks the reason by operator id. The shadow batch runner already rebases and collects row errors for every operator.
- Out-of-core route (`out_of_core/_bucket_native.py`): no row-error channel, so any unparseable cell raises F9 before the batch is written.
- Tests: `tests/unit/strategies/test_bucket_perturb_safety.py` (section 10) plus rewritten parity, witness, chunked and shadow tests. Valid-row output did not move, checked against main with fixed inputs; no golden was re-recorded.

Still needed before #745 merges (gate finding against the as-built slice):

- `execution/native/_capabilities.py:198-211`. Yes, it still needs a change. The `bucket_perturb` entry (`_Ortho(True, False, False, False, True)`, `:209`) declares no `row_error_modes`, but the handler now appends `format_error` RowErrors. Routing still works, because the shadow batch runner collects row errors whatever the node declares and the unified-slice admission gate (`_unified_slice_admission.py:479-481`) passes an empty obligation set. But the capability facts are now false, and `tests/native/test_capabilities.py::test_row_error_strategies_are_exactly_the_five_emitters` says it is "sourced from the handlers' actual append sites". Fix: add `row_error_modes=("format_error",)` to `bucket_perturb`, add `routed_diagnostics=frozenset({"reduce_row_error:format_error"})` to the `bucket_perturb` `OperatorSpec` in `execution/_operator_registry.py` in the same commit (without it the unified slice would start to decline every `bucket_perturb` node), and add `bucket_perturb` to the test's emitter set and trigger table.
- Required before merge (Codex round 2, DESIGN; the #745 fixer is adding it): one choke point for the user-visible reason. Today three consumers choose the reason with an `if` on the strategy (`E:src/decoy_engine/execution/_sequential_native_ops.py:487`, `execution/native/_chunked_row_errors.py:23`, `execution/physical/_shadow_operators.py:425`). The fix carries the reason with the positions: a `format_error_reason` on `StepResult`, set by the step from the strategy's own `FORMAT_ERROR_REASON`, and the three consumers read it with no strategy branch. A test asserts that each of the three routes reports the `bucket_perturb` reason and the `date_shift` reason from `StepResult`, and the mutation "set the `date_shift` reason on a `bucket_perturb` step" turns it red.

Open review questions on #745, with the recommended answer:

- Q12, out-of-range valid dates (`9999-12-31`). `pd.to_datetime` coerces a date outside 1677-09-21 to 2262-04-11 to `NaT`, so after E0 a valid `9999-12-31` is a `format_error` row error and the run fails (before E0 it passed through unchanged). `date_shift` already treats it the same way (`E:src/decoy_engine/execution/_strategies/_date_shift.py:293`). Recommended: merge E0 as is, because a row error fails closed and `preserve_values: ["9999-12-31"]` keeps the cell (the docs in #745 say so). But open-ended dates such as `9999-12-31` are common in real tables, so a run that fails on valid data is a function break under the V1 bar. E0b fixes it for both date strategies on every route, and E0b is V1-blocking.
- Q13, empty strings. A non-null `""` does not parse, so after E0 it is a row error. The default CSV read turns an empty field into a null (`E:src/decoy_engine/io/bounded_reader.py:300`), so this hits empty strings from Parquet and database `varchar` columns. `date_shift` already row-errors them. Recommended: merge E0 as is, and move the empty-string rule to V2. Reason: the rule cannot be made true in one place in V1. F06 lexeme reads turn off the empty-to-null mapping and reject `""` at the cast boundary, before either strategy runs, so a strategy-level rule would cover some sources and not others. A V2 row owns it together with the F06 boundary. In V1 a `""` cell fails closed as a row error, and `error_policy: quarantine` handles dirty data.

## 9. The language side

### 9.1 What the user writes today

`date_format` is a plain option: `dob : date_shift(min_days: -30, max_days: 30, date_format: "%m/%d/%Y") in dates`. F06 fields are column fields, so `logical_type` and `parse_format` can also be written as options. But `parse_format: {id: "integer/ascii/v1"}` is noise for a CSV age column.

### 9.2 The smallest addition: `as <shape>` on a rule

```decoy-mask
dob, admitted as date("%m/%d/%Y") : date_shift(min_days: -30, max_days: 30) in dates
age as integer                    : top_code(upper: 89)
income as decimal(precision: 12, scale: 2) : bucketize(width: 10000)
```

Grammar: `mask: names [shape] ":" treatment [REVIEW_MARK]` with `shape: AS call`. `as` becomes a contextual keyword: it is a keyword only in the position after the names, so a column named `as` still works unquoted (C2 tests this). This position is a syntax error in today's grammar, so the frozen-surface rule allows it (section 6.4). The shape describes the column (the data), so it is on the column side of `:`, apart from the treatment. A `let` treatment stays free of shapes, so one `let` serves a CSV table and a Parquet table. A `group` gets no shape: shapes go on the rule's column names only.

Shapes in V1: `date("<strftime>")`, `integer`, `decimal(precision: p, scale: s)`. Nothing else.

Lowering: the compiler asks the engine catalog (`StrategyInfo.shape`) which field carries the declaration for the rule's strategy and which shapes it admits. The language keeps no list of its own. So `as decimal(...)` on `top_code` is a language error from the catalog data, and `as decimal(precision: 20, scale: 2)` on `bucketize` lowers and is then refused by the engine (F3), because the precision bound is an engine rule.

| Shape | Strategy family | YAML it compiles to |
|---|---|---|
| `date("F")` | date (`date_shift`, `bucket_perturb`) | `provider_config.date_format: "F"` |
| `integer` | numeric (`bucketize`, `top_code`) | `logical_type: integer`, `parse_format: {id: integer/ascii/v1}` |
| `decimal(precision: p, scale: s)` | numeric, `bucketize` only | `logical_type: decimal`, `parse_format: {id: decimal/plain/v1, precision: p, scale: s}` |

`date(...)` lowers to `date_format`, not to an F06 date, on purpose: `date_format` writes the shifted date back in the same text format, which is what a CSV user expects.

New language codes:

- `lang.shape_unknown`: not one of the three shapes.
- `lang.shape_not_read`: the strategy does not read the value, for example `hash` ("remove `as`; hash does not read the value").
- `lang.shape_wrong_family`: for example `as integer` on `date_shift`, or `as decimal(...)` on `top_code`.
- The existing `lang.option_repeated` when a rule has both `as date(...)` and a `date_format:` option.

All are compile-time language errors with a span. `lang.shape_unknown` and `lang.option_repeated` are pure language checks. `lang.shape_not_read` and `lang.shape_wrong_family` read `StrategyInfo.shape` from the engine catalog, the same data the lowering uses, so they need the engine package but no data and no plan.

Converter and printer: a column with `date_format` under a date strategy prints as `as date("...")`. An F06 `integer/ascii/v1` with default parameters prints as `as integer`. `decimal/plain/v1` prints as `as decimal(...)`. Every other F06 contract (grouped, currency, COBOL, sentinels, error policy, output format) prints as options, as today. The converter's round-trip proof covers each case.

YAML stays fully explicit. The engine never sees `as`; it sees only the fields in the table.

### 9.3 Scan and starter output

The starter YAML already carries `date_format` for a text date. Through the DECOY-LANG S6 converter path with review marks, that becomes:

```decoy-mask
# REVIEW: The scan detected US-format dates (%m/%d/%Y in every value). ...
dob as date("%m/%d/%Y") : date_shift(min_days: -365, max_days: 365) in dob ?
```

A typed date column gets no `as`: `dob : date_shift(min_days: -365, max_days: 365) in dob ?`. `decoy run` refuses while the `?` is there (DECOY-LANG rule 3), so a detected format never runs unconfirmed.

### 9.4 Later candidates (not in scope)

- Exact decimal `bucketize` (compute in `Decimal`, admit `decimal_wide` and non-integer widths) and fractional `top_code` (admit `decimal`). Each is a strategy output change with its own row.
- V2: an empty string `""` under a date strategy treated as absent (kept, no row error) on every source. It needs a change at the F06 boundary, which rejects `""` on lexeme reads before the strategy runs (Q13).
- Named shapes: `shape us_date = date("%m/%d/%Y")` at pipeline level, then `dob as us_date : ...`.
- A table-level shape block (`columns { dob: date("%m/%d/%Y"), age: integer }`) that also feeds `keep` columns and `windowed_date` anchors.
- Source-level type hints, `csv("a.csv", types: {...})`, that make the reader produce typed Arrow columns (typed CSV reading).
- `as` on `keep` and on link columns, which needs F06 on `passthrough` anchors.
- `as date(iso)` mapped to F06 `date/iso8601/v1`.
- An optional `windowed_date` `anchor_format` (default `iso8601`, strftime values allowed), with `as date(...)` on the anchor column.

## 10. Acceptance tests first

Each slice's tests are written before its code. "Proves" says what a red test would mean. Fixtures use marker values so the value-free checks can search messages for them.

### E0 (built in #745; the gate checks these exist and fail under the named mutations)

| Test | Proves |
|---|---|
| `E:tests/unit/strategies/test_bucket_perturb_safety.py::test_transform_refuses_when_format_resolves_to_none` | F4 at the transform itself, not only behind a handler |
| `::test_null_stays_null` | nulls are not row errors |
| `::test_unparseable_cell_is_reported_by_the_transform` | the transform records the position |
| `::test_transform_without_a_row_channel_refuses_instead_of_passing_through` | F9: a caller with no channel cannot lose a failed cell |
| `::test_handler_refuses_when_format_resolves_to_none` | the refusal reaches the handler with the code |
| `::test_unparseable_cell_is_row_error` | F7 on the pandas handler |
| `::test_explicit_format_output_unchanged` (month, quarter) and `::test_handler_clean_run_has_no_row_errors` | valid-row output does not move |
| `::test_pipeline_refuses_when_format_resolves_to_none` and `::test_pipeline_fails_on_unparseable_cell` (full frame, chunked) | the codes reach the pipeline on both routes |
| `::test_native_unparseable_cell_is_reported_like_the_oracle`, `::test_native_positions_rebase_past_preserved_rows`, `::test_native_explicit_format_output_unchanged` | native parity, including the preserve rebase |
| `::test_messages_value_free` | no marker value in a refusal or row error |
| `E:tests/physical/test_shadow_bucket_perturb.py` (rewritten), `tests/native/test_chunked_bucket_perturb_parity.py`, `tests/parity/test_phase_d_d2c_iii_bucket_seq.py`, `tests/parity/test_phase_d_d1c_ooc.py` | the shadow, chunked native, sequential native and out-of-core routes |
| `E:tests/native/test_capabilities.py::test_row_error_strategies_are_exactly_the_six_emitters` (added before merge) | the capability facts match the handler |

Mutations (recorded in #745): restore the pass-through return, and `test_transform_refuses_when_format_resolves_to_none` turns red; restore the per-cell skip with no position, and `test_unparseable_cell_is_reported_by_the_transform` turns red; drop the native positions, and `test_native_unparseable_cell_is_reported_like_the_oracle` turns red. Added before merge: drop `row_error_modes` from `bucket_perturb`, and the capability test turns red.

### E0b

| Test | Proves |
|---|---|
| `E:tests/unit/strategies/test_date_edge_cells.py::test_far_future_date_is_masked_on_every_route` (`9999-12-31` and `0001-01-02` under `%Y-%m-%d`, both date strategies, parametrised over full frame, sequential, chunked, native sequential, native chunked, shadow and out of core) | Q12: a valid date outside the nanosecond range gives masked output on every route; the test fails on a row error and on any refusal, coded or not |
| `::test_route_evidence_for_far_future_date` | where a native kernel declines, the route evidence shows the fallback route chosen before any read, and the output equals the pandas output |
| `::test_result_past_year_9999_is_row_error` | a result that cannot be written as a date is a row error, never the source value |
| `::test_empty_string_stays_row_error` | the V1 behaviour of Q13 is pinned until the V2 row changes it |
| `::test_digest_unchanged_for_in_range_dates` | in-range output bytes do not move |

Mutation: drop the day-precision parse; `test_far_future_date_is_masked_on_every_route` turns red. Second mutation: make one native kernel raise its range code instead of declining; the same test turns red on that route.

### E1a

| Test | Proves |
|---|---|
| `E:tests/unit/contracts/test_column_shape.py::test_classifier_table` (parametrised over every row of 3.1, including decimal precision 15 and 16, scale 0 and scale `-1`, for `classify_column` and `declared_shape`) | the two mapping functions give each listed shape |
| `::test_csv_is_text_even_when_reader_inferred_int` (cloud CSV path yields `int64`) | CSV stays untyped on every reader |
| `::test_unlisted_arrow_type_is_other` (`list<int>`, `struct`) | F8: no crash on an unknown type |
| `E:tests/unit/plan/test_column_shapes.py::test_config_facts_override_observed_shape` (F06 on a Parquet string column; `nested` child) | the F06 and `nested` rows win over the observed shape |
| `::test_loader_table_shape_from_loader_schema` (a `source_loader` with a `date32` schema and no descriptor) | source-loader schemas reach the shapes; the table is not `unknown` |
| `::test_zero_chunk_input_takes_source_schema_shape` (both public chunked entries with zero chunks and a `date32` schema: `run_mask_pipeline_chunked` with `source_schema`, `run_mask_chunked` with a `_FixedSchemaChunks` input) | a zero-row typed chunked input is not refused as `unknown` on either entry |
| `::test_zero_chunk_arbitrary_iterable_is_unknown` (`run_mask_chunked`, a plain empty list) | with no schema the column stays `unknown` and needs a declaration |
| `::test_observed_shape_used_directly` (a profile whose `ColumnProfile.shape` is `date`, no `source_schemas`) | the assembler uses the observed shape as a shape and does not pass it to `classify_column`; the column is `date`, not `other` |
| `::test_chunked_first_chunk_shape_matches_full_frame` (Parquet `date32`, CSV) | the chunked profile passes the schema and the source format, so both paths give the same shape |
| `::test_s3_csv_shape_is_text` (cloud reader stub that infers `int64`) | the source format reaches the classifier on the cloud path |
| `E:tests/unit/plan/test_required_settings_shapes.py::test_date_shift_rule_unchanged_on_every_shape` | E1a moves no behaviour: every shape still requires `date_format` |
| `::test_config_only_defers_unknown` | the config-only pass on a Parquet source does not refuse; the compile pass does |
| `E:tests/unit/plan/test_plan_column_shapes.py::test_plan_records_shapes_for_reading_strategies_only` | the plan lists shapes for shape-reading strategies and no others |
| `::test_plan_is_deterministic` | the same config and profile give byte-identical plans |
| `::test_plan_round_trip_keeps_column_shapes` | YAML out and back gives an equal `Plan` and an equal physical plan hash |
| `::test_plan_without_shapes_writes_no_key` | the omit-when-empty rule |
| `::test_v4_plans_need_recompile` (one version-4 fixture per family valid today: `date_shift` with `date_format`, `date_shift` on an F06 date, `bucket_perturb` with and without `date_format`, `bucketize` and `top_code` on a typed number and on CSV text, `fpe`) | each is refused at load with F11; its config compiled again gives a version-5 plan that runs, or is refused only by a section 12 freeze item |
| `::test_newer_plan_version_refused` (`plan_version: 6`) | F10 |
| `::test_malformed_plan_version_refused` (missing, `true`, `"5"`, `5.0`, `[5]`) | F10 for each; the message holds no stored value; `__cause__` and `__context__` are `None` |
| `::test_unknown_stored_shape_refused` (plan and profile) | class 6 on stored artifacts: F12 for a plan, the field-naming `ValueError` for a profile, never `other` |
| `E:tests/unit/execution/physical/test_plan_hash_shapes.py::test_hash_differs_when_only_loader_schema_differs` (two compiles of one config and profile, a loader `date32` column against a loader `string` column) | the physical plan hash covers `Plan.column_shapes` |
| `::test_hash_ignores_shape_order` | the hash part is canonical: the same shapes in another order give the same hash |
| `::test_capture_passes_loader_schemas` | `capture_physical_plan_inputs` with a loader and its schema gives the loader column its typed shape, not `unknown` |
| `E:tests/unit/profile/test_profile_shape.py::test_shape_in_profile_hash` (two profiles equal except one column's shape, `date` and `text`, both `object` dtype) | the hashes differ, so a stale profile cannot be reused for a changed source type |
| `::test_profile_round_trip_keeps_shape` | Profile JSON carries `shape`; a compile from the loaded profile equals a compile from the in-memory one |
| `::test_old_profile_json_loads_shape_unknown` | missing-field compatibility, fail closed |
| `E:tests/sentry/test_column_shape_classifier.py` | the section 6 caller list and predicate rule hold |

Mutations: drop `csv` from `TEXT_SOURCE_FORMATS`, and `test_csv_is_text_even_when_reader_inferred_int` turns red. Drop `shape` from `_column_to_dict`, and `test_profile_round_trip_keeps_shape` turns red. Stop passing `source_loader_schemas` into `source_schemas`, and `test_loader_table_shape_from_loader_schema` turns red. Drop `source_schema` in `_oracle_preflight`, and `test_zero_chunk_input_takes_source_schema_shape` turns red.

### E1b

| Test | Proves |
|---|---|
| `E:tests/unit/strategies/test_date_shift_typed.py::test_parquet_date32_runs_without_format` (full frame, sequential, chunked) | change (1): native dates need no declaration on every route |
| `::test_loader_date32_runs_without_format` | the same on a source-loader table |
| `::test_output_keeps_date32` and `::test_timestamp_tz_keeps_unit_zone_and_time` | typed in, same type out |
| `::test_typed_offset_equals_iso_text_offset` (same namespace, Parquet `2024-01-15` and CSV `"2024-01-15"`) | the digest input of a typed date is its ISO text |
| `::test_timestamp_naive_refused_at_compile` | F3 replaces the run-time `timezone_naive_datetime` |
| `::test_integer_column_refused` | F3 on a typed number |
| `::test_date_format_on_typed_date_warns_and_is_unused` | F5; output is a date, not formatted text |
| `::test_loader_table_override_mismatch_refused` (`date_format` on a loader `int64` column) | the override rule on loader tables |
| `::test_csv_without_format_still_refused` | F1 is kept for text |
| `::test_preserve_values_on_typed_date_without_format` | sentinels work on typed dates |
| `::test_handler_backstop_keys_on_plan` (a Parquet `date32` column the plan lists as typed runs with no format; the same column with the plan entry removed is refused; a text column with no format is refused) | the one backstop rule: only a plan-listed typed column skips the declaration |
| `::test_messages_value_free` | no marker value in any message |

Mutation: in `_shift_rows`, keep `shifted.astype(str)` for typed columns; `test_output_keeps_date32` turns red.

### E2

| Test | Proves |
|---|---|
| `E:tests/unit/strategies/test_bucket_perturb_shape.py::test_text_without_format_refused` (config-only and compile) | change (2): the new refusal, before any read for CSV |
| `::test_transform_does_not_detect` (calls `apply_bucket_perturb` directly with no `date_format` on clean ISO values that detection would read) | no run-time detection, at the transform, whatever the handler does |
| `::test_typed_date_runs_without_format_and_keeps_type` | the typed path for a plan-listed column |
| `::test_handler_refuses_unlisted_column` (a Parquet date column with its plan entry removed, no format) | the one backstop rule |
| `::test_native_parity_unchanged_for_explicit_format` | output bytes for today's valid configs do not move |
| the section 6 import sentry | `_detect_format` cannot be reached from `bucket_perturb` |

Mutation: restore `fmt = date_format or _detect_format(series)` in the transform; `test_transform_does_not_detect` and the import sentry turn red. The test calls the transform directly, so the handler backstop cannot hide the mutation.

### E3

| Test | Proves |
|---|---|
| `E:tests/unit/strategies/test_numeric_shape.py::test_csv_top_code_without_declaration_refused` and the `bucketize` twin | change (3) |
| `::test_csv_top_code_with_integer_declaration_runs_on_every_route` | the F06 path admits `top_code` on integers |
| `::test_csv_top_code_decimal_declaration_refused` | `top_code` refuses a decimal declaration at compile (F3), instead of failing at run time |
| `::test_parquet_decimal_under_top_code_refused` (Arrow `decimal128(10, 2)`) | the same on a typed decimal |
| `::test_csv_bucketize_decimal_declaration_range_format` (precision 12, scale 2, width 10000) | the widened F06 proof |
| `::test_bucketize_decimal_boundary_exact` (`29999.99`, `30000.00`, `9999999999999.99` with width 10000; text and `decimal128(15, 2)`) | each value lands in its true bucket at the bounds of the admitted range |
| `::test_bucketize_wide_decimal_refused` (F06 precision 16; Arrow `decimal128(20, 2)`) | F3 for `decimal_wide` |
| `::test_bucketize_decimal_non_integer_width_refused` (width `0.1`) | F3 for a width float64 cannot divide exactly |
| `::test_bucketize_negative_scale_decimal_refused` (Arrow `decimal128(15, -5)`; F06 decimal with scale `-5`) | F3 at compile, where today the run fails in the `Int64` cast |
| `::test_bucketize_decimal_width_out_of_range_refused` (width `0`, `10^15 + 1`, `2^63`) | F3 for a width outside 1 to `10^15` on a decimal column |
| `::test_bucketize_decimal_preset_runs` (parametrised over every `BUCKETIZE_PRESETS` name; Arrow `decimal128(12, 2)` and an F06 decimal declaration with precision 12, scale 2; no `width`) | presets are admitted on typed and declared decimals and give the same buckets as the equal integer `width` |
| `E:tests/unit/contracts/test_bucketize_width.py::test_one_resolution` (known preset, preset plus `width`, unknown preset, boolean, zero, negative, float `width`) | the contract gives today's effective width for each case |
| `E:tests/sentry/test_bucketize_width_contract.py` | only `contracts/bucketize_width.py` reads `provider_config` `preset` or `width` for `bucketize`; the handler, `_checks_bucketize.py` and the shape rule call `resolve_bucketize_width` |
| `::test_parquet_int_runs_without_declaration` | typed numbers need nothing |
| `::test_parquet_date_under_bucketize_refused` | F3 |
| `::test_fpe_float_refused_integer_runs_text_runs` | the `fpe` row of 3.2 |
| `::test_bad_cell_follows_error_policy_fail` | a non-numeric CSV cell under a declared column fails the run (F06 default) and never passes through |

Mutations: make the shape rule read `provider_config.width` itself, and `test_bucketize_decimal_preset_runs` and the width-contract sentry turn red. Remove `top_code` from `SHAPE_REQUIREMENTS_BY_STRATEGY`, and `test_csv_top_code_without_declaration_refused` and the catalog test turn red. Raise `EXACT_FLOAT_DECIMAL_DIGITS` to 38, and `test_bucketize_wide_decimal_refused` turns red.

### E5

| Test | Proves |
|---|---|
| `E:tests/unit/profiling/test_starter_shape.py::test_csv_date_gets_detected_format` | the starter writes the format for text |
| `::test_parquet_date_gets_no_format` | and not for typed dates |
| `::test_every_starter_config_compiles` (CSV and Parquet fixtures) | the starter never writes a config its own compiler refuses |
| `E:tests/unit/test_strategy_catalog.py::test_shape_matches_requirement_table` | the catalog and the table agree |

Mutation: make the starter write `date_format` for every date; `test_parquet_date_gets_no_format` turns red.

### C1

| Test | Proves |
|---|---|
| `tests/unit/lang/test_docs.py` (existing; `compile_text` on every program and snippet) after the cheat-sheet and guide fixes | every doc example is valid language |
| `tests/unit/lang/test_docs_engine.py::test_a_program_in_a_guide_passes_the_engine` (new; for each complete program in the guides, `run_config_only_checks(compile_text(program).config)`) | no `.decoy` doc example is refused by the engine rule. `test_docs.py` alone cannot show this: `compile_text` lowers and validates the schema but runs no engine check |
| `::test_a_yaml_example_passes_the_engine` (every fenced `yaml` block with `version: 2` under `docs/` and every template in `src/decoy/templates/`) | no YAML doc example or template is refused |
| `tests/e2e/test_column_shape_codes.py::test_codes_reach_cli_with_exit_1` | the new codes reach `validate` and `run` with the config-refusal exit |
| `tests/e2e/test_plan_command.py` (existing; the `plan_version: 4` assertions at `:80`, `:98` and `:115-116` move to 5 in the repin) | the CLI writes and reads back version-5 plans |

Mutation: remove `date_format` from one cheat-sheet CSV example; `test_a_program_in_a_guide_passes_the_engine` turns red and `test_docs.py` stays green.

### C2

| Test | Proves |
|---|---|
| `tests/unit/lang/test_shapes.py::test_as_date_lowers_to_date_format` | lowering |
| `::test_as_integer_lowers_to_f06` and `::test_as_decimal_lowers_to_f06` | lowering |
| `::test_as_on_hash_is_shape_not_read`, `::test_as_integer_on_date_shift_is_wrong_family`, `::test_as_decimal_on_top_code_is_wrong_family`, `::test_as_and_option_repeated` | the language errors, each with its span |
| `::test_lowering_reads_catalog` (monkeypatch `StrategyInfo.shape`) | the language keeps no strategy list |
| `tests/unit/lang/test_convert_roundtrip.py::test_shapes_print_and_round_trip` | the converter prints `as` and proves the program |
| `::test_column_named_as_works_unquoted` | `as` stays a contextual keyword: `as : hash` and `as as integer : top_code(upper: 89)` both parse |
| `tests/unit/lang/test_language_freeze.py` (existing) with the regenerated `lang-surface.json` | the grammar change and the three new codes are recorded; no code is removed |
| the existing twins and round-trip tests | every program that compiled before compiles to the same config |

Mutation: make `_shapes.py` lower `date(...)` to an F06 date; `test_as_date_lowers_to_date_format` and the round-trip test turn red.

### C3

| Test | Proves |
|---|---|
| `tests/e2e/test_init_shapes.py::test_csv_init_writes_as_date_under_review_mark` | detected formats are written for the user to confirm |
| `::test_parquet_init_writes_no_as` | typed sources get no declaration |
| `::test_run_refuses_until_mark_removed_then_runs` | the `?` gate holds |
| `::test_yaml_init_unchanged_for_csv` | the `--yaml` snapshot moves only for typed sources |

Mutation: write `as date(...)` for Parquet dates too; `test_parquet_init_writes_no_as` turns red.

## 11. Docs to update

- Engine: `docs/strategies.md` (the `date_shift`, `bucket_perturb`, `bucketize`, `top_code` and `fpe` sections: what each needs on text and on typed columns, the 15-digit decimal bound for `bucketize`, `top_code` on integers only, a note that `windowed_date` anchors keep the fixed ISO grammar; E0 already rewrote the `bucket_perturb` row-error text; E2 removes "detected from the column if omitted"; E0b updates the `9999-12-31` text; the empty-string text says a `""` cell is a row error in V1), `docs/compatibility-contract.md` (one pre-GA note per freeze item below), `CHANGELOG.md`, `CODEMAP.md` (contracts and `plan/checks` rows), and `docs/frozen-surfaces.md` if it lists `Plan` or Profile fields.
- CLI: `docs/guides/decoy-language/cheat-sheet.md` and `02-masking.md` (the `date_shift(min_days: -30, max_days: 30)` examples have no `date_format` and are refused on CSV today; fix them and add the `as` form), `agent-card.md`, `06-from-yaml.md`, `07-errors.md` (new codes), `docs/release/frozen-surfaces.md` (the `as` addition), the template comments in `src/decoy/templates/hipaa.yaml` and `pci.yaml` (the format is for text sources only), `CHANGELOG.md` (the language surface change), the roadmap row and the shipped log.
- Vault: the `date_shift` section of `30_Resources/Decoy-Language-to-Delivery.md`, after merge.

## 12. Compatibility and freeze

Every item lands before the 1.0 freeze. Each gets a pre-GA note in `E:docs/compatibility-contract.md`.

| Item | Kind | Slice |
|---|---|---|
| `bucket_perturb` refuses at run time when no format resolves, instead of passing the column through; unparseable cells become row errors on every route with a channel, and a refusal on the out-of-core route | new refusal and output change, safety | E0 |
| Valid dates outside the pandas range are masked on every route instead of failing, in both date strategies | output change, refusal removed | E0b |
| `date_shift` on a typed date with no `date_format` now runs | refusal removed (a success) | E1b |
| `date_shift` or `bucket_perturb` on a typed date with `date_format`: output stays a date instead of formatted text; warning added | output change | E1b, E2 |
| `date_shift` on a tz-naive timestamp is refused at compile instead of failing at run time | earlier refusal, same outcome | E1b |
| `bucket_perturb` on text with no `date_format` | new refusal (owner freeze item) | E2 |
| `bucketize` and `top_code` on text with no F06 numeric declaration | new refusal | E3 |
| `bucketize` on a decimal above 15 digits or with a non-integer width on a decimal; `top_code` on any decimal | new compile refusal (today these run with wrong buckets or fail at run time) | E3 |
| Numeric strategies on typed dates, booleans and other types | new compile refusal (today every row fails) | E3 |
| `fpe` on typed float, decimal, date and timestamp | new refusal | E3 |
| F06 admits `top_code` on integer and `bucketize` on decimal | refusal removed | E3 |
| Profile JSON gains `shape`; old profiles load as `unknown`; `profile_hash` moves once | stored format | E1a |
| `PLAN_VERSION` 5 with `column_shapes`; `pipeline_config_hash` does not move; version-4 plans need a recompile (F11); newer and malformed versions are refused (F10) | stored format, breaking before 1.0 | E1a |
| New reason codes (section 4), registered unreleased | registry | E0 to E3 |
| `StrategyInfo.shape` | public name, additive | E5 |
| Config-only `decoy validate` (`run_config_only_checks`) on a Parquet pipeline no longer refuses a missing `date_format`; `validate compile` and `run` do. Recorded in E1a's compatibility note | moved refusal | E1a |
| `.decoy` contextual keyword `as` and the shape clause, recorded in the language freeze fixture | language syntax (frozen surface, additive) | C2 |

Platform repin checklist (platform is parked): fixtures with `bucket_perturb`, `bucketize` or `top_code` on CSV, stored plans at version 4, and the disguise application path (parked row PLATFORM-DISGUISE-DATE-FORMAT).

## 13. Fold or stand alone

Stand alone. DATE-SHIFT-FORMAT shipped in 0.28.2; only its CLI repin is left. Reopening it would keep a near-done row open (closing-set rule). This row builds on that release and replaces the config-only `date_format` descriptor with the shape-aware one. DATE-SHIFT-FORMAT closes when its repin merges; COLUMN-SHAPE-RULE then owns the rule.

## 13.1 Follow-up candidates (not in this row)

- Move the pandas-dtype classifiers onto `ColumnProfile.shape`, so plan checks have one notion of column type: `_is_float_dtype` (`E:src/decoy_engine/plan/_checks_correctness.py:36`, used in the numeric lookup at `:104-113`) and `_is_integer_dtype` (`E:src/decoy_engine/plan/_checks.py:40`, used by the null-bearing check at `:209-217`). Log it as a structure-review item after this row closes.
- Carry the format-error reason with the native positions (section 8.1), if #745 does not.

## 14. Open questions (recommended answer for each)

| # | Question | Recommended |
|---|---|---|
| Q1 | The owner lists "`bucket_perturb` numeric", which the engine does not have. Add one? | No. Treat `bucket_perturb` as a date strategy. A numeric perturb is a new strategy and a 1.x candidate. |
| Q2 | "A declaration is an explicit override": should a `date_format` on a typed date column turn the output into text (today's effect), or be checked and not used? | Checked and not used, with the `column_shape_format_unused` warning. One meaning per field, and the same YAML runs on CSV and Parquet. |
| Q3 | The numeric declaration on text: F06 (`logical_type` plus `parse_format`) or a new strategy option such as `number_format`? | F06. It already has strict lexers on every route. A new option would be a second parser and a per-strategy copy. The language form `as integer` removes the YAML noise. |
| Q4 | `fpe` on typed float and decimal columns (today it encrypts `str(value)`). | Refuse with `column_shape_mismatch`. The text form of a float is a rendering choice. Typed integers keep working. |
| Q5 | `bucket_perturb` on zoned timestamps. | Refuse in V1. It formats dates only; admitting timestamps later is additive. |
| Q6 | A column made by a `derive` transform: which shape? | The Arrow type the transform produced, read after transforms. If the profile sees only pre-transform sources (the E1a builder confirms), treat derived columns as `unknown` at compile and require the declaration. |
| Q7 | F06's default `error_policy: fail` means one bad cell in a declared CSV numeric column fails the run, where `bucketize` today records a row error. Accept? | Yes. A bad cell under a declared type is a data problem the user must see. `error_policy: quarantine` exists for dirty data. Document it in `strategies.md`. |
| Q8 | One generic `column_shape_required` code, or one code per strategy like `date_shift_requires_date_format`? | Generic for the new ones; keep the shipped `date_shift` code. Fewer codes, one message per family, and the strategy name is in the path. |
| Q9 | `windowed_date` text anchors: require `anchor_format: iso8601`, or keep the fixed ISO grammar with no declaration? | Keep the fixed grammar with no declaration (review round 1). A required field with one allowed value is ceremony. A later optional `anchor_format` with default `iso8601` is additive. |
| Q10 | Language keyword `as`, or a word that cannot clash with column names? | `as`. It reads well, matches SQL `CAST(x AS type)`, it takes a place that is a syntax error today, and the language already quotes columns named after keywords. |
| Q11 | `top_code` on a typed `decimal(p, 0)` column, which holds integers and runs today. | Refuse in this row (one rule: `top_code` reads integers; cast the column). It is rare, the refusal is coded with a hint, and admitting scale-0 decimals is additive later. |
| Q12 | #745: a valid date outside the pandas range (`9999-12-31`) is now a row error. | Merge E0 as is (fail closed; `preserve_values` keeps sentinels). Fix both date strategies in E0b, which is V1-blocking: failing a run on valid data is a function break. Every route must mask it; a coded native refusal does not close it (coordinator and Codex round 2). |
| Q13 | #745: a non-null empty string is now a row error. | Merge E0 as is. The empty-string rule is V2: F06 lexeme reads reject `""` at the cast boundary before either strategy runs, so no strategy-level rule can hold on every source. In V1 a `""` cell is a row error (fail closed). |
