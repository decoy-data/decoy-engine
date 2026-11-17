Status: plan

# F07: bounded path-observation discovery, nested-path relations and JSONB coverage (roadmap row 82)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-17. Revision 1 (not yet reviewed).
Scope: engine only (the row says engine). Slices 82-E1, 82-E2a, 82-E2b, 82-E3a, 82-E3b, 82-E4 and
82-E5. CLI exposure is a follow-up row (OQ-8).

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1
and R2 tiers), `development-loop.md` (PLAN: guarantee, size, design notes, choke point, Placement,
Established solutions; Proportion), `feature-dev.md`, `api-and-compatibility.md` (versioned
formats, additive fields), `security.md` (untrusted input, value-free output), `architecture.md`
(Layout: size, fan-out, layers), `cross-cutting-concerns.md` (choke points), `testing.md` (Test
depth, full-suite triggers), `documentation.md`, `workspace-and-vcs.md` (Commit messages),
`reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `catalogs/recurring-defects.md`
(classes 1 to 11); engine `CLAUDE.md`, `CODEMAP.md` "Where Things Go" (`CODEMAP.md:235`),
`src/decoy_engine/_MAP.md`, `.importlinter`, `tests/sentry/layout/test_package_fanout.py`,
`tests/sentry/test_module_size.py`, `docs/compatibility-contract.md` (scan-set/v1 at
`docs/compatibility-contract.md:251`, required strategy settings at
`docs/compatibility-contract.md:1016`); the V1 bar (only a function break, data loss, a non-admin
value leak or cascading design blocks V1); the V1 threat model (accidental leaks only); owner
rules: CLI V1 first, no new features beyond the row, no raised caps.

Base: engine `origin/main` `3bddfc9ff` (#610). Line numbers below are from that head.

## 1. Source and what is already done

Source spec, found in this order:

1. MASTER F07 "Path-aware nested data discovery and masking" (wiki,
   `10_Projects/decoy/Market Expansion Specs/MASTER - Decoy Feature Specification.md`, section F07,
   code audit 2026-10-27: PARTIAL). Gaps it names: the bounded path-observation emitter, the
   nested-path to parent-key relation, Studio path editing, and untested JSONB handling. FRAME
   decision it asks for: the JSONPath subset, wildcard relationship rules, serialization and the
   route matrix; XML is a separately gated extension.
2. CLI roadmap row 82 (`C:docs/ROADMAP.md` section 5.3 group H) and row detail
   (`C:docs/roadmap/row-detail.md:161`): "F07 has depth, array-expansion and cell-size bounds with
   declared failure behavior; complex nested formats and XML defer."
3. COMPANION V1 and V2 scope (wiki): F07 is listed V2 there, with the V1 part "existing explicit
   JSON masking remains bounded and correct; unknown nested content cannot count as approved
   protection". The LLM Council scope note lists F07 as "V1 (reduced)". The roadmap places row 82
   in the CLI V1 track, so this plan follows the roadmap and keeps the reduced scope (OQ-1).

What exists today and is not planned again:

- The `nested` masking strategy (`src/decoy_engine/execution/_strategies/_nested.py`, 585 lines):
  one JSONPath `target` (jsonpath-ng), one child strategy, the child seed takes the outer column
  namespace (`src/decoy_engine/execution/_strategies/_nested.py:184`), a malformed cell becomes a
  `format_error` row error (`src/decoy_engine/execution/_strategies/_nested.py:325`), a target
  that matches nothing in the column fails closed
  (`src/decoy_engine/execution/_strategies/_nested.py:400`), deepest-first writeback with a
  path-overlap warning, a guard against jsonpath-ng's dict-as-list write corruption, and child
  row errors remapped to the outer row.
- Plan checks that refuse some child strategies inside `nested` (top_code, date_shift group_by,
  bucket_perturb, when) and the required-settings rows for `strategy` and `target`
  (`src/decoy_engine/contracts/strategy_requirements.py:76`).
- Route handling: `nested` is excluded from the native route
  (`src/decoy_engine/execution/native/_capabilities.py:359`), is not chunk-safe
  (`src/decoy_engine/execution/_chunked_fk_vocab.py:44`) and falls back from out-of-core
  (`src/decoy_engine/execution/out_of_core/_compat.py:124`). It runs on the full-frame and
  sequential pandas routes only.
- The Postgres snapshot primitive accepts `json` and `jsonb` columns
  (`src/decoy_engine/connectors/postgres_snapshot.py:104`) and stages them as Parquet text; one
  fidelity cell covers a small `jsonb` value (`tests/connectors/test_postgres_snapshot.py:212`).
- The STORM engine rename is merged (#329, #349): `detection/`, `profiling/` and `verification/`
  exist and `storm/` is gone. Row 16 (STORM E1) is one platform reason code, not engine structure.
  This plan treats the row's "After: STORM rename" as met (OQ-7).

Found while planning (a V1 data-loss defect in the existing strategy, fixed in 82-E1): the cell is
parsed with `json.loads` and written with `json.dumps(parsed)`
(`src/decoy_engine/execution/_strategies/_nested.py:527`). Every number in the cell, including
leaves no rule selected, goes through a Python float. Checked on the devbox with plain Python (no
tests run): `{"a":1e400,"b":1.10,"c":12345678901234567890.5,"d":1,"d":2}` comes back as
`{"a": Infinity, "b": 1.1, "c": 1.2345678901234567e+19, "d": 2}`. That is invalid JSON
(`Infinity`), a changed decimal (`1.10`), a lost large value and a silently dropped duplicate
member. Postgres `jsonb` stores numbers as `numeric`, so JSONB input hits this on real data.

The real remainder, which this plan covers:

- Bounded cell reading and a declared serialization contract for `nested` (82-E1).
- Bounded path-observation discovery in the scan, as a value-free addition to `scan-set/v1`
  (82-E2a, 82-E2b).
- Several path rules per JSON column, each with its own child strategy and identity domain
  (82-E3a, 82-E3b). Relations need this: a payload with an email and a customer id needs two rules
  with two namespaces.
- Nested-path relations: a scalar child path references a relational parent key, gets the parent's
  identity, and the pre-scan and post-scan key checks count its orphans (82-E4).
- JSONB acceptance coverage end to end on a real Postgres, and the feature doc with the route
  matrix (82-E5).

## 2. Guarantee and non-goals

### The guarantee (pinned)

1. **Serialization.** For a `nested` column, every JSON value the rules do not select keeps its
   JSON value exactly: number lexemes, strings, booleans, nulls and member order are kept. A cell
   whose numbers all round-trip through a float is written with bytes equal to today's
   `json.dumps` form; any other cell keeps its original number lexemes. Output is RFC 8259 JSON
   whenever the input was. Exact byte preservation of whitespace and escapes is not promised
   (semantic preservation only).
2. **Bounds.** A `nested` cell larger than `MASK_CELL_BYTES`, deeper than `MASK_MAX_DEPTH`, or
   holding a duplicate object member is a row error (quarantine or job failure under the job's
   existing policy), never passed through and never silently changed. Discovery reads at most the
   scan sample, `SCAN_CELL_BYTES` per cell, `SCAN_MAX_DEPTH` levels, `SCAN_ARRAY_ITEMS` items per
   array and `SCAN_MAX_PATHS` paths per column, and reports each limit it hit as a count.
3. **Value-free discovery.** The `nested` member of a `scan-set/v1` field holds counts, JSON kind
   labels, detector ids and path patterns built only from object keys that pass the key rule
   (section 4.2). No cell value, no leaf value, no failing key text and no exception text reaches
   the scan core, an error, a warning or a log line.
4. **Relations.** A rule with `references` masks its leaf with the parent column's namespace and
   strategy, so equal source keys give equal masked keys. The plan refuses a reference it cannot
   make join-safe. The pre-scan and post-scan key checks count orphans for the path end with the
   same key identity as column ends. A leaf that is missing or JSON null is a null key, not an
   orphan.
5. **Routes.** `nested` keeps today's route set (full-frame and sequential pandas; native,
   chunked and out-of-core decline or fall back with their existing reasons). This row adds no
   route.

### Non-goals

- Studio path inspection and rule editing; CLI rendering of path observations; starter-config
  suggestions for path rules; the `scan_sources(path_relations=...)` wiring in the CLI (OQ-8).
- XML and any nested format other than JSON (spec: separately gated).
- Path ends in `relationships:`. A path relation is never seen by the FK execution machinery
  (remap, subset, chunked FK, out-of-core FK); its orphan handling is report-only (OQ-5).
- Wildcard or array references (`$.items[*].customer_id`): references are RFC 9535 singular paths
  of name segments only.
- A coverage verdict that says a JSON column is "protected". Discovery reports observations and
  never counts as protection; a coverage check is follow-up F-2.
- Byte-exact splicing of masked leaves into the original text.
- Changing the jsonpath-ng grammar accepted for masking `target` today.
- Hostile inputs crafted to evade the key rule or the detectors. V1 threat model: accidental leaks
  only.
- Python dict and list cells (Parquet struct and list columns read through pandas) keep today's
  behavior, including being written back as JSON text (follow-up F-3).

## 3. Established solutions

Searches run 2026-11-17: web search "Spark JSON schema inference samplingRatio
dropFieldIfAllNull genson schema builder merge"; DuckDB `read_json` documentation (schema
detection parameters); qmd `F07 path observation`; codebase searches for `jsonpath`, `jsonb`,
`nested`, `json.loads`, `strategy_config`, `relationships`, `run_all_detectors`, `scan-set/v1`.

| Problem | Established answer | Followed here |
|---|---|---|
| Infer the structure of many JSON documents | GenSON `SchemaBuilder.add_object` merges object properties as a union over samples; Spark `spark.read.json` infers one schema from a sample (`samplingRatio`, `dropFieldIfAllNull`); DuckDB `read_json` uses `sample_size` (default 20480 objects) and `maximum_depth` | Yes: one pass over the existing scan sample, union of paths, per-path kind set (heterogeneous means more than one kind), bounded depth |
| Objects used as maps (keys are data) | DuckDB `map_inference_threshold` (default 200): a struct with more fields than the threshold is inferred as a MAP; `field_appearance_threshold` (0.1) does the same for sparse fields | Yes: a level with more than `SCAN_MAP_KEYS` distinct keys collapses to `*`. The threshold is lower (64) because a map key here is also a possible value leak |
| Arrays | GenSON and Spark merge all array items into one item schema | Yes: `[*]`, reading the first `SCAN_ARRAY_ITEMS` items |
| Path syntax | RFC 9535 (JSONPath): Normalized Paths (section 2.7) and singular queries (name and index segments only); jsonpath-ng implements the Goessner syntax `target` already uses | Discovery emits dot-form patterns that jsonpath-ng parses and that work as a `target`; references accept singular name-only paths |
| Detect PII inside JSON | Microsoft Presidio `presidio-structured` (`JsonAnalysisBuilder`) runs the analyzer per key path over leaf values and returns a key-to-entity map | Yes: the engine's own regex detectors (`src/decoy_engine/detection/detectors.py:648`) run per path over leaf strings; only detector ids leave |
| Duplicate members and number interoperability | RFC 8259 section 4 (names SHOULD be unique); RFC 7493 I-JSON (names MUST be unique; numbers beyond IEEE double are not interoperable); Python `json` hooks `object_pairs_hook`, `parse_float`, `parse_int` | Yes: duplicates are a row error; numbers are parsed into a lexeme-keeping type |
| JSONB semantics | PostgreSQL `jsonb`: keys deduplicated (last wins), key order normalized, whitespace dropped, numbers stored as `numeric` | JSONB input never carries duplicates; its numbers need the lexeme rule |
| Relation through a JSON key | dbt `relationships` test and SQL `MATCH SIMPLE`: a null child key is not an orphan; already followed in `src/decoy_engine/profiling/_scan_integrity.py:1` | Yes: a missing or null leaf is a null key |

Custom code that remains: the bounded walker (about 150 lines; no library gives value-free path
statistics with per-limit counts), the key rule, the lexeme-keeping serializer fallback (about 60
lines, used only for cells whose numbers do not round-trip; stdlib `json` cannot emit a raw number
token, and no new dependency is added), and the rule model. Each is small and specific to Decoy.

## 4. Behavior

### 4.1 Bounded cell reading and serialization (82-E1)

New private bottom-tier package `src/decoy_engine/_nested_json/` (stdlib only, plus `reasons`).

- `read_cell(text, *, max_bytes, max_depth) -> ParsedCell | CellFault`. `CellFault` is a closed
  enum: `oversized`, `malformed`, `too_deep`, `duplicate_key`. Size is the UTF-8 byte length,
  checked before parsing. Parsing uses `json.loads` with `object_pairs_hook` (refuses a repeated
  name in one object) and `parse_float` and `parse_int` returning `JsonNumber` (the numeric value
  plus its lexeme), then an iterative depth walk. A `RecursionError` or `ValueError` from the
  parser maps to `too_deep` or `malformed`, raised after the `except` block closes (class 3).
  `NaN`, `Infinity` and `-Infinity` literals keep today's behavior (accepted and written back as
  the same token; follow-up F-4).
- `ParsedCell.lossless` is true when every `JsonNumber` lexeme equals `json.dumps` of its value.
- `write_cell(cell) -> str`: for a lossless cell, `json.dumps(value)` with today's defaults (same
  bytes as today); otherwise a small serializer with the same separators and `ensure_ascii`
  escaping that writes each untouched `JsonNumber` by its lexeme. A leaf the child strategy
  replaced is written as the child's output value.
- Child strategies receive leaf values as today: `JsonNumber` leaves are handed over as plain
  `int` or `float`, so child behavior does not change.
- Constants (OQ-3): `MASK_CELL_BYTES = 16 MiB`, `MASK_MAX_DEPTH = 64`.
- `_nested.py` calls `read_cell` and `write_cell` in place of `json.loads` and `json.dumps`. Each
  fault becomes a `RowError` with trigger `format_error` and a new runtime reason code
  (`nested_cell_oversized`, `nested_cell_too_deep`, `nested_cell_duplicate_key`; `malformed`
  keeps the existing warning code). The fixed reason text names the fault, never the cell.

### 4.2 Path-observation discovery (82-E2a, 82-E2b)

82-E2a moves the persisted scan-set core models (`_Core` through `ScanSetCoreRead`,
`src/decoy_engine/profiling/scan_set.py:104` to `:228`) unchanged into
`src/decoy_engine/profiling/_scan_core.py`, and moves the importers to the new module (no
re-export left behind, per `architecture.md` Layout; `scan_set` keeps exporting the public names
it exports today because they are frozen API). `scan_set.py` (600 lines, no census entry) then has
room for the wiring without a ceiling.

82-E2b adds `src/decoy_engine/profiling/paths/`:

- **Which columns.** In each scanned table, a column qualifies when at least half of its sampled
  non-null values are `str` values that parse (under the scan bounds) to a JSON object or array,
  or Python `dict` or `list` values. Other columns get no `nested` member.
- **Walk.** For each qualifying cell, an iterative walk records per path pattern: present, JSON
  null, and the JSON kind (`string`, `integer`, `number`, `boolean`, `object`, `array`). Array
  items become `[*]`; only the first `SCAN_ARRAY_ITEMS` items of each array are walked
  (`arrays_truncated` counts the rest). Below `SCAN_MAX_DEPTH` the walk stops and counts
  `depth_truncated_cells`. When the column already has `SCAN_MAX_PATHS` patterns, new patterns are
  not added and `paths_truncated` is set.
- **Key rule (value-free path text).** An object key is written into a pattern only when it
  matches `re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key)` and the regex detectors do not hit
  the level's key set. Otherwise the segment becomes `*` and `key_suspect_collapsed` counts it. A
  level with more than `SCAN_MAP_KEYS` distinct keys across the sample becomes `*` and
  `map_collapsed` counts it. Stated limit, the same as the column-header guard: a single
  identifier-shaped key that is a value (for example a first name) and that no detector hits is
  written as a name.
- **Detection.** For each pattern, the first `SCAN_LEAF_SAMPLE` non-null scalar leaves are passed
  as strings to `run_all_detectors`, with the last named segment as the name hint (empty for `*`).
  Only `detector_id` crosses the boundary; `sample_misses` is dropped.
- **Output.** `FieldCore` gains `nested: NestedCore | None = None` (additive, strict):
  `cells_sampled`, `cells_parsed`, `cells_malformed`, `cells_oversized`, `cells_scalar`,
  `depth_truncated_cells`, `arrays_truncated`, `key_suspect_collapsed`, `map_collapsed`,
  `paths_truncated: bool`, and `paths: list[PathObservationCore]` sorted by `path`. Each
  `PathObservationCore` has `path`, `present_count`, `null_count`, `kinds` (sorted closed kind
  tokens) and `detector_hits` (sorted ids). `TableScan.nested` maps column name to the in-memory
  observation. Header-suspect tables keep writing positional column names; the paths sit under
  them.
- **Warnings.** New `warning` codes on the table: `nested_paths_truncated`,
  `nested_path_key_suspect`, `nested_cells_unreadable` (any malformed, oversized or depth count).
- **Switch.** `scan_sources(..., nested_paths: bool = True)` (OQ-4). `False` skips qualification
  and the walk.
- Constants (OQ-3): `SCAN_CELL_BYTES = 1 MiB`, `SCAN_MAX_DEPTH = 16`, `SCAN_ARRAY_ITEMS = 16`,
  `SCAN_MAX_PATHS = 256`, `SCAN_MAP_KEYS = 64`, `SCAN_LEAF_SAMPLE = 1000`.

### 4.3 Several rules per column (82-E3a, 82-E3b)

82-E3a (behavior-preserving): one function `nested_children(entry) -> tuple[NestedChild, ...]` in
`_nested_json/_rules.py` is the only reader of a nested column's child strategy and child config.
Every site that today reads `provider_config.strategy` or `strategy_config` of a `nested` column
calls it (section 6). With only the single form it returns one child, and every site behaves as
before.

82-E3b adds the list form to `nested` `provider_config`:

```yaml
- name: payload
  strategy: nested
  namespace: events_payload
  provider_config:
    rules:
      - target: $.user.email
        strategy: faker
        strategy_config: {provider: email}
      - target: $.customer_id
        strategy: hash
        namespace: customer
```

- `rules` and the single form (`target` plus `strategy`) are mutually exclusive; the required
  settings row accepts either (`nested_rules_and_target_both_set`, `nested_rules_empty`).
- Each rule may set `namespace`; absent means the column's namespace. A rule namespace must be
  declared elsewhere in the config (`nested_rule_namespace_unknown`).
- Two rules with the same target text are refused at plan time (`nested_rule_target_duplicate`).
- At run time the cell is parsed once, rules apply in declared order, and the cell is written
  once. A leaf position written by an earlier rule and matched again by a later rule fails the
  column closed (`nested_rules_overlap`, a `StrategyError` naming the column and the two rule
  indexes, never a value).
- The all-zero-match rule applies per rule: a rule that matches nothing in a column with a
  parseable cell fails closed, as the single form does today.

### 4.4 Nested-path relations (82-E4)

A rule may set `references: {table: customers, column: id}`:

- **Path shape.** The rule's `target` must be an RFC 9535 singular path of name segments only
  (`$.customer_id`, `$.ref.customer_id`); anything else is `nested_reference_path_not_singular`.
- **Identity.** The plan refuses the reference unless the parent column exists, is masked with
  `hash` or `tokenize`, the rule uses the same strategy and `strategy_config`, and the rule
  namespace equals the parent's namespace from the namespace registry
  (`src/decoy_engine/relationships/_namespace.py:119`). Codes: `nested_reference_parent_unknown`,
  `nested_reference_strategy_not_join_safe`, `nested_reference_strategy_mismatch`,
  `nested_reference_namespace_mismatch`. `fpe` is refused because its tweak is column-scoped.
- **Key type.** The source profile's type for the parent column fixes the leaf kind: an integer
  parent needs JSON integer leaves, a text parent needs JSON string leaves. A leaf of another kind,
  or an object or array, is a row error `nested_reference_leaf_type_mismatch` (fail closed). This
  stops the silent case where `42` and `"42"` canonicalize differently and hash to different
  tokens (`src/decoy_engine/generation/pool/_canonicalize.py:63`).
- **Integrity.** One function `path_relations(config) -> tuple[PathRelation, ...]` (choke point)
  derives the relations from the rules. Pre-scan: `scan_sources(..., path_relations=())` (additive
  keyword) adds one `RelationshipFacts` per relation. Post-scan: `check_keys`
  (`src/decoy_engine/verification/postmask/_keys.py:128`) reads `path_relations(config)` beside
  `relationships`. Both load the child end through `path_key_batches(batches, path)`, which
  extracts the leaf from each cell under the scan bounds and yields an Arrow key column; an
  unreadable cell is counted, never loaded. `ChildFactsCore` gains `path: str | None = None` and
  `unreadable_rows: int | None = None` (additive).
- **Execution.** Path relations are never added to `relationships`, so no FK route, subset or
  orphan remap sees them.

### 4.5 JSONB coverage and the feature doc (82-E5)

`pg_integration` acceptance cells run a real Postgres table with `jsonb` columns through the
snapshot primitive, `scan_sources` and `run_pipeline`. A new `docs/nested-json.md` states the
JSONPath subset, the serialization contract, the bounds and the route matrix.

## 5. Failure modes

| # | Failure | Behavior | Test |
|---|---|---|---|
| F1 | Unselected number changed (`1.10`, `1e400`, a big decimal) | Lexeme kept | AT-E1-1 |
| F2 | Output is not JSON (`Infinity` from overflow) | Lexeme kept, output parses | AT-E1-1 |
| F3 | Duplicate member silently dropped | Row error `nested_cell_duplicate_key` | AT-E1-3 |
| F4 | Huge cell exhausts memory | Row error before parse | AT-E1-4 |
| F5 | Deep cell, `RecursionError` text or traceback | Row error `nested_cell_too_deep`, value-free | AT-E1-5 |
| F6 | Existing golden bytes move for ordinary cells | Lossless cells use today's `json.dumps` | AT-E1-2 |
| F7 | Discovery prints a map key that is a value (an email key) | Segment `*`, counted, warning | AT-E2-3 |
| F8 | Map-shaped object explodes the path set | Collapse at `SCAN_MAP_KEYS`, path cap | AT-E2-4, AT-E2-5 |
| F9 | Detector `sample_misses` copied to output | Only ids cross the boundary | AT-E2-2 |
| F10 | Missing, null, malformed and mixed-kind paths look the same | Distinct counts and kind sets | AT-E2-6 |
| F11 | Older reader rejects a new scan record | Additive defaulted fields; read model ignores unknowns | AT-E2-7 |
| F12 | A site still reads only the single-form child, so a `rules` child skips a plan refusal | One choke point plus sentry | AT-E3a-2, AT-E3b-4 |
| F13 | Two rules mask the same leaf twice | Column fails closed | AT-E3b-2 |
| F14 | Reference masks with a different identity than the parent | Plan refusal or row error | AT-E4-1 to AT-E4-3 |
| F15 | Path relation reaches FK execution and breaks a route | Not in `relationships` by construction | AT-E4-6 |
| F16 | Pre-scan and post-scan count path keys differently | One extractor for both | AT-E4-5 |
| F17 | JSONB values round-trip differently from JSON text | JSONB acceptance cells | AT-E5-1 to AT-E5-3 |

## 6. Design notes and choke points

Design principles applied (`architecture.md`): one place per fact (bounds constants, the key rule,
the child reader, the relation list and the leaf extractor each live in one module); typed context
objects (`ParsedCell`, `NestedChild`, `PathRelation`) instead of raw dicts across modules; no flag
arguments that switch behavior (`write_cell` reads `lossless` from the parsed cell, it is not a
caller choice). Established pattern for the new foundation package: `_canonical/`
(`CODEMAP.md:269`), a private bottom-tier sub-package, chosen because the engine root is at its
fan-out cap and because the reader is shared by `execution`, `profiling` and `verification`;
placing it in `profiling/` would make `execution/_strategies/_nested.py` import the `profiling`
package init (which imports `scan_set`, which already back-imports `execution._guards`), an import
cycle risk.

Choke points:

| Rule | Enforced in | Guard test | Mutation that turns it red |
|---|---|---|---|
| Every nested cell is read with the bounds and written with the serialization contract | `_nested_json.read_cell` and `write_cell`; `_nested.py` is the only masking caller | `tests/sentry/defects/test_nested_json_choke_point.py`: no `json.loads` or `json.dumps` call in `execution/_strategies/_nested.py`; plus AT-E1-1 | put back `json.dumps(parsed)` at `_nested.py:527` |
| Every reader of a nested child goes through `nested_children` | `_nested_json/_rules.py` | `tests/sentry/defects/test_nested_child_choke_point.py` walks the syntax tree: a module that compares a strategy to the literal `"nested"` (`==`, `in (...)`, dict key) and reads `.get("strategy")`, `["strategy"]`, `.get("strategy_config")` or `["strategy_config"]` must import `nested_children`; seeded red case per shape. Plus AT-E3b-4 behavior cells | revert `plan/_checks_top_code.py:146` to `pc.get("strategy")` |
| Discovery output carries no value | `profiling/paths/_observe.py` builds `PathObservationCore` from counts, kind tokens, ids and checked segments only | AT-E2-2 canary scan of the whole core dict and caplog | write the raw key into the segment |
| Path relations are listed in one place | `_nested_json.path_relations(config)` | AT-E4-5 (pre and post scan agree) and AT-E4-6 | read references in `_keys.py` with a local loop that skips `rules` |
| Path keys are extracted in one place | `_nested_json.path_key_batches` | AT-E4-5 | load the raw JSON text as the key in `_scan_integrity._open_keys` |

The site list for the child choke point at the base: `plan/_checks_top_code.py:146`,
`plan/_checks_date_shift.py:120` and `:242`, `plan/_checks_bucket_perturb.py:70`,
`secret_providers/_requirements.py:217`, `execution/_column_access.py:179`,
`execution/_pipeline_multi_table.py:103`, and `_nested.py` itself. `plan/_checks_when.py:66` reads
no child (comment only); the sentry confirms it. Registries that name `"nested"` without reading
the child (`execution/native/_capabilities.py:359`, `execution/out_of_core/_compat.py:124`,
`execution/native/_determinism_protocol.py:84`, `validators/_leak_check.py:78`,
`contracts/distribution_behavior.py:93`, `support/_shape.py:151`) are outside the rule; the
sentry's shape list excludes them because they do not read the child.

## 7. Value-free rules

- Reason texts for every new code are fixed strings; row errors name the column and row position
  only; `StrategyError` names the column and rule indexes only.
- No new code formats an exception; faults are raised after the `except` block (class 3), and
  every new error asserts `__cause__ is None and __context__ is None`.
- Discovery writes path text only from keys that pass the key rule; `*` otherwise.
- Logs: discovery logs nothing per cell or per path; one debug line per table with counts only.
- The scan `detail=True` member stays value-bearing by contract and is not changed.

## 8. Acceptance tests (red first)

Each cell is written first and must fail on the slice base before the change. Mutations run on
the final head of each slice (class 9) and the head is recorded. No tests run on the devbox;
builders use the test VMs or the Mac.

### 82-E1 (`tests/unit/nested_json/test_read_write.py`, cells in `tests/unit/execution/test_nested_strategy.py`)

- AT-E1-1: cell `{"ssn":"123-45-6789","amt":1.10,"big":12345678901234567890.5,"e":1e400}` with
  target `$.ssn` and child `redact`: output keeps `1.10`, `12345678901234567890.5` and `1e400`
  and parses under `json.loads` with a `parse_constant` that refuses. Mutation: `write_cell`
  always calls `json.dumps`.
- AT-E1-2: 200 seeded cells with only float-exact numbers, non-ASCII keys and escaped surrogates
  give bytes equal to `json.dumps(parsed)` after masking (today's form). Mutation: use the lexeme
  serializer for every cell with compact separators.
- AT-E1-3: `{"a":1,"a":2}` gives a `format_error` row error with code
  `nested_cell_duplicate_key`; under `quarantine:` the row is quarantined and absent from main
  output; without it the job fails. Mutation: drop the `object_pairs_hook` check.
- AT-E1-4: a cell of `MASK_CELL_BYTES + 1` UTF-8 bytes built from 3-byte characters (character
  count under the limit) is `nested_cell_oversized`, and a spy proves the parser was not called;
  exactly `MASK_CELL_BYTES` passes. Mutation: measure `len(text)`.
- AT-E1-5: depth `MASK_MAX_DEPTH` passes, `+1` is `nested_cell_too_deep`; depth 5000 is
  `nested_cell_too_deep` with no traceback text. Mutation: `>` to `>=`.
- AT-E1-6: a canary value placed in a leaf, a key and a duplicate member never appears in any row
  error, warning detail, `StrategyError` text or caplog record; every new error has no
  `__cause__` or `__context__`. Mutation: add `str(exc)` to the row error reason.
- AT-E1-7: trailing whitespace is valid and trailing text (`{"a":1}x`, `{"a":1}\nx`) is
  `malformed`. Mutation: strip and cut the text at the first newline before parsing (class 1).

### 82-E2a (`tests/unit/profiling/test_scan_core_move.py`)

- AT-E2a-1: `ScanSetCore.model_json_schema()` and `ScanSetCoreRead.model_json_schema()` equal a
  snapshot taken on the base, and `decoy_engine.profiling.ScanSetCore` is the moved class.
  Mutation: rename one field in the move.

### 82-E2b (`tests/unit/profiling/paths/`)

- AT-E2-1: a column of `{"user":{"email":...},"items":[{"sku":...}]}` gives `$.user.email` with
  `detector_hits == ["email"]` and `$.items[*].sku`, with exact present and null counts. Mutation:
  keep indexes (`$.items[0].sku`).
- AT-E2-2: canary leaf values, canary keys that fail the key rule and canary `sample_misses` never
  appear in `json.dumps(scan_set_to_dict(scan, detail=False))` or caplog. Mutation: copy
  `sample_misses` into the observation.
- AT-E2-3: keys `alice@example.com`, `name\n` and `123` become `*` and are counted, and the table
  carries `nested_path_key_suspect`. Mutation: `re.match` with `$` in the key rule (class 1).
- AT-E2-4: 65 distinct keys at one level collapse to `*`; 64 keep names. Mutation: threshold off
  by one.
- AT-E2-5: one fixture per bound (path 257, array item 17 holding a new key, depth 17, cell
  `SCAN_CELL_BYTES + 1`): each sets its count or flag and the right warning. Mutations: remove
  each bound check (four mutations).
- AT-E2-6: a fixture with missing, null, malformed and mixed integer and string values at one
  path gives distinct `present_count`, `null_count`, `cells_malformed` and
  `kinds == ["integer", "string"]`. Mutation: count JSON null as missing.
- AT-E2-7: a record without `nested` validates on write and read; a record with it reads under a
  read model built without the field; strict cells refuse `present_count=True`, `"5"` and an
  unknown kind token on write (classes 2 and 4). Mutation: `kinds: list[str]`.
- AT-E2-8: a plain text column and a column with under half JSON cells get `nested=None`; two runs
  give identical bytes with sorted paths. Mutation: iterate a set unsorted.
- AT-E2-9: `nested_paths=False` gives no `nested` members and the walker spy is never called.
  Mutation: ignore the switch.

### 82-E3a (`tests/sentry/defects/test_nested_child_choke_point.py`, existing nested plan-check tests)

- AT-E3a-1: every existing nested plan-check, secret-requirement, column-access and multi-table
  test passes unchanged (characterization; no assertion edited).
- AT-E3a-2: the sentry is red on one seeded module per covered shape and green on the migrated
  head. Mutation: revert one migrated site.

### 82-E3b (`tests/unit/execution/test_nested_rules.py`, `tests/unit/plan/checks/test_nested_rules.py`)

- AT-E3b-1: two rules (email via faker, id via hash with its own namespace) mask both leaves in
  one pass; the id leaf equals a flat `hash` column under the same namespace. Mutation: use the
  column namespace for every rule.
- AT-E3b-2: overlapping rules (`$.a` and `$..a`) fail the column with `nested_rules_overlap`.
  Mutation: skip the written-position set.
- AT-E3b-3: `rules` plus `target`, empty `rules`, duplicate targets and an unknown rule namespace
  are refused with their codes in both `compile_plan` and `run_config_only_checks`. Mutation: drop
  the duplicate-target check.
- AT-E3b-4: each existing child refusal (top_code, date_shift `group_by`, bucket_perturb, `when`
  in a child) is still refused when the child sits in `rules[1]`. Mutation: `nested_children`
  returns only the first rule.
- AT-E3b-5: a rule matching nothing in a column with parseable cells fails closed per rule.
  Mutation: check zero matches across all rules together.

### 82-E4 (`tests/unit/nested_json/test_path_relations.py`, `tests/integration/test_nested_path_relations.py`)

- AT-E4-1: parent `customers.id` (hash, namespace `customer`) and a rule `$.customer_id` with
  `references` give equal masked keys for equal source keys; joining the outputs on the masked
  values returns every source match. Mutation: give the rule the column namespace.
- AT-E4-2: plan refusals for an unknown parent, `fpe`, a strategy mismatch, a namespace mismatch,
  path `$.items[*].id` and path `$..id`. Mutation: allow `fpe`.
- AT-E4-3: an integer parent with a string leaf `"42"` is `nested_reference_leaf_type_mismatch`;
  an object leaf too. Mutation: coerce the leaf with `int()`.
- AT-E4-4: a missing or JSON null leaf is a null key, not counted as orphan before or after the
  run (`MATCH SIMPLE`). Mutation: load null as the string `"null"`.
- AT-E4-5: a fixture with 3 orphan path keys gives `orphan_rows == 3` in pre-scan
  `RelationshipFacts` and the same count in the post-scan finding; an unreadable child cell is in
  `unreadable_rows` and not loaded. Mutation: one site loads the raw JSON text as the key.
- AT-E4-6: a config with a path relation compiles a plan whose `relationships` equal those of the
  same config without it, and runs on the full-frame and sequential routes with identical
  non-nested output. Mutation: append the path relation to `relationships`.
- AT-E4-7: a `scan-set/v1` record with `path` and `unreadable_rows` on a child reads back; a record
  without them reads with `None`. Mutation: make `path` required.

### 82-E5 (`tests/connectors/test_postgres_snapshot_jsonb.py`, `pg_integration`)

- AT-E5-1: a `jsonb` column holding `{"ssn": "...", "amt": 1.10, "big": 12345678901234567890.5,
  "e": 1e400}` (Postgres keeps them as `numeric`): snapshot, then `run_pipeline` with a two-rule
  `nested` column; unselected numbers come out as the text Postgres returned and the output
  parses as JSON. Mutation: revert `write_cell` to `json.dumps`.
- AT-E5-2: `scan_sources` over the staged Parquet reports the expected paths and detector ids for
  the `jsonb` column. Mutation: skip qualification for Parquet text columns.
- AT-E5-3: a `jsonb` reference to a parent table masks to the parent's identity and the post-scan
  key finding is `info`. Mutation: as AT-E4-1.
- Each cell skips cleanly without docker or `DECOY_TEST_PG_DSN` (existing marker,
  `pyproject.toml:419`); the E5 gate needs a run log from a node with Postgres where they passed.

## 9. Goldens, pins and sentries that move

- Goldens: a golden that holds a `nested` cell with a non-round-trip number changes (a bug fix).
  The builder lists each such golden by name; AT-E1-2 proves ordinary cells do not move.
- Size ceilings: none raised. `_nested.py` stays at or under 600 lines (it shrinks in 82-E1 and
  grows in 82-E3b and 82-E4; the builder reports the count per slice). `scan_set.py` drops by about
  130 lines in 82-E2a. `plan/_compile.py` (656 lines against its 666 ceiling,
  `tests/sentry/test_module_size.py:111`) takes at most 3 lines in 82-E3b; if that is not enough,
  the new check is called from an existing check function instead.
- Fan-out: `execution/_strategies` (29, frozen) gets no module. `profiling` goes from 18 to 19
  direct modules (`_scan_core.py`), under 25. The new sub-packages start well under 25.
- Layer contract: `_nested_json` joins the bottom tier of `.importlinter` and the snapshot in
  `tests/sentry/layout/test_import_layers.py`. This is a placement, not a widened allowance; no
  ignore line is added.
- Reason registry: every new code is `since=UNRELEASED`; the registry version moves at merge by the
  renumber tool.
- New sentries: the two choke-point sentries in section 6, each with seeded red cases, listed in
  the sentry registry.

## 10. Placement (checked against `CODEMAP.md:235`)

| New file | Directory | Map row | Beside |
|---|---|---|---|
| `__init__.py`, `_read.py`, `_write.py` (E1), `_rules.py` (E3a), `_paths.py` (E4) | `src/decoy_engine/_nested_json/` | Map change: new row "Nested JSON cell foundation", worded like the `_canonical/` row (`CODEMAP.md:269`); bottom layer | `src/decoy_engine/_canonical/` |
| `_scan_core.py` (E2a) | `src/decoy_engine/profiling/` | "Detectors, profiling" (`CODEMAP.md:262`) | `profiling/scan_set.py` |
| `paths/__init__.py`, `paths/_walk.py`, `paths/_observe.py` (E2b) | `src/decoy_engine/profiling/paths/` | "Detectors, profiling"; map text gains "path observation in `profiling/paths/`" | `profiling/features/` |
| `_nested_rules.py` (E3b) | `src/decoy_engine/plan/checks/` | "Plan compile and checks: new checks in `plan/checks/`" (`CODEMAP.md:251`) | `plan/checks/_relationship_keys.py` |
| `runtime/_nested_json.py` (E1), `warning/_nested_paths.py` (E2b), `plan/_nested_rules.py` (E3b) | `src/decoy_engine/reasons/` | "Reason codes" (`CODEMAP.md:265`) | `reasons/runtime/_f06.py` |
| `nested-json.md` (E5) | `docs/` | "Feature and contract docs" (`CODEMAP.md:273`) | `docs/publication.md` |
| tests | `tests/unit/nested_json/`, `tests/unit/profiling/paths/`, `tests/unit/plan/checks/`, `tests/sentry/defects/`, `tests/connectors/` | "Unit tests", "Sentry test" (`CODEMAP.md:270`, `CODEMAP.md:280`) | existing siblings |

`src/decoy_engine/_MAP.md` gains rows for `_nested_json/` and `profiling/paths/`. Present
consumers: `_read.py` and `_write.py` are used by `_nested.py` in E1; `_rules.py` by the eight
sites in E3a; `_paths.py` by `_nested.py`, `_scan_integrity.py` and `_keys.py` in E4;
`profiling/paths/` by `scan_set.py` in E2b. No module merges before its consumer.

## 11. Reuse inventory

- `jsonpath-ng` for `target` matching and writeback (unchanged), and its parsed node types
  (`Root`, `Child`, `Fields`) for the singular-path check.
- Python `json` hooks for duplicate detection and number lexemes (no new dependency).
- `run_all_detectors` (`src/decoy_engine/detection/detectors.py:648`) for leaf detection.
- The scan sample already read by `_read_and_profile` (`src/decoy_engine/profiling/scan_set.py:399`);
  no second read of the source.
- `key_facts`, `KeyBatches` and the DuckDB anti-join in `profiling/_scan_integrity.py` for path
  orphan counts; the `fk_tokens` key identity is unchanged.
- The namespace registry `for_column` (`src/decoy_engine/relationships/_namespace.py:119`) for the
  reference namespace check.
- `RowError` and the existing quarantine policy for every cell fault.
- `_relaxed` read-model derivation (moved, not copied) for the additive scan fields.
- `StrategyRequirement` rows for the `rules` form.

## 12. Frozen contracts

| Surface | Change | Rule followed |
|---|---|---|
| `scan-set/v1` (`docs/compatibility-contract.md:251`) | Additive: `FieldCore.nested`, `ChildFactsCore.path`, `ChildFactsCore.unreadable_rows`, all defaulted `None`; strict write models; read model ignores unknowns | Same precedent as SCAN-ML M3a `model_hits`; contract text, frozen-surface map row and a corpus sample in the same slice |
| `scan_sources` signature | Additive keyword-only `nested_paths=True`, `path_relations=()` | Contract section 3.1: new keyword-only parameters are additive |
| `nested` `provider_config` (`docs/compatibility-contract.md:1016`) | Additive `rules` list with per-rule `namespace` and `references`; the single form is unchanged | Required-settings text updated |
| `nested` output bytes | Change only for cells with non-round-trip numbers (bug fix) | Recorded as a pre-GA semantic change in the contract and the changelog |
| Reason registry | New codes, `since=UNRELEASED` | Renumbered at merge |
| Root facade `decoy_engine/__init__.py` (599 lines) | No change; new names are exported from `decoy_engine.profiling` | Keeps the root under its size limit |

## 13. Class table

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output in errors, logs or scan records | Fixed reason texts; observations built only from counts, kind tokens, ids and rule-checked segments; `sample_misses` dropped | AT-E1-6, AT-E2-2, AT-E2-3 | copy `str(exc)` or a raw key into output |
| 2 | Cleanup missing on an exit path | No new files or scratch; path keys use the existing protected spill dir and its cleanup in `_scan_integrity` | AT-E4-5 plus the existing spill cleanup tests | open a second DuckDB spill outside the allocator |
| 3 | State and concurrency | Reader, walker and rules are pure functions; constants are module `Final`; no cache | AT-E2-8 determinism | memoize observations in a module global |
| 4 | Route parity and silent fallback | `nested` keeps today's route set; path relations never enter `relationships`; route matrix in the doc | AT-E4-6, existing route-decline tests | append the path relation to `relationships` |
| 5 | Referential integrity | Reference identity checked at plan time (namespace, strategy) and at run time (leaf kind); one extractor for pre and post scan | AT-E4-1, AT-E4-3, AT-E4-5 | coerce `"42"` to `42` |
| 6 | Untrusted producer data | JSON cells are untrusted: byte, depth and duplicate bounds before use; key rule before any key text is written | AT-E1-3, AT-E1-4, AT-E1-5, AT-E2-5 | remove the byte check |
| 7 | Check then use (TOCTOU) | Size checked on the same in-memory text that is parsed; no re-read of the source | AT-E1-4 | re-read the cell after the size check |
| 8 | Weak tests and overclaimed evidence | Red-first cells with named mutations on the final head; JSONB cells run on a Postgres node and a skip is reported, never counted as a pass | AT-E5-1 to AT-E5-3, AT-E1-2 | assert only that output parses |
| 9 | Behavior-preserving refactor drift | 82-E2a is a pure move with a schema snapshot; 82-E3a keeps every existing assertion unchanged | AT-E2a-1, AT-E3a-1 | rename a field in the move |
| 10 | Frozen contract drift | Additive defaulted fields only; contract text, frozen-surface map row and corpus sample in the same slice | AT-E2-7, AT-E4-7, `tests/sentry/release/test_frozen_surface_map.py` | make a new field required |

Class 11 (no raised caps): nothing in this plan raises a size ceiling, fan-out allowlist,
baseline, pin or allowlist. The `.importlinter` bottom tier gains one member (placement); no
ignore line is added.

## 14. Enumerations

### Exit paths

- Cell fault (oversized, malformed, too deep, duplicate key): row error, then quarantine or job
  failure (`src/decoy_engine/execution/_strategies/_nested.py:325`).
- Rule overlap, a rule that matches nothing, an unknown child: `StrategyError`, the job fails and
  nothing is published (`src/decoy_engine/execution/_strategies/_nested.py:400`).
- Reference leaf kind mismatch: row error (new).
- Plan refusals (rules shape, reference checks): `PlanCompileError` before any read, on both the
  compile path and the config-only path (`src/decoy_engine/plan/_compile.py:477`).
- Scan: a qualifying column whose cells all fail still returns counts; a scan error keeps today's
  `ScanSourceError` (table and exception class only, `src/decoy_engine/profiling/scan_set.py:90`).

### Routes

- Full-frame pandas and sequential: `nested` runs here, today and after.
- Native: excluded (`src/decoy_engine/execution/native/_capabilities.py:359`); unchanged.
- Chunked: `nested` is not chunk-safe (`src/decoy_engine/execution/_chunked_fk_vocab.py:44`); the
  table declines as today; unchanged.
- Out-of-core: falls back (`src/decoy_engine/execution/out_of_core/_compat.py:124`); unchanged.
- Scan: one route (the scan sample frame).

### FK shapes

- Flat single-column and composite relationships: unchanged; path relations never join them.
- Path relation with a singular name path, a scalar leaf, and `hash` or `tokenize`: supported
  (82-E4).
- Path relation with an array or wildcard path, a composite parent, `fpe` or another strategy:
  refused at plan time.
- Path end as a parent: not expressible (references point from a rule to a column).
- Cross-table cycles through a path relation: no remap happens (report-only), so no cycle handling
  is involved.

### Fields

- `FieldCore.nested` (`NestedCore`: ten counts or flags and `paths`).
- `PathObservationCore`: `path`, `present_count`, `null_count`, `kinds`, `detector_hits`.
- `ChildFactsCore.path`, `ChildFactsCore.unreadable_rows`.
- `nested` provider config: `rules[].target`, `rules[].strategy`, `rules[].strategy_config`,
  `rules[].namespace`, `rules[].references.table`, `rules[].references.column`.
- `scan_sources` keywords `nested_paths` and `path_relations`.

### Output surfaces

- Masked output cells of `nested` columns (serialization contract).
- `scan-set/v1` core (value-free) and the `detail` member (unchanged, value-bearing by contract).
- Post-scan `fk_preservation` findings for path relations.
- Row errors, quarantine records, `QualityWarning`s, `StrategyError` and `PlanCompileError` texts.
- Logs: one count-only debug line per scanned table.

## 15. Slices, gates and risk

| Slice | What | Production files (max 10) | Lines (about) | Risk and gate | After |
|---|---|---|---|---|---|
| 82-E1 | `_nested_json` reader and writer, bounds, row errors in `_nested.py`, contract and CODEMAP rows | 7: `_nested_json/__init__.py`, `_read.py`, `_write.py`, `_nested.py`, `reasons/runtime/_nested_json.py`, `reasons/runtime/__init__.py`, `.importlinter` | 450 | R2 (data handling): Dennis then Codex | none |
| 82-E2a | Move the scan-set core models to `profiling/_scan_core.py`, importers moved | 3: `_scan_core.py`, `scan_set.py`, `profiling/__init__.py` | 280 (moved) | R1: Codex | none |
| 82-E2b | `profiling/paths/`, `NestedCore`, scan wiring, warning codes, contract text | 8: `paths/__init__.py`, `paths/_walk.py`, `paths/_observe.py`, `_scan_core.py`, `scan_set.py`, `profiling/__init__.py`, `reasons/warning/_nested_paths.py`, `reasons/warning/__init__.py` | 650 | R2 (value leaks): Dennis then Codex | 82-E1, 82-E2a |
| 82-E3a | `nested_children` choke point, migrate the child readers, sentry | 9: `_rules.py`, `_nested_json/__init__.py`, `_nested.py`, `plan/_checks_top_code.py`, `plan/_checks_date_shift.py`, `plan/_checks_bucket_perturb.py`, `secret_providers/_requirements.py`, `execution/_column_access.py`, `execution/_pipeline_multi_table.py` | 350 | R2 (cross-cutting refactor): Dennis then Codex | 82-E1 |
| 82-E3b | `rules` form, per-rule namespace, overlap refusal, plan checks | 8: `_rules.py`, `_nested.py`, `plan/checks/_nested_rules.py`, `plan/checks/__init__.py`, `plan/_compile.py`, `contracts/strategy_requirements.py`, `reasons/plan/_nested_rules.py`, `reasons/plan/__init__.py` | 600 | R2 (masking identity): Dennis then Codex | 82-E3a |
| 82-E4 | References, `path_relations`, `path_key_batches`, pre and post scan counts, additive child facts | 9: `_nested_json/_paths.py`, `_rules.py`, `_nested.py`, `plan/checks/_nested_rules.py`, `profiling/_scan_integrity.py`, `profiling/scan_set.py`, `profiling/_scan_core.py`, `verification/postmask/_keys.py`, `reasons/plan/_nested_rules.py` | 700 | R2 (referential integrity): Dennis then Codex | 82-E2b, 82-E3b |
| 82-E5 | JSONB `pg_integration` acceptance, `docs/nested-json.md`, changelog, roadmap note | 0 | 400 (tests and docs) | R1: Codex | 82-E4 |

Expected size in total: about 3,400 changed lines including tests. New public names:
`NestedCore`, `PathObservationCore`, `PathRelation`, `TableScan.nested`, `FieldCore.nested`, and
the `scan_sources` keywords `nested_paths` and `path_relations` (exported from
`decoy_engine.profiling`). A slice that runs well past its line budget stops and explains before
review.

Test depth per slice: T0 and T1 by the builder on a test VM or the Mac, never the devbox; T2 at
the gate on the exact head with the mutations above. Full-suite triggers: 82-E1 (layer contract is
test configuration), 82-E2a, 82-E2b and 82-E4 (serialization of a frozen contract). These run once
per merge-batch head under the merge-train rule.

## 16. Dependencies, release and repin

- 82-E1 and 82-E2a start at once (no shared file). 82-E2b after both. 82-E3a after 82-E1
  (`_nested.py`). 82-E3b after 82-E3a. 82-E4 after 82-E2b and 82-E3b. 82-E5 last.
- One writer at a time on `_nested.py` (82-E1, 82-E3a, 82-E3b, 82-E4 in that order) and on
  `profiling/scan_set.py` and `_scan_core.py` (82-E2a, 82-E2b, 82-E4).
- Each merged slice ships in the next daily engine release. No CLI repin is required for this row;
  the CLI follow-up row (OQ-8) waits for the release that carries 82-E4.

## 17. Owner questions

- **OQ-1. V1 or V2?** COMPANION puts F07 in V2; the roadmap lists row 82 in the CLI V1 track and
  the council scope says "V1 (reduced)". Recommended: build the reduced scope in this plan for V1
  (the serialization defect fixed in 82-E1 is a V1 data-loss fix either way); Studio, XML and
  wildcard relations stay V2.
- **OQ-2. Duplicate object members in JSON text.** Recommended: a row error (quarantine or fail),
  because keeping the last member silently changes data; JSONB input never has duplicates.
  Alternative: keep last-wins and add a warning.
- **OQ-3. Bounds as engine constants or config?** Recommended: constants for V1
  (`MASK_CELL_BYTES` 16 MiB, `MASK_MAX_DEPTH` 64, `SCAN_CELL_BYTES` 1 MiB, `SCAN_MAX_DEPTH` 16,
  `SCAN_ARRAY_ITEMS` 16, `SCAN_MAX_PATHS` 256, `SCAN_MAP_KEYS` 64, `SCAN_LEAF_SAMPLE` 1000),
  documented in `docs/nested-json.md`; config knobs are V2.
- **OQ-4. Discovery on by default?** Recommended: yes for qualifying columns, with
  `nested_paths=False` to switch it off; the fields are additive and bounded.
- **OQ-5. Where are nested-path relations declared?** Recommended: on the `nested` rule
  (`references`), never in `relationships:`, with report-only orphan handling (counted before and
  after the run; no remap, no subset). Path ends in `relationships:` would reach about 40
  execution modules that read relationships.
- **OQ-6. Which strategies may a reference use?** Recommended: `hash` and `tokenize`, with the same
  strategy and config as the parent; `fpe` is refused (column-scoped tweak).
- **OQ-7. Is "After: STORM rename" met?** Recommended: yes. The engine rename is merged (#329,
  #349); row 16 is one platform reason code that F07 does not touch.
- **OQ-8. CLI exposure.** Recommended: a new CLI row after the engine release that carries 82-E4:
  show path observations in `decoy scan`, pass `path_relations` from the config, and offer path
  rules in the starter config. Not part of row 82.

## 18. Pre-mortem

- The lexeme serializer differs from `json.dumps` in a corner case (a lone surrogate, a non-ASCII
  key) and moves bytes of ordinary cells. Guard: AT-E1-2 with a seeded corpus that includes both,
  and the lossless fast path for every cell whose numbers round-trip.
- The 82-E3a sentry misses a reader that uses a new spelling, and a `rules` child skips a plan
  refusal. Guard: AT-E3b-4 behavior cells for every known refusal; the sentry lists its shapes.
- Discovery is slow on wide JSON columns. Guard: all bounds apply per column; the gate records the
  scan time of the AT-E2-5 fixture; a regression goes to the known-issues list.
- A reviewer asks for wildcard references or remap. Outside the pinned guarantee; recorded as a
  follow-up, not a blocker.
- JSONB cells skip in CI because no Postgres is present, and the slice merges on skips. Guard: the
  82-E5 gate needs the `pg_integration` run log with the cells passed, from a node with docker.
- `_nested.py` grows past 600 lines across 82-E3b and 82-E4. Guard: per-slice line report; rule
  helpers live in `_nested_json/_rules.py`, not in the handler.
- The 82-E2a move breaks an importer outside the engine (CLI imports `ScanSetCoreRead`). Guard:
  the names stay exported from `decoy_engine.profiling` and `profiling.scan_set` (frozen API), and
  AT-E2a-1 pins identity.

## 19. Follow-ups (recorded, not in this row)

- F-1: CLI row (OQ-8).
- F-2: a coverage check that flags detector-hit paths no rule covers (spec: unknown nested content
  cannot count as approved protection).
- F-3: Python `dict` and `list` cells (Parquet struct and list) are written back as JSON text by
  `nested` today; decide whether to keep the Arrow type.
- F-4: `NaN` and `Infinity` literals are accepted today; decide whether to refuse them as RFC 8259
  does.
- F-5: XML, wildcard and array references, and remap for path relations (V2).

## 20. Review record

None yet.
