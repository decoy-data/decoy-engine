Status: plan

# F07: bounded path-observation discovery, nested-path relations and JSONB coverage (roadmap row 82)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-17. Revision 3 (Dennis rounds 1 and 2 applied;
see section 20).
Scope: engine only (the row says engine). Slices 82-E1a, 82-E1, 82-E2a, 82-E2b, 82-E3a, 82-E3b,
82-E4a, 82-E4b and 82-E5. CLI exposure is a follow-up row (OQ-8).

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
`docs/compatibility-contract.md:1029`); the V1 bar (only a function break, data loss, a non-admin
value leak or cascading design blocks V1); the V1 threat model (accidental leaks only); owner
rules: CLI V1 first, no new features beyond the row, no raised caps.

Base: engine `origin/main` `62353dc0b` (#630). Line numbers below are from that head; every
citation was re-checked against it in revision 4 (Codex round 1).

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

- A move-only slice that puts the handler into `execution/_strategies/nested/` (82-E1a), then
  bounded cell reading and a declared serialization contract for `nested` (82-E1).
- Bounded path-observation discovery in the scan, as a value-free addition to `scan-set/v1`
  (82-E2a, 82-E2b).
- Several path rules per JSON column, each with its own child strategy and identity domain
  (82-E3a, 82-E3b). Relations need this: a payload with an email and a customer id needs two rules
  with two namespaces.
- Nested-path relations: a scalar child path references a relational parent key, gets the parent's
  identity (82-E4a), and the pre-scan and post-scan key checks count its orphans, report-only
  (82-E4b).
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
   orphan. A declared path relation makes the post-scan gate apply on its own, so a job whose
   only relation is a path relation still gets its path-key counts and findings. Path-relation
   orphans are report-only: they never block a run or a post-scan verdict.
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

### 4.1 Handler move (82-E1a), bounded cell reading and serialization (82-E1)

**82-E1a: move only.** `_nested.py` is at 585 of 600 lines and `execution/_strategies` is frozen at
29 direct modules. 82-E1a is a `git mv` of `execution/_strategies/_nested.py` to
`execution/_strategies/nested/_handler.py` plus a new `nested/__init__.py` that exports
`NestedStrategyHandler`, and nothing else: no line of the handler changes, so every line number
in the keyed baselines stays the same. It follows the CODEMAP target "next family:
`execution/_strategies/<family>/`". The slice changes only these files, and each keyed entry is
re-keyed by path alone, with equal entry counts before and after as evidence:

- `src/decoy_engine/execution/_strategies/__init__.py:36` (registry import);
- importers: `tests/perf/test_throughput_budgets.py:26`,
  `tests/unit/execution/test_nested_strategy.py`,
  `tests/unit/execution/test_bucket_perturb_format_guard.py`,
  `tests/unit/execution/test_categorical_seeded_nondet.py`,
  `tests/unit/execution/test_faker_positional_nondet.py`,
  `tests/unit/execution/test_row_error_producers.py` (module path only);
- keyed baselines: `tests/fixtures/f29/reason-baseline.json:637` to `:644` (eight runtime
  `sources` entries) and `:835` to `:836` (the two warning entries `nested_cell_json_parse_error`
  and `nested_jsonpath_path_overlap`, whose `sources` lists name `_nested.py` beside
  `_mixed_admission.py`; only the `_nested.py` string changes, the list keeps its length and
  order), ten entries in all, `tests/fixtures/f29/producer-inventory.json:227` to `:236` (`file` field),
  `tests/sentry/baselines/f29-producer-inventory.json:599` onward (key prefix),
  `tests/sentry/baselines/gcs-call-kwargs.json:128` (key prefix),
  `tests/sentry/test_physical_seam_disconnection.py:591` (allowlisted path; the comment at `:846`
  too);
- the fan-out freeze for `execution/_strategies` lowered from 29 to 28 in both
  `tests/sentry/layout/test_package_fanout.py:34` and `tests/sentry/baselines/package-fanout.json`
  (`max`; the allowlist must match the count exactly, so this moves in the same slice; a ratchet
  moving down);
- `CODEMAP.md:253`: the freeze text becomes "fan-out freeze at 28" and the row gains the code
  span `src/decoy_engine/execution/_strategies/nested/`, which
  `test_every_subpackage_of_a_frozen_package_is_in_the_map` requires for a sub-package of a
  frozen package.

The quality ledgers in `docs/quality/` that name `_nested.py` are dated records and are not
edited. The sentries that walk source files use `rglob` (checked in `tests/sentry/defects/`,
`tests/sentry/fa/`), so the sub-package stays in their scope; the builder confirms no sentry uses a
non-recursive glob over `_strategies` and stops if one does. Later nested code goes to
`nested/_leaves.py` (82-E1) and `nested/_apply.py` (82-E3b).

**82-E1: one strict JSON reader.** `strict_json_loads` (`src/decoy_engine/_canonical/_json.py:173`)
already refuses duplicate keys with a recording hook, raises after the `except` block with a
closed token vocabulary (`STRICT_JSON_TOKENS`, `src/decoy_engine/_canonical/_json.py:155`) and is
used by `_canonical/_strict_spec.py:241`, `records/_codec.py` and the native faker admission
(`execution/native/_faker_deterministic_admission.py:154`). 82-E1 grows it instead of adding a
second reader:

- `strict_json_read(text, *, max_bytes, max_depth, non_finite, keep_lexemes, max_int_digits)` in
  `_canonical/_json.py` is the bounded mode. `strict_json_loads` becomes a call into it with its
  current defaults (`max_bytes=None`, `max_depth=None`, `non_finite="refuse"`,
  `keep_lexemes=False`, 20 digits), so its callers and tests do not change. `STRICT_JSON_TOKENS`
  gains `oversized` and `too_deep` at the end; the tokens stay the only fault names (`not_json`,
  `duplicate_key`, `non_finite`, `out_of_range`, `oversized`, `too_deep`).
- **Size.** The byte length is `len(text.encode("utf-8", "surrogatepass"))`, so the measure never
  fails. `len(text) > max_bytes` is `oversized` at once (each character is at least one byte);
  otherwise the text is encoded only when `len(text) * 4 > max_bytes`. A `bytes` input is measured
  by `len(data)` before decoding.
- **Lone surrogates, independent of size.** A raw lone surrogate in the cell text (a Python `str`
  that holds one, for example from a lax source decode) is not valid Unicode and so not RFC 8259
  text: it is `not_json`. The check runs after the size check and only on non-ASCII text, by a
  strict `text.encode("utf-8")` whose failure sets a flag and raises after the `except` block. An
  escaped `\ud800` inside a JSON string is valid JSON text: it parses, an unselected one is
  written back by the `ensure_ascii` writer as the same escape, and a selected one reaches the
  child as today. No character of the input reaches any error.
- **Depth.** An iterative walk after the parse; deeper than `max_depth` is `too_deep`. A
  `RecursionError` from the parser is `too_deep` only when `max_depth` is set; with
  `max_depth=None` (the `strict_json_loads` default) it stays `not_json`, as
  `tests/unit/canonical/test_json.py:208` pins today.
- **Numbers.** With `keep_lexemes=True`, `parse_float` and `parse_int` return `JsonNumber`, a
  frozen dataclass `JsonNumber(value: int | float | None, lexeme: str)`. The nested mode passes
  `max_int_digits=None`, so a long integer never fails the parse. An integer longer than 4300
  digits (the CPython `int` string limit) keeps `value=None` and its lexeme; it is written back
  unchanged, and only a rule that selects that leaf gives a row error with token `out_of_range`.
- **Non-finite.** `non_finite="keep"` (the nested mode and the scan mode) keeps today's behavior:
  `NaN`, `Infinity` and `-Infinity` literals are accepted and written back as the same token
  (follow-up F-4). `non_finite="refuse"` is the existing strict behavior.
- **Writer.** `strict_json_write(value)` in the same module: when every `JsonNumber` lexeme equals
  `json.dumps` of its value (the cell is lossless), it returns `json.dumps` of the plain value with
  today's defaults, so the bytes equal today's output. Otherwise a small serializer with the same
  separators and `ensure_ascii` escaping writes each `JsonNumber` by its lexeme.
- **Leaves to the child.** A matched scalar `JsonNumber` is handed to the child as its plain
  `int` or `float`. A matched object or array is deep-converted to plain Python before the child
  sees it. Leaf ordinals do not change: every matched leaf, JSON null included, keeps its place in
  the leaf column, so a positional child (seeded non-deterministic `categorical`, positional
  `faker`) keys each leaf on the same ordinal as today
  (`tests/unit/execution/test_categorical_seeded_nondet.py:318` pins that a null leaf keeps its
  ordinal, and stays unchanged).
- **Leaf column dtype.** The leaf column is built exactly as today (pandas inference over the
  leaf list) unless it holds at least one JSON null and every non-null leaf is an `int` (not
  `bool`). Only in that case it is built with `dtype=object`, so `[1, null, 3]` reaches a `hash`
  child as `1`, `None`, `3` and never as `float64` `1.0`, `NaN`, `3.0` (today the leaf frame at
  `src/decoy_engine/execution/_strategies/_nested.py:415` infers `float64`; the `hash`
  canonicalizer refuses floats, `src/decoy_engine/generation/pool/_canonicalize.py:91`). A
  null-free leaf list gets the same frame and dtype as today, so its bytes do not move, and
  `tokenize`'s dtype gate (`src/decoy_engine/execution/_strategies/_tokenize.py:175`) still
  refuses null-free integer leaves.
- **Pre-GA semantic change (int and null leaves).** For a leaf list of integers with at least one
  null, the child now sees `object` dtype instead of `float64`. Effects: `hash` and value-keyed
  children produce output instead of the float refusal; `tokenize` passes its dtype gate and
  tokenizes the integers instead of refusing; a child that writes its null input back as `NaN`
  now gives JSON `null` (see the next item). Recorded in the compatibility contract's pre-GA
  semantic change list and the changelog in 82-E1. A child output `NaN` for a non-null leaf is
  also written as JSON `null` instead of the invalid token `NaN`. The builder lists by name every
  golden or fixture that moves; the positional-child fixtures
  (`test_categorical_seeded_nondet.py:318`, `test_faker_positional_nondet.py`) use string leaves
  and must not move.
- **Child output.** A child output that is a pandas null (`None`, `NaN`, `pd.NA`) is written as
  JSON `null`. A child that returns `inf` or `-inf` gives a `mask_error` row error
  (`nested_child_non_finite`); the value is never written.
- **Constants home (OQ-3).** Every bound is a module `Final` in `_canonical/_json.py`, the bottom
  tier: `MASK_CELL_BYTES = 16 MiB`, `MASK_MAX_DEPTH = 64` (82-E1), and the scan bounds
  `SCAN_CELL_BYTES`, `SCAN_MAX_DEPTH`, `SCAN_ARRAY_ITEMS`, `SCAN_MAX_PATHS`, `SCAN_MAP_KEYS`,
  `SCAN_LEAF_SAMPLE`, `SCAN_MAX_CELLS`, `SCAN_KEY_APPEARANCE` (added in 82-E2b). The nested
  handler, `profiling/paths` and `_nested_json/_paths.py` all import them from
  `decoy_engine._canonical`; none restates a value.
- **Carrier for the fault code.** `RowError` has no code field
  (`src/decoy_engine/execution/_row_errors.py:29`), and the existing carrier for
  `nested_cell_json_parse_error` is a `QualityWarning` emitted beside the row error
  (`src/decoy_engine/execution/_strategies/_nested.py:346`). Each new fault follows that pattern
  with the same cardinality: per faulty cell, one `RowError` (trigger `format_error` or
  `mask_error`, fixed reason text that names the fault, never the cell) plus one
  `QualityWarning` with `detail={"row_pos": str(pos)}`, the same detail keys as today. Codes:
  `nested_cell_oversized`, `nested_cell_too_deep`, `nested_cell_duplicate_key`,
  `nested_cell_number_out_of_range` and `nested_child_non_finite`. `not_json` keeps
  `nested_cell_json_parse_error`. No `RowError` or `RowErrorRecord` field changes.
- **Warning-code registries.** Every new nested warning code is added in the same slice to the
  three places that list the nested codes: `execution/_mixed_admission.py:92`
  (`CHUNK_VARIANT_WARNING_CODES`), `execution/native/_capabilities.py:366` (the `nested`
  `warning_codes`) and the pin in `tests/native/test_capabilities.py:121`. This applies to 82-E1
  and to 82-E4a (`nested_reference_leaf_type_mismatch`); no other slice adds a nested warning
  code.

### 4.2 Path-observation discovery (82-E2a, 82-E2b)

82-E2a moves the persisted scan-set core models (`_Core` through `ScanSetCore`, `_relaxed` and
`ScanSetCoreRead`, `src/decoy_engine/profiling/scan_set.py:104` to `:228`) unchanged into
`src/decoy_engine/profiling/_scan_core.py`. `SCAN_SET_SCHEMA` and `PII_CANDIDATE_THRESHOLD` stay
in `scan_set.py`. No re-export is left in `scan_set.py` (`architecture.md` Layout): it imports
only the classes it uses itself, and every importer of a moved name moves to `_scan_core`:

- `src/decoy_engine/profiling/__init__.py:77` (`ScanSetCore`, `ScanSetCoreRead`);
- `src/decoy_engine/profiling/scan_set_read.py:19` (`ScanSetCoreRead`);
- `src/decoy_engine/profiling/scan_diff.py:30` (`_relaxed`);
- `tests/unit/profiling/test_scan_set.py:31` (`TableCore`);
- `tests/unit/profiling/test_scan_integrity.py:421` (`RelationshipFactsCore`);
- `tests/unit/profiling/test_scanml_m3a_record.py:26` (`ModelHitCore`, `ModelRefCore`,
  `_DetectorRunCore`).

Public names keep their public homes: `decoy_engine.profiling` and the root facade export
`ScanSetCore` and `ScanSetCoreRead` (now from `_scan_core`), which is what the frozen-surface map
lists (`docs/frozen-surfaces.md:79`, `decoy_engine.__all__`). The `scan-set/v1` row of
`docs/frozen-surfaces.md:54` names the module that defines the format; it gains
`src/decoy_engine/profiling/_scan_core.py` beside `scan_set.py`. `scan_set.py` (600 lines, no
census entry) then has room for the wiring without a ceiling.

82-E2b adds `src/decoy_engine/profiling/paths/`:

- **Which columns.** In each scanned table, a column qualifies when at least half of its first
  `SCAN_MAX_CELLS` non-null sampled values are `str` values that parse (under the scan bounds) to
  a JSON object or array, or Python `dict` or `list` values. Qualification reads only those cells,
  so it is bounded by the same cell cap as the walk. A string whose first non-whitespace character
  is not `{` or `[` is counted as `cells_scalar` without parsing. Other columns get no `nested`
  member. Parsing uses `strict_json_read` with the scan bounds, `keep_lexemes=False`,
  `non_finite="keep"` and `max_int_digits=None`. Under that mode a `NaN`, `Infinity` or
  `-Infinity` literal and an overflowing number such as `1e400` (a Python `inf`) are leaves of
  kind `number`, and the detectors see them as the strings `nan`, `inf` and `-inf`.
- **Cells cap.** At most `SCAN_MAX_CELLS` cells per column are walked, also when the scan reads
  every row (`sample_rows=None` or `strategy="full"`); this is the DuckDB `sample_size` analogue.
- **Two passes, bounded state.** The parsed trees are not kept: pass 2 parses each cell again, so
  memory holds one cell at a time, and the parse cost is at most twice the qualified cells, each
  under `SCAN_CELL_BYTES`.
  - Pass 1 tracks levels. A level is a parent pattern (the path so far, with collapses applied)
    plus the set of keys seen under it and, per key, the number of cells it appears in. Key rules
    1 and 2 (below) run in pass 1 before a key is stored: a key that fails either is counted
    under `*` at once and its text is never kept. When a level's distinct-key set passes
    `SCAN_MAP_KEYS`, the level collapses online: its key set is dropped, the level becomes `*`
    for the rest of pass 1, and keys below it are tracked under `*`. At most `SCAN_MAX_PATHS`
    levels are tracked; a key whose level would be new past that cap is counted as `*` and sets
    `paths_truncated`. So pass-1 state is at most `SCAN_MAX_PATHS * (SCAN_MAP_KEYS + 1)` keys of
    at most 64 characters.
  - At the end of pass 1, key rule 3 (appearance) is applied to every stored key.
  - Pass 2 walks again and emits paths with every collapse already applied, so the path cap is
    never spent on keys that are later collapsed.
- **Walk.** For each qualifying cell, an iterative walk records per path pattern: present, JSON
  null, and the JSON kind (`string`, `integer`, `number`, `boolean`, `object`, `array`). Array
  items become `[*]`; only the first `SCAN_ARRAY_ITEMS` items of each array are walked
  (`arrays_truncated` counts the rest). Below `SCAN_MAX_DEPTH` the walk stops and counts
  `depth_truncated_cells`. When the column already has `SCAN_MAX_PATHS` patterns, new patterns are
  not added and `paths_truncated` is set.
- **Key rule (value-free path text).** An object key is written into a pattern only when all of
  these hold:
  1. it matches `re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key)`;
  2. no regex detector hits that key (detectors run per key, and a hit on one key collapses that
     key);
  3. it appears in at least 2 cells, and in at least `SCAN_KEY_APPEARANCE` (0.1) of the cells in
     which its parent object appears (the DuckDB `field_appearance_threshold` analogue).

  Otherwise the segment becomes `*` and `key_suspect_collapsed` counts it. A level with more than
  `SCAN_MAP_KEYS` distinct keys becomes `*` and `map_collapsed` counts it. Rule 3 means keys that
  are data (a first name per cell, an id per cell) collapse even when no detector hits them.
  Stated limits: a key that is a value, repeats in at least 10% of cells, and that no detector
  hits is written as a name; and a column with a single qualifying cell collapses every key to
  `*` (rule 3 needs two cells), which `docs/nested-json.md` states.
- **Detection.** For each pattern, the first `SCAN_LEAF_SAMPLE` non-null scalar leaves are passed
  as strings to `run_all_detectors`, with the last named segment as the name hint (empty for `*`).
  Only `detector_id` crosses the boundary; `sample_misses` is dropped. Only the built-in regex
  detectors run on leaves: the model detectors that `pre_scan` adds to the column scan and
  `CustomDetectorSpec` entries are not run per path. This is recorded as V2-LOG (follow-up F-6)
  and stated in `docs/nested-json.md`.
- **Output.** `FieldCore` gains `nested: NestedCore | None = None` (additive, strict):
  `cells_sampled`, `cells_parsed`, `cells_malformed`, `cells_oversized`, `cells_scalar`,
  `depth_truncated_cells`, `arrays_truncated`, `key_suspect_collapsed`, `map_collapsed`,
  `paths_truncated: bool`, and `paths: list[PathObservationCore]` sorted by `path`. Each
  `PathObservationCore` has `path`, `present_count`, `null_count`, `kinds` (sorted closed kind
  tokens; the write model is a `Literal` list, the read model accepts any `str`, as
  `WarningRefCore` does) and `detector_hits` (sorted ids). `TableScan.nested` maps column name to
  the in-memory observation. Header-suspect tables keep writing positional column names; the paths
  sit under them.
- **Warnings.** New `warning` codes on the table: `nested_paths_truncated`,
  `nested_path_key_suspect`, `nested_cells_unreadable` (any malformed, oversized or depth count).
  These are scan warnings (`WarningRefCore`), not handler `QualityWarning`s, so the nested
  warning-code registries of section 4.1 do not change in 82-E2b.
- **Switch.** `scan_sources(..., nested_paths: bool = True)` (OQ-4). `False` skips qualification
  and the walk.
- Constants (OQ-3), defined in `_canonical/_json.py` (section 4.1): `SCAN_CELL_BYTES = 1 MiB`,
  `SCAN_MAX_DEPTH = 16`, `SCAN_ARRAY_ITEMS = 16`, `SCAN_MAX_PATHS = 256`, `SCAN_MAP_KEYS = 64`,
  `SCAN_LEAF_SAMPLE = 1000`, `SCAN_MAX_CELLS = 20480`, `SCAN_KEY_APPEARANCE = 0.1`.

### 4.3 Several rules per column (82-E3a, 82-E3b)

82-E3a (behavior-preserving): one function
`nested_children(provider_config: Mapping[str, Any]) -> tuple[NestedChild, ...]` in
`_nested_json/_rules.py` is the only reader of a nested column's child strategy and child config.
Every site that today reads `provider_config.strategy` or `strategy_config` of a `nested` column
calls it (section 6). It takes the provider-config mapping, not a column entry, because
`src/decoy_engine/execution/_pipeline_multi_table.py:103` reads the child from a seed's provider
config, not from a config column. With only the single form it returns one child, and every site
behaves as before. `NestedChild` is a frozen dataclass: `index` (`None` for the single form, `i`
for `rules[i]`), `target`, `strategy`, `strategy_config`, `namespace`, `references` (82-E4a) and
`config_path`, the prefix every refusal path uses below the column: `provider_config` for the
single form and `provider_config.rules[<i>]` for a rule. A migrated plan check builds its error
path as `tables.<t>.columns.<c>.` plus `config_path` plus the setting, so the single form keeps
today's path text exactly.

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

- `rules` and the single form (`target` plus `strategy`) are mutually exclusive
  (`nested_rules_and_target_both_set`); an empty `rules` list is `nested_rules_empty`.
- **Either form in the required-settings rows.** `StrategyRequirement`
  (`src/decoy_engine/contracts/strategy_requirements.py:29`) gains one additive field,
  `unless_present: tuple[str, ...] | None = None`; `requirement_applies` (`:106`) returns False when
  the value at that path is present. The two `nested` rows (`:76`) set
  `unless_present=("provider_config", "rules")`, so a `rules` column is not refused for a missing
  `provider_config.strategy` or `target`, and a single-form column is refused exactly as today.
  `check_required_strategy_settings` already calls `requirement_applies`, so
  `plan/checks/_required_settings.py` does not change. Each rule's own `target` and `strategy` are
  checked by `plan/checks/_nested_rules.py` with the same codes (`nested_target_unset`,
  `nested_strategy_unset`) and the rule's `config_path`.
- Each rule may set `namespace`; absent means the column's namespace. Namespaces are free names in
  the engine (the registry creates them on use), so no "unknown namespace" check is added.
- Two rules with the same target text are refused at plan time (`nested_rule_target_duplicate`).
- **Per-rule draw identity, real column for evidence.** Two rules must not share one draw. The
  draw channel today is `draw_column(ctx, column)` (`src/decoy_engine/execution/_adapter.py:499`),
  which returns `ctx.nested_outer_column or column`; `context_draw_identity` (`:506`) feeds the
  non-deterministic `shuffle` (`_shuffle.py:72`) and positional `faker` (`_faker_positional.py:49`)
  draws. 82-E3b adds a separate draw identity and keeps the real column for everything else:
  - `StrategyContext` gains `nested_draw_column: str = ""`, and `draw_column` returns
    `nested_draw_column or nested_outer_column or column`. This is the only change in
    `execution/_adapter.py`.
  - The handler leaves it empty for the single form (bytes identical to the base) and sets it to
    `<column>.rules[<i>]` around rule `i`'s child call, restoring the prior value after, as it does
    for `nested_outer_column` today.
  - `nested_outer_column` stays the real outer column for every rule. So the evidence and
    attribution keyed on it keep naming the column the operator configured: the `code_set` corpus
    record and evidence (`_code_set.py:194`, `:265`, `code_set_corpora`), the
    `date_preserve_metrics` key (`_adapter.py:296`), and the `fileaccess.at_position` text
    (`_code_set.py:197`, `_joint_mask.py:71`). No child module changes.
  - Consequence for `code_set`: its pinned corpus record is cached per (table, outer column), so
    two `code_set` rules in one column would share the first rule's corpus. A plan check refuses
    a second `code_set` rule in one nested column (`nested_rules_code_set_repeated`).
  - Consequence for `date_preserve_metrics`: two date rules in one column add their preserved
    counts under the one column key. That is a correct per-column count and is documented.
  - The native draw-site text (`execution/native/_draw_sites_mask.py:27`) stays true: `nested`
    never runs on the native route, so the new field is empty on every native-reachable call.
- **Matching before writing.** At run time the cell is parsed once. Every rule's matches are
  collected on the parsed tree before any write. Overlap is decided on structured path tuples,
  never on path text (`$.a` is not a prefix of `$.ab`): the handler's existing `_path_segments`
  gives each match a tuple of field names and indexes, and two rules overlap when one tuple equals
  another or is a strict prefix of it (an ancestor and its descendant). An overlap fails the
  column closed (`nested_rules_overlap`, a `StrategyError` naming the column and the two rule
  indexes, never a value). Then the children run, rules write in declared order, and the cell is
  written once.
- **Preflight.** The handler's `preflight()` is forwarded to every rule's child, not only the
  first, so a child that needs a preflight (for example `code_set`) works in `rules[1]`.
- The all-zero-match rule applies per rule: a rule that matches nothing in a column with a
  parseable cell fails closed, as the single form does today.

### 4.4 Nested-path relations (82-E4a references, 82-E4b integrity)

**82-E4a: references.** A rule may set `references: {table: customers, column: id}`:

- **Path shape.** The rule's `target` must be an RFC 9535 singular path of name segments only
  (`$.customer_id`, `$.ref.customer_id`); anything else is `nested_reference_path_not_singular`.
- **Identity.** The plan refuses the reference unless the parent column exists, is masked with
  `hash` or `tokenize`, the rule uses the same strategy and `strategy_config`, and the rule
  namespace equals the parent's namespace from the namespace registry
  (`src/decoy_engine/relationships/_namespace.py:119`). Codes: `nested_reference_parent_unknown`,
  `nested_reference_strategy_not_join_safe`, `nested_reference_strategy_mismatch`,
  `nested_reference_namespace_mismatch`. `fpe` is refused because its tweak is column-scoped.
- **Gated parent.** A parent column with a `when` condition is refused
  (`nested_reference_parent_conditional`): rows the condition skips keep their source key, and the
  path leaf would not match them.
- **Key kind, bound at compile.** The parent column's profiled dtype fixes the leaf kind: an
  integer parent takes JSON integer leaves (`key_kind="integer"`), a string parent takes JSON
  string leaves (`key_kind="string"`). Any other parent dtype is refused
  (`nested_reference_parent_type_unsupported`), and so is `tokenize` over an integer parent, which
  `tokenize`'s dtype gate refuses at run time anyway. The kind is resolved in `compile_plan` by a
  named function, `bind_reference_key_kinds(config, profile) -> config` in
  `plan/checks/_nested_rules.py`, which returns a copy of the config with `key_kind` written into
  each rule's `references` mapping; the seed's `provider_config` carries it from there. It sits
  in `references`, outside the child's `strategy_config`, so the child's config fingerprint and
  draws do not change. A `references.key_kind` written by the user is refused
  (`nested_reference_key_kind_reserved`). The config-only path (`run_config_only_checks`) has no
  profile: it runs every static reference check above, and the key kind is bound only by
  `compile_plan` (stated in `docs/nested-json.md`). The binding call takes at most 3 lines of
  `plan/_compile.py`. Under `compile_plan(..., no_profile=True)` the dtype is not
  trusted (the same rule `check_when_string_output_on_numeric_unsupported` follows), so a
  reference is refused with `nested_reference_requires_profile`. At run time, a rule with
  `references` but no bound `key_kind` (a hand-written plan) fails the column closed with a
  `StrategyError` carrying the same code.
- **Leaf kind at run time.** A selected leaf of another kind than `key_kind`, or an object or
  array, is a row error plus a `QualityWarning` `nested_reference_leaf_type_mismatch` (fail
  closed, the section 4.1 carrier). This stops the silent case where `42` and `"42"`
  canonicalize differently and hash to different tokens
  (`src/decoy_engine/generation/pool/_canonicalize.py:63`). The new warning code goes into the
  three nested warning-code registries (section 4.1).
- **Execution.** Path relations are never added to `relationships`, so no FK route, subset or
  orphan remap sees them.
- **Relation list and extractor (defined here, wired in 82-E4b).** 82-E4a adds the relation
  list and the path-key extractor described below (`path_relations` in `_nested_json/_rules.py`,
  `path_key_batches` in the new `_nested_json/_paths.py`) with unit cells (AT-E4a-6). Nothing
  reads them in 82-E4a: no scan, gate or finding changes, and `post_scan_gate_applies` is
  unchanged until 82-E4b wires post-scan. This keeps 82-E4b within ten production files.

**82-E4b: integrity, report-only.** One function
`path_relations(config) -> tuple[PathRelation, ...]` in `_nested_json/_rules.py` (82-E4a) derives
the relations from the rules (choke point). `PathRelation` is a frozen dataclass: parent table, parent
column, child table, child (payload) column, and `path` (the rule target). Both sides load the
child end through one extractor, `path_key_batches(batches, path, parent_type)` in
`_nested_json/_paths.py` (82-E4a): it reads the payload column, extracts the leaf under the scan bounds,
and yields an Arrow key column of the parent key column's Arrow type (integer types take JSON
integers, string types take JSON strings). An unreadable cell, and a leaf of the wrong kind for
the parent, is counted in `unreadable_rows` and never loaded, so the key column always has one
type. A missing leaf or JSON null is a null key. A parent of another Arrow type gives the key
the existing `key_type_mismatch` status, as for column ends.

- **Pre-scan.** `scan_sources(..., path_relations: Sequence[PathRelation] = ())` (additive
  keyword) passes them to `_integrity_facts` (`profiling/scan_set.py:342`) and
  `profiling/_scan_integrity.py`, whose `_open_keys` (`:242`) calls `path_key_batches` for a path
  child end. Each relation adds one `RelationshipFacts` whose child facts carry
  `ChildFactsCore.path: str | None = None` and `unreadable_rows: int | None = None` (additive, in
  `profiling/_scan_core.py`). `PathRelation` and `path_relations` are exported from
  `decoy_engine.profiling` so a caller can build the keyword from a config.
- **Post-scan key check.** In `verification/postmask/_keys.py`: the end tuple `_End` gains a path
  element, `(table, columns, path)`, with `path=None` for column ends; `check_keys` keeps its
  `relationships` argument and gains the keyword `path_relations: Sequence[PathRelation] = ()`;
  `_Run._lookup` calls `path_key_batches` for an end with a path; `key_columns(rels,
  path_relations=())` adds each path relation's parent column and payload column, so the loader
  tee keeps the payload column. `KeyResult` gains `path: str | None = None` and
  `unreadable_rows: int | None = None`; `as_dict()` writes both members only for a path row, so
  every column-relation row keeps its exact bytes.
- **Post-scan gate.** In `execution/pipeline/_post_scan.py` (583 lines): a `_path_relations()`
  method beside `_relationships()` (`:304`) returns `path_relations(self._config)`; `tee_reader`
  (`:224`) passes it to `key_columns`; `_keys` (`:395`) passes it to `check_keys` and returns
  early only when both lists are empty; `note_quarantined` (`:286`) also records the parent end of
  each path relation; `_decide` (`:206`) writes column-relation rows to `report["keys"]` as today
  and path rows to a new member `report["path_keys"]`, present only when the config has a path
  relation. The file must stay at or under 600 lines with no census entry; if the change does not
  fit, the merge of declared ends moves into `_keys.py`. On a route where the gate is deferred,
  path keys get no check, the same as column keys today (`_post_scan.py:264`).
- **Gate applies for a path relation.** `post_scan_gate_applies`
  (`src/decoy_engine/config/_post_scan.py:139`, 221 lines) gains a third reason, read through the
  one choke point: `bool(config.get("relationships")) or post_scan_integrity_requested(config) or
  bool(path_relations(config))`. The import is lazy inside the function (`config` sits above the
  bottom tier, so `config` to `_nested_json` is a downward import and needs no ignore line). It
  changes in 82-E4b, the slice that wires post-scan, so the gate never applies before it can
  count path keys. Every caller already asks this one function: the gate's `required` flag
  (`execution/pipeline/_post_scan.py:106`), the source-fact capture in `bind_gate` (`:501`) and
  the lazy-input choice (`execution/pipeline/_lazy_input.py:95`). A job whose only relation is a
  path relation therefore runs the gate the way a job with only a declared relationship does
  today: source facts are captured, a lazy transform-bearing mask table is kept off the lazy set,
  and the report carries `keys` (empty) and `path_keys`. The suite still runs only with
  `post_scan.integrity` on, so the integrity refusal for transformed tables (`_post_scan.py:327`)
  does not reach a path-only job.
- **Report-only under a gate that applies only for a path relation.** Path rows and path
  findings never block (next bullets). The existing gate faults keep their behaviour for every
  gate that applies: a required gate that never ran when the route ends, and a failure outside
  the per-end catch of `check_keys` (`verification/postmask/_keys.py:175`, which turns any error
  of one end into that end's `error` row, so a path end that fails becomes a capped path row).
  These are wiring faults, not findings, and fail closed as they do for a relationship-only job. The leaf type logic stays in
  `_nested_json/_paths.py`, outside the `post-scan-key-core` sentry's scope
  (`tests/sentry/post_scan/_scan.py:187`), so `_keys.py` and `_post_scan.py` add no type compare
  and no baseline entry there.
- **Findings.** In `verification/postmask/fk_preservation.py`, `fk_findings` (`:27`) reads
  `path_relations(config)` beside `relationships`; `_frame_keys` passes them to `key_columns` and
  `check_keys`, so `run_post_mask` over pandas frames counts them too; `by_end` is keyed by
  `(table, columns, path)`. `FKPreservationFinding` (`verification/postmask/types.py:76`) gains
  `path: str | None = None` (additive, last field); `asdict` writes it in every
  `fk_preservation` finding, `null` for column relations, as SCAN-ML M4 did for `residual_pii`.
- **Report-only, never blocks (OQ-5).** A path relation's finding is capped at `warning`: where a
  column relation would get `fail` (orphans introduced) or `error` (not checked), the path
  finding gets `warning` with a fixed message that says the relation is report-only. The verdict
  (`verification/postmask/_blocked.py:224`) reads `keys`, `fk_preservation`, `residual_pii` and
  `policy_validation`; it never reads `path_keys`, and a `warning` finding never blocks, so
  `_blocked.py` does not change. AT-E4b-4 proves a run whose path relation has introduced orphans
  is not blocked.
- **Contract text.** `post-scan-integrity/v3` (`docs/compatibility-contract.md:295`) gains, as
  additive members only: `fk_preservation[].path` (`null` for column relations), and the report
  member `path_keys`, present only when the config declares a path relation, whose rows have the
  `keys` row shape plus `path` and `unreadable_rows`. The tag stays `v3`.

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
| F14 | Reference masks with a different identity than the parent | Plan refusal or row error | AT-E4a-1 to AT-E4a-4 |
| F15 | Path relation reaches FK execution and breaks a route | Not in `relationships` by construction | AT-E4a-5 |
| F16 | Pre-scan and post-scan count path keys differently | One extractor for both | AT-E4b-2 |
| F17 | JSONB values round-trip differently from JSON text | JSONB acceptance cells | AT-E5-1 to AT-E5-3 |
| F18 | Mixed integer and null leaves become `float64`, so `hash` keys change and `NaN` or `3.0` is written | Object dtype only for integer leaves with a null; nulls keep their ordinal; pandas-null output written as JSON `null` | AT-E1-8, AT-E4a-1 |
| F19 | Two rules share one draw or one `code_set` corpus | Separate per-rule draw identity; second `code_set` rule refused | AT-E3b-6, AT-E3b-7 |
| F20 | Keys that are data (names, ids) appear in path text | Per-key detectors and the appearance rule | AT-E2-10 |
| F21 | Child returns `inf` or `nan` and the cell is no longer JSON | `inf` is a `mask_error` row error and nothing is written; `nan` is JSON `null` | AT-E1-9 |
| F22 | The leaf-column change moves output of null-free leaves, or shifts positional ordinals | Null-free leaves keep today's frame; null leaves keep their ordinal | AT-E1-13 |
| F23 | A new nested warning code is missing from a registry, so a route admits or declines wrongly | Codes added to all three registries in the same slice | AT-E1-14, AT-E4a-3 |
| F24 | Pass 1 holds every distinct key of a map-of-maps column | Online collapse, key rules 1 and 2 before storing, tracked-level cap | AT-E2-12 |
| F25 | The post-scan gate never counts path keys (wired at a site that does not read config) | `_post_scan.py` and `fk_preservation.py` call `path_relations(config)` | AT-E4b-3, AT-E4b-7 |
| F29 | A job whose only relation is a path relation runs no gate, so no path-key counts exist | `post_scan_gate_applies` reads `path_relations(config)` | AT-E4b-8 |
| F26 | A path-relation orphan blocks a run | Finding capped at `warning`; path rows in `path_keys`, which the verdict does not read | AT-E4b-4 |
| F27 | Rules `$.a` and `$.ab` reported as overlapping | Overlap on structured path tuples | AT-E3b-2 |
| F28 | The handler move changes a keyed baseline entry count or a line | Move only, re-key by path, equal counts | AT-E1a-1 |

## 6. Design notes and choke points

Design principles applied (`architecture.md`): one place per fact (bounds constants, the key rule,
the child reader, the relation list and the leaf extractor each live in one module); typed context
objects (`ParsedCell`, `NestedChild`, `PathRelation`) instead of raw dicts across modules; no flag
arguments that switch behavior (`strict_json_write` reads losslessness from the values, it is not a
caller choice). One strict JSON reader: the bounded mode grows `_canonical/_json.py`, it does not
copy it. The rule model and the path-key extractor go in a new private bottom-tier package
`_nested_json/`, following the `_canonical/` precedent (`CODEMAP.md:269`): the engine root is at
its fan-out cap, and the code is shared by `plan`, `secret_providers`, `execution`, `profiling`
and `verification`. Placing it in `profiling/` would make the nested handler import the
`profiling` package init (which imports `scan_set`, which already back-imports
`execution._guards`), an import cycle risk.

Allowed dependencies per package (import-linter enforces the internal ones):

| Package | May import |
|---|---|
| `_canonical` | stdlib, `reasons`, `_error_base` (unchanged; `_canonical/_json.py:32`) |
| `_nested_json` | stdlib, `_canonical`, `reasons`, `jsonpath_ng` (`_rules.py`, singular-path check), `pyarrow` (`_paths.py` only) |
| `profiling/paths` | stdlib, `_canonical`, `detection`, `reasons` |
| `execution/_strategies/nested` | what `_nested.py` imports today, plus `_canonical` and `_nested_json` |

Choke points:

| Rule | Enforced in | Guard test | Mutation that turns it red |
|---|---|---|---|
| Every JSON cell is read by the one strict reader and nested cells are written with the serialization contract | `_canonical.strict_json_read` and `strict_json_write`; the nested sub-package and `profiling/paths` are the callers | `tests/sentry/defects/test_nested_json_choke_point.py`: no `json.loads` or `json.dumps` call in `execution/_strategies/nested/`, `_nested_json/` or `profiling/paths/`; plus AT-E1-1 | put back `json.dumps(parsed)` in `nested/_leaves.py` |
| Every reader of a nested child goes through `nested_children` | `_nested_json/_rules.py` | `tests/sentry/defects/test_nested_child_choke_point.py` walks the syntax tree: a module that compares a strategy to the literal `"nested"` (`==`, `in (...)`, dict key) and reads `.get("strategy")`, `["strategy"]`, `.get("strategy_config")` or `["strategy_config"]` must import `nested_children`; seeded red case per shape. Plus AT-E3b-4 behavior cells | revert `plan/_checks_top_code.py:146` to `pc.get("strategy")` |
| Discovery output carries no value | `profiling/paths/_observe.py` builds `PathObservationCore` from counts, kind tokens, ids and checked segments only | AT-E2-2 canary scan of the whole core dict and caplog | write the raw key into the segment |
| Path relations are listed in one place | `_nested_json.path_relations(config)`, called by the four modules that read the config for relations: `profiling/scan_set.py` (through the `scan_sources` keyword), `config/_post_scan.py` (`post_scan_gate_applies`), `execution/pipeline/_post_scan.py` and `verification/postmask/fk_preservation.py` | AT-E4b-2 (pre and post scan agree), AT-E4b-3 (gate, through `run_pipeline`), AT-E4b-7 (`run_post_mask` over frames), AT-E4b-8 (gate applies for a path relation alone), AT-E4a-5, AT-E4a-6 | in `_post_scan._PostScanGate._keys`, pass `path_relations=()` instead of `self._path_relations()`; second mutation: drop `path_relations(config)` from `fk_findings`; third mutation: `post_scan_gate_applies` ignores path relations |
| Path keys are extracted in one place | `_nested_json.path_key_batches`, called by `_scan_integrity._open_keys` and `_keys._Run._lookup` | AT-E4b-2 | load the raw JSON text as the key in `_keys._Run._lookup` |

The site list for the child choke point at the base: `plan/_checks_top_code.py:146`,
`plan/_checks_date_shift.py:120` and `:242`, `plan/_checks_bucket_perturb.py:70`,
`secret_providers/_requirements.py:217`, `execution/_column_access.py:179`,
`execution/_pipeline_multi_table.py:103`, and the nested handler itself. `plan/_checks_when.py:66` reads
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

### 82-E1a (no new test file; existing suites)

- AT-E1a-1: after the move, every existing test passes with only its import path edited (no
  assertion edited); `git diff -M --stat` shows `_nested.py` renamed to `nested/_handler.py` at
  100% similarity; each re-keyed baseline file has the same entry count as the base and differs
  from the base only in the path text (checked by a diff of the files with the path substituted
  back); in `reason-baseline.json` the ten entries that name `_nested.py` at the base (`:637` to
  `:644` and the warning entries at `:835` and `:836`) name `nested/_handler.py` after, and the
  count of entries naming either path is 10 before and after; the fan-out sentry and the CODEMAP
  sub-package check pass at 28. Mutation: leave one `reason-baseline.json` `sources` entry on the
  old path, once for a runtime entry and once for a warning entry (the F29 baseline test goes
  red each time).

### 82-E1 (`tests/unit/canonical/test_strict_json_read.py`, cells in `tests/unit/execution/test_nested_strategy.py`)

- AT-E1-1: cell `{"ssn":"123-45-6789","amt":1.10,"big":12345678901234567890.5,"e":1e400}` with
  target `$.ssn` and child `redact`: output keeps `1.10`, `12345678901234567890.5` and `1e400`
  and parses under `json.loads` with a `parse_constant` that refuses. Mutation:
  `strict_json_write` always calls `json.dumps`.
- AT-E1-2: 200 seeded cells with only float-exact numbers, non-ASCII keys and escaped surrogates
  give bytes equal to `json.dumps(parsed)` after masking (today's form). Mutation: use the lexeme
  serializer for every cell with compact separators.
- AT-E1-3: `{"a":1,"a":2}` gives one `RowError` with trigger `format_error` for that row and one
  `QualityWarning` with code `nested_cell_duplicate_key` and `detail == {"row_pos": "<pos>"}`;
  two faulty cells give two warnings; under `quarantine:` the row is quarantined and absent from
  main output; without it the job fails. Mutation: drop the duplicate check in the pairs hook.
- AT-E1-4: a cell of `MASK_CELL_BYTES + 1` UTF-8 bytes built from 3-byte characters (character
  count under the limit) is `nested_cell_oversized`, and a spy proves the parser was not called;
  exactly `MASK_CELL_BYTES` passes; a text holding a raw lone surrogate and over the limit is
  `oversized` (the measure does not raise). Mutation: measure `len(text)`.
- AT-E1-5: depth `MASK_MAX_DEPTH` passes, `+1` is `nested_cell_too_deep`; depth 5000 under the
  nested mode is `nested_cell_too_deep` with no traceback text; `strict_json_loads` on depth
  100000 still gives token `not_json` (`tests/unit/canonical/test_json.py:208` unchanged).
  Mutations: `>` to `>=`; map `RecursionError` to `too_deep` without checking `max_depth`.
- AT-E1-6: a canary value placed in a leaf, a key and a duplicate member never appears in any row
  error, warning detail, `StrategyError` text or caplog record; every new error has no
  `__cause__` or `__context__`. Mutation: add `str(exc)` to the row error reason.
- AT-E1-7: trailing whitespace is valid and trailing text (`{"a":1}x`, `{"a":1}\nx`) is
  `not_json`. Mutation: strip and cut the text at the first newline before parsing (class 1).
- AT-E1-8: a `hash` child over leaves `[1, null, 3]` in three cells gives the tokens a flat `hash`
  column gives for integers `1` and `3`, and the null cell keeps JSON `null`; no output cell holds
  `NaN`, `1.0` or `3.0`. Mutation: build the leaf column by pandas inference in every case.
- AT-E1-9: a stub child that returns `float("inf")` gives a `mask_error` row error and a
  `nested_child_non_finite` warning, and the output cell is not written with `Infinity`; a stub
  child that returns `float("nan")` for a non-null leaf gives JSON `null`. Mutation: drop the
  finite check.
- AT-E1-10: (a) escaped: a cell `{"k":"\ud800","x":1}` with target `$.x` is read, and the output
  holds the escape `\ud800` unchanged; (b) raw: a Python `str` cell that holds a raw lone
  surrogate is `not_json` and the error text holds no character of the cell; (c) a 4301-digit
  integer leaf is written back with the same lexeme, and a rule that selects it gives
  `nested_cell_number_out_of_range`. Mutations: call `int()` on every integer lexeme; treat an
  escaped surrogate as `not_json`.
- AT-E1-11: a rule that matches an object hands the child plain `dict`, `int` and `float`
  values, never `JsonNumber`. Mutation: skip the deep conversion.
- AT-E1-12: every existing `strict_json_loads` test (records codec, native faker admission,
  `_canonical/_strict_spec.py`, `_canonical`) passes unchanged, and `STRICT_JSON_TOKENS` keeps
  its first four tokens in order. Mutation: change the default `max_int_digits` of
  `strict_json_loads`.
- AT-E1-13 (characterization): for every strategy in `SCALAR_HANDLERS` that the plan accepts as a
  nested child, a column of int-only, null-free leaves gives output bytes equal to the base; the
  leaf column dtype is `int64` as on the base; `tokenize` still raises with code
  `tokenize_requires_string_dtype`; and `test_categorical_seeded_nondet.py:318` (a null leaf keeps
  its ordinal) passes unchanged. The base bytes are captured on the 82-E1a head before the change.
  Mutation: build every leaf column with `dtype=object`.
- AT-E1-14: `capabilities_for("nested").warning_codes` and `CHUNK_VARIANT_WARNING_CODES` hold the
  five new codes (the pin in `tests/native/test_capabilities.py:121` is extended with them).
  Mutation: leave `nested_cell_oversized` out of `_capabilities.py`.

### 82-E2a (`tests/unit/profiling/test_scan_core_move.py`)

- AT-E2a-1: `ScanSetCore.model_json_schema()` and `ScanSetCoreRead.model_json_schema()` equal a
  snapshot taken on the base, `decoy_engine.profiling.ScanSetCore` and
  `decoy_engine.ScanSetCore` are the moved class, and the six importers listed in section 4.2
  import from `_scan_core`. Mutation: rename one field in the move.

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
  `SCAN_CELL_BYTES + 1`, cell `SCAN_MAX_CELLS + 1` under `strategy="full"`): each sets its count
  or flag and the right warning. One more fixture hits the map collapse and the path cap in the
  same column and shows the collapsed keys did not use path slots. Mutations: remove each bound
  check (five mutations), and emit paths in pass 1.
- AT-E2-6: a fixture with missing, null, malformed and mixed integer and string values at one
  path gives distinct `present_count`, `null_count`, `cells_malformed` and
  `kinds == ["integer", "string"]`. Mutation: count JSON null as missing.
- AT-E2-7: a record without `nested` validates on write and read; a record with it reads under a
  read model built without the field; strict cells refuse `present_count=True`, `"5"` and an
  unknown kind token on write (classes 2 and 4), while the read model accepts an unknown kind
  token. Mutation: `kinds: list[str]` on the write model.
- AT-E2-8: a plain text column and a column with under half JSON cells get `nested=None`; two runs
  give identical bytes with sorted paths. Mutation: iterate a set unsorted.
- AT-E2-9: `nested_paths=False` gives no `nested` members and the walker spy is never called.
  Mutation: ignore the switch.
- AT-E2-10: 20 cells, each an object keyed by a different first name (`{"Maria": {...}}`), with no
  detector hit, give the single path `$.*` and `key_suspect_collapsed == 20`; a key seen in 1 of
  20 cells collapses, a key seen in 2 of 20 is kept; a key that a detector hits collapses while
  its sibling keys at the same level are kept; a column with one qualifying cell gives only `*`
  segments. Mutation: remove the appearance rule.
- AT-E2-11: a column of plain strings never calls the parser (first-character prefilter).
  Mutation: parse every string.
- AT-E2-12 (map of maps): 100 cells of one object with 100 outer keys, each holding an object
  with 100 distinct inner keys, give the single path family `$.*.*`, `map_collapsed` counts both
  levels, and a spy on the pass-1 level state never holds more than
  `SCAN_MAX_PATHS * (SCAN_MAP_KEYS + 1)` keys at any time; a key that fails key rule 1 or 2 is
  never stored in that state. Mutation: collapse levels only at the end of pass 1.
- AT-E2-13: cells holding `NaN`, `Infinity`, `-Infinity` and `1e400` leaves are parsed (not
  malformed) and the paths have kind `number`. Mutation: scan with `non_finite="refuse"`.

### 82-E3a (`tests/sentry/defects/test_nested_child_choke_point.py`, existing nested plan-check tests)

- AT-E3a-1: every existing nested plan-check, secret-requirement, column-access and multi-table
  test passes unchanged (characterization; no assertion edited), including the exact error path
  text of each refusal. Mutation: build a migrated refusal path without `config_path`.
- AT-E3a-2: the sentry is red on one seeded module per covered shape and green on the migrated
  head. Mutation: revert one migrated site.

### 82-E3b (`tests/unit/execution/test_nested_rules.py`, `tests/unit/plan/checks/test_nested_rules.py`)

- AT-E3b-1: two rules (email via faker, id via hash with its own namespace) mask both leaves in
  one pass; the id leaf equals a flat `hash` column under the same namespace. Mutation: use the
  column namespace for every rule.
- AT-E3b-2: rules `$.a` and `$..a` (equal positions) and rules `$.a` and `$.a.b` (prefix) each
  fail the column with `nested_rules_overlap`, and no cell is written; rules `$.a` and `$.ab` do
  not overlap and both mask. Mutations: check only equal positions; compare path text with
  `startswith`.
- AT-E3b-3: `rules` plus `target`, empty `rules` and duplicate targets are refused with their
  codes in both `compile_plan` and `run_config_only_checks`. Mutation: drop the duplicate-target
  check.
- AT-E3b-4: each existing child refusal (top_code, date_shift `group_by`, bucket_perturb, `when`
  in a child) is still refused when the child sits in `rules[1]`, with the error path
  `tables.<t>.columns.<c>.provider_config.rules[1]...`. Mutation: `nested_children` returns only
  the first rule.
- AT-E3b-5: a rule matching nothing in a column with parseable cells fails closed per rule.
  Mutation: check zero matches across all rules together.
- AT-E3b-6: two non-deterministic `shuffle` rules in one column give independent permutations
  (their draw identities differ: `payload.rules[0]`, `payload.rules[1]`), and the single form
  gives bytes equal to the base on a seeded fixture. Mutation: leave `nested_draw_column` empty
  for every rule.
- AT-E3b-7: one `code_set` rule in `rules[1]` records its evidence under the real column name
  (`code_set_corpora[...]["column"] == "payload"`); a second `code_set` rule in the same column is
  refused with `nested_rules_code_set_repeated`. Mutation: set `nested_outer_column` to the rule
  identity.
- AT-E3b-8: `code_set` in `rules[1]` under a `when` that matches no row preflights and runs
  without error. Mutation: forward `preflight()` to the first rule only.
- AT-E3b-9: a `rules` column without top-level `target` or `strategy` passes the required-settings
  check; a single-form column without `target` is refused with `nested_target_unset` at
  `tables.<t>.columns.<c>.provider_config.target` as today; a rule without `target` is refused at
  `...provider_config.rules[1].target`. Mutation: drop the `unless_present` test in
  `requirement_applies`.

### 82-E4a (`tests/unit/plan/checks/test_nested_references.py`, `tests/unit/execution/test_nested_references.py`, `tests/unit/nested_json/test_path_keys.py`)

- AT-E4a-1: parent `customers.id` (hash, namespace `customer`) and a rule `$.customer_id` with
  `references` give equal masked keys for equal source keys; joining the outputs on the masked
  values returns every source match; a row whose leaf is JSON null keeps `null`, and an integer
  leaf in a cell beside a null cell still equals the parent's token (the AT-E1-8 dtype case).
  Mutation: give the rule the column namespace.
- AT-E4a-2: plan refusals, each with its code, on `compile_plan`: an unknown parent, `fpe`, a
  strategy mismatch, a namespace mismatch, a `when`-gated parent, path `$.items[*].id`, path
  `$..id`, a float parent, `tokenize` over an integer parent, a user-written `key_kind`, and
  `no_profile=True`. `run_config_only_checks` refuses the static ones (all but the float parent,
  the integer `tokenize` parent and `no_profile`). Mutation: allow `fpe`.
- AT-E4a-3: an integer parent with a string leaf `"42"` gives a row error and a
  `nested_reference_leaf_type_mismatch` warning; an object leaf too; the code is in
  `capabilities_for("nested").warning_codes` and `CHUNK_VARIANT_WARNING_CODES`. Mutation: coerce
  the leaf with `int()`.
- AT-E4a-4: compile writes `key_kind` into the rule's `references`, and the child's
  `strategy_config` fingerprint for a rule with `references` equals the fingerprint of the same
  rule without it; a hand-written plan whose rule has `references` and no `key_kind` fails the
  column closed with `nested_reference_requires_profile`. Mutation: write `key_kind` into the
  child's `strategy_config`.
- AT-E4a-5: a config with a reference compiles a plan whose `relationships` equal those of the
  same config without it, and runs on the full-frame and sequential routes with identical
  non-nested output. Mutation: append the path relation to `relationships`.
- AT-E4a-6: `path_relations(config)` returns one `PathRelation` per `references` rule (parent
  table and column, child table and payload column, `path`) in config order, and `()` for a
  config with no reference; `path_key_batches` over an integer parent yields an integer key
  column where a missing or JSON null leaf is null, and a malformed cell, a string leaf `"42"`
  and an object leaf are counted in `unreadable_rows` and not loaded. Mutations: skip rules
  given in the `rules` form in `path_relations`; coerce `"42"` with `int()` in
  `path_key_batches`.

### 82-E4b (`tests/unit/nested_json/test_path_keys.py`, `tests/unit/detection_verification/postscan/test_path_relations.py`, `tests/integration/test_nested_path_relations.py`)

- AT-E4b-1: a missing or JSON null leaf is a null key, not counted as orphan before or after the
  run (`MATCH SIMPLE`). Mutation: load null as the string `"null"`.
- AT-E4b-2: a fixture with 3 orphan path keys gives `orphan_rows == 3` in pre-scan
  `RelationshipFacts` and the same count in the post-scan path row; an unreadable child cell is in
  `unreadable_rows` and not loaded; a string leaf in an integer relation is counted in
  `unreadable_rows` and the key column stays integer. Mutation: `_keys._Run._lookup` loads the raw
  JSON text as the key.
- AT-E4b-3 (gate, not Postgres-only): `run_pipeline` on CSV sources (`customers`, `events` with a
  JSON `payload`) with `post_scan.integrity` on and a `references` rule: the report's `path_keys`
  holds one row with `path == "$.customer_id"` and status `checked`, the matching
  `fk_preservation` finding has the same `path`, and `report["keys"]` is byte-equal to the same
  run without the rule. Mutations: in `_post_scan._PostScanGate._keys`, pass `path_relations=()`;
  in `tee_reader`, call `key_columns` without the path relations (the payload column is not teed
  and the row is not `checked`).
- AT-E4b-4 (report-only): the same `run_pipeline` setup where the run introduces path orphans
  (the builder drops parent rows with a row filter that path relations do not steer, for example
  `subset` on `customers` alone): the path finding has severity `warning` and the orphan count,
  the verdict does not block, and the run publishes. A control run with the same orphans on a
  column relation blocks with the orphans code. Mutation: remove the severity cap in
  `fk_preservation._finding`.
- AT-E4b-5: a `scan-set/v1` record with `path` and `unreadable_rows` on a child reads back; a
  record without them reads with `None`. Mutation: make `path` required.
- AT-E4b-6: `KeyResult.as_dict()` for a path row has `path` and `unreadable_rows`; for a column
  row it has exactly the base members; every `fk_preservation` finding dict has `path` (`None`
  for a column relation) and reads back through the post-scan report reader. Mutation: write
  `path` on every `keys` row.
- AT-E4b-7: `run_post_mask` over pandas frames (no gate, no `keys` passed) gives a
  `fk_preservation` finding with `path` for a path relation and the right orphan count.
  Mutation: drop `path_relations(config)` from `fk_findings`.
- AT-E4b-8 (gate applies for a path relation alone, red first): `run_pipeline` on the AT-E4b-3
  CSV sources with no `relationships`, no `post_scan` block and one `references` rule whose
  output has 2 orphan path keys: `post_scan_gate_applies(config)` is true, the result's report
  holds `path_keys` with one row (`path == "$.customer_id"`, status `checked`, the orphan
  count) and an `fk_preservation` finding with the same `path`, severity `warning`, the verdict
  does not block, and the run publishes. Control: the same config without the `references` rule
  gives `post_scan_gate_applies(config)` false and no post-scan report, as on the base. On the
  82-E4b base the first cell is red (no gate runs, no report). Mutation: `post_scan_gate_applies`
  ignores path relations (the report is absent).

### 82-E5 (`tests/connectors/test_postgres_snapshot_jsonb.py`, `pg_integration`)

- AT-E5-1: a `jsonb` column holding `{"ssn": "...", "amt": 1.10, "big": 12345678901234567890.5,
  "e": 1e400}` (Postgres keeps them as `numeric`): snapshot, then `run_pipeline` with a two-rule
  `nested` column; unselected numbers come out as the text Postgres returned and the output
  parses as JSON. Mutation: revert `strict_json_write` to `json.dumps`.
- AT-E5-2: `scan_sources` over the staged Parquet reports the expected paths and detector ids for
  the `jsonb` column. Mutation: skip qualification for Parquet text columns.
- AT-E5-3: a `jsonb` reference to a parent table masks to the parent's identity and the post-scan
  path finding is `info`. Mutation: as AT-E4a-1.
- Each cell skips cleanly without docker or `DECOY_TEST_PG_DSN` (existing marker,
  `pyproject.toml:419`); the E5 gate needs a run log from a node with Postgres where they passed.

## 9. Goldens, pins and sentries that move

- Goldens: a golden that holds a `nested` cell with a non-round-trip number changes (a bug fix).
  A nested column whose leaves are integers with at least one null changes dtype (section 4.1,
  pre-GA semantic change). The builder lists each moved golden or fixture by name; AT-E1-2 and
  AT-E1-13 prove ordinary cells and null-free leaves do not move.
- Keyed baselines re-keyed by path only in 82-E1a, with equal entry counts (section 4.1):
  `tests/fixtures/f29/reason-baseline.json` (ten entries: `:637` to `:644` and `:835` to `:836`), `tests/fixtures/f29/producer-inventory.json`,
  `tests/sentry/baselines/f29-producer-inventory.json`,
  `tests/sentry/baselines/gcs-call-kwargs.json:128`, the allowlisted path in
  `tests/sentry/test_physical_seam_disconnection.py:591`. Later slices add entries for new
  producers (new codes) as the F29 baseline tools generate them; no entry is removed to make room.
- Pins extended with new codes (a list pin, not a cap): `tests/native/test_capabilities.py:121`
  in 82-E1 and 82-E4a.
- Size ceilings: none raised. `_nested.py` moves in 82-E1a to `nested/_handler.py` unchanged;
  each module of the sub-package stays at or under 600 lines, and rule code goes to
  `nested/_apply.py`, not the handler (the builder reports the counts per slice).
  `_canonical/_json.py` (209 lines) grows to about 400 with the bound constants. `scan_set.py`
  drops by about 130 lines in 82-E2a. `plan/_compile.py` (656 lines against its 666 ceiling,
  `tests/sentry/test_module_size.py:111`) takes at most 3 lines in 82-E3b and at most 3 in 82-E4a
  (662 at most); if that is not enough, the new call goes inside an existing check function
  instead. `execution/pipeline/_post_scan.py` (583 lines, no census entry) must stay at or under
  600 after 82-E4b (section 4.4).
- Fan-out: `execution/_strategies` goes from 29 to 28 direct modules in 82-E1a (`_nested.py` moves
  into `nested/`), and its freeze in `tests/sentry/layout/test_package_fanout.py:34` and
  `tests/sentry/baselines/package-fanout.json` is lowered to 28 (the ratchet moves down; nothing
  is raised); `CODEMAP.md:253` says "fan-out freeze at 28" and names the `nested/` span. `profiling` goes from 18 to 19 direct modules
  (`_scan_core.py`), under 25. The new sub-packages start well under 25.
- Layer contract: in 82-E3a, `_nested_json` joins the bottom tier of `.importlinter` and the snapshot in
  `tests/sentry/layout/test_import_layers.py`. This is a placement, not a widened allowance; no
  ignore line is added.
- Reason registry: every new code is `since=UNRELEASED`; the registry version moves at merge by the
  renumber tool.
- New sentries: the two choke-point sentries in section 6, each with seeded red cases, listed in
  the sentry registry.

## 10. Placement (checked against `CODEMAP.md:235`)

| New file | Directory | Map row | Beside |
|---|---|---|---|
| No new file; `strict_json_read`, `strict_json_write`, `JsonNumber` added to `_json.py` (E1) | `src/decoy_engine/_canonical/` | "Foundation: `_canonical/`" (`CODEMAP.md:269`), unchanged row | `_canonical/_json.py` |
| `nested/__init__.py`, `nested/_handler.py` (moved from `_nested.py`, E1a), `nested/_leaves.py` (E1), `nested/_apply.py` (E3b) | `src/decoy_engine/execution/_strategies/nested/` | "Masking strategy family: `execution/_strategies/<family>/`" (`CODEMAP.md:253`), the target the fan-out freeze names; the row gains the `nested/` code span in E1a | `execution/_strategies/_hash.py` |
| `__init__.py`, `_rules.py` (E3a), `_paths.py` (E4a) | `src/decoy_engine/_nested_json/` | Map change: new row "Nested JSON cell foundation", worded like the `_canonical/` row (`CODEMAP.md:269`); bottom layer | `src/decoy_engine/_canonical/` |
| `_scan_core.py` (E2a) | `src/decoy_engine/profiling/` | "Detectors, profiling" (`CODEMAP.md:262`) | `profiling/scan_set.py` |
| `paths/__init__.py`, `paths/_walk.py`, `paths/_observe.py` (E2b) | `src/decoy_engine/profiling/paths/` | "Detectors, profiling"; map text gains "path observation in `profiling/paths/`" | `profiling/features/` |
| `_nested_rules.py` (E3b) | `src/decoy_engine/plan/checks/` | "Plan compile and checks: new checks in `plan/checks/`" (`CODEMAP.md:251`) | `plan/checks/_relationship_keys.py` |
| `warning/_nested_cells.py` (E1), `warning/_nested_paths.py` (E2b), `plan/_nested_rules.py` (E3b) | `src/decoy_engine/reasons/` | "Reason codes" (`CODEMAP.md:265`) | `reasons/runtime/_f06.py` |
| `nested-json.md` (E5) | `docs/` | "Feature and contract docs" (`CODEMAP.md:273`) | `docs/publication.md` |
| tests | `tests/unit/canonical/`, `tests/unit/nested_json/`, `tests/unit/profiling/paths/`, `tests/unit/plan/checks/`, `tests/unit/execution/`, `tests/unit/detection_verification/postscan/`, `tests/integration/`, `tests/sentry/defects/`, `tests/connectors/` | "Unit tests", "Sentry test" (`CODEMAP.md:270`, `CODEMAP.md:280`) | existing siblings |

`src/decoy_engine/_MAP.md` gains rows for `_nested_json/` and `profiling/paths/`. Present
consumers: `strict_json_read` and `strict_json_write` are used by the nested handler in E1 and by
`profiling/paths` in E2b; `_rules.py` by the seven sites and the handler in E3a; `_paths.py` by
`_scan_integrity.py` and `_keys.py` in E4b;
`profiling/paths/` by `scan_set.py` in E2b. No module merges before its consumer.

## 11. Reuse inventory

- `jsonpath-ng` for `target` matching and writeback (unchanged), and its parsed node types
  (`Root`, `Child`, `Fields`) for the singular-path check.
- `strict_json_loads` (`src/decoy_engine/_canonical/_json.py:173`), the engine's one strict JSON
  reader (recording hooks, `STRICT_JSON_TOKENS`, raise after `except`), used today by
  `_canonical/_strict_spec.py`, `records/_codec.py` and the native faker admission. 82-E1 grows it into the bounded,
  lexeme-keeping reader; no second reader is written.
- Python `json` hooks for duplicate detection and number lexemes (no new dependency).
- `run_all_detectors` (`src/decoy_engine/detection/detectors.py:648`) for leaf detection.
- The scan sample already read by `_read_and_profile` (`src/decoy_engine/profiling/scan_set.py:399`);
  no second read of the source.
- `key_facts`, `KeyBatches` and the DuckDB anti-join in `profiling/_scan_integrity.py`, and
  `check_keys` with its `_Run` in `verification/postmask/_keys.py`, for path orphan counts; the
  `fk_tokens` key identity is unchanged.
- The handler's `_path_segments` (structured match paths) for the cross-rule overlap check.
- `ctx.nested_outer_column` save and restore around the child call, the pattern the new
  `nested_draw_column` follows.
- The namespace registry `for_column` (`src/decoy_engine/relationships/_namespace.py:119`) for the
  reference namespace check.
- `RowError`, the existing `QualityWarning` carrier for nested cell-fault codes, and the existing
  quarantine policy for every cell fault.
- `_relaxed` read-model derivation (moved, not copied) for the additive scan fields.
- `StrategyRequirement` rows and `requirement_applies` for the `rules` form (one additive field).

## 12. Frozen contracts

| Surface | Change | Rule followed |
|---|---|---|
| `scan-set/v1` (`docs/compatibility-contract.md:251`) | Additive: `FieldCore.nested`, `ChildFactsCore.path`, `ChildFactsCore.unreadable_rows`, all defaulted `None`; strict write models; read model ignores unknowns. The contract text says every field in a new record carries `"nested": null` when it is not a JSON column, and every child fact carries `"path": null` and `"unreadable_rows": null` for column relations | Same precedent as SCAN-ML M3a `model_hits`; contract text, frozen-surface map row and a corpus sample in the same slice |
| `post-scan-integrity/v3` (`docs/compatibility-contract.md:295`) | Additive only: `fk_preservation[].path` (`null` for column relations); report member `path_keys`, present only when a path relation is declared, rows shaped as `keys` rows plus `path` and `unreadable_rows`; `keys` rows of column relations keep their exact members; `check_keys` gains keyword `path_relations=()` | Additive; same precedent as SCAN-ML M4 `residual_pii` fields; contract text in 82-E4b; read-back covered by AT-E4b-6 |
| `strict_json_loads` and `STRICT_JSON_TOKENS` | Behavior unchanged; the token tuple gains `oversized` and `too_deep` at the end | Internal foundation; AT-E1-12 pins the existing callers |
| Module path of the nested handler | `execution/_strategies/_nested.py` becomes `execution/_strategies/nested/_handler.py` (82-E1a, move only) | Private module; the strategy registry name `nested` is unchanged |
| `post_scan_gate_applies` (exported from `decoy_engine.config`) | Also true when the config declares a path relation (82-E4b). Configs without a `references` rule get the same answer as today | Additive reason for an existing gate; a path-only job had no integrity check before, and the new check is report-only for path rows; AT-E4b-8 with its control cell |
| `scan_sources` signature | Additive keyword-only `nested_paths=True`, `path_relations=()` | Contract section 3.1: new keyword-only parameters are additive |
| `nested` `provider_config` (`docs/compatibility-contract.md:1029`) | Additive `rules` list with per-rule `namespace` and `references`; the single form is unchanged | Required-settings text updated |
| `nested` output bytes | Change only for cells with non-round-trip numbers (bug fix), for integer leaves with a null (object dtype), and for a child `NaN` output (now JSON `null`) | Recorded as pre-GA semantic changes in the contract and the changelog in 82-E1 |
| `StrategyRequirement` | Additive field `unless_present` (default `None`) | Internal contract; existing rows unchanged |
| `StrategyContext` | Additive field `nested_draw_column` (default `""`) | Internal; empty keeps every draw identity unchanged |
| Reason registry | New codes, `since=UNRELEASED` | Renumbered at merge |
| Root facade `decoy_engine/__init__.py` (599 lines) | No change; new names are exported from `decoy_engine.profiling` | Keeps the root under its size limit |

## 13. Class table

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output in errors, logs or scan records | Fixed reason texts; observations built only from counts, kind tokens, ids and rule-checked segments; `sample_misses` dropped | AT-E1-6, AT-E2-2, AT-E2-3 | copy `str(exc)` or a raw key into output |
| 2 | Cleanup missing on an exit path | No new files or scratch; path keys use the existing protected spill dir and its cleanup in `_scan_integrity` | AT-E4b-2 plus the existing spill cleanup tests | open a second DuckDB spill outside the allocator |
| 3 | State and concurrency | Reader, walker and rules are pure functions; constants are module `Final`; no cache | AT-E2-8 determinism | memoize observations in a module global |
| 4 | Route parity and silent fallback | `nested` keeps today's route set; path relations never enter `relationships`; route matrix in the doc | AT-E4a-5, existing route-decline tests | append the path relation to `relationships` |
| 5 | Referential integrity | Reference identity checked at plan time (namespace, strategy, key kind bound from the profile) and at run time (leaf kind); one extractor for pre and post scan; path orphans report-only | AT-E4a-1, AT-E4a-3, AT-E4a-4, AT-E4a-6, AT-E4b-2, AT-E4b-4, AT-E4b-8 | coerce `"42"` to `42` |
| 6 | Untrusted producer data | JSON cells are untrusted: byte, depth and duplicate bounds before use; key rule before any key text is written | AT-E1-3, AT-E1-4, AT-E1-5, AT-E2-5 | remove the byte check |
| 7 | Check then use (TOCTOU) | Size checked on the same in-memory text that is parsed; no re-read of the source | AT-E1-4 | re-read the cell after the size check |
| 8 | Weak tests and overclaimed evidence | Red-first cells with named mutations on the final head; JSONB cells run on a Postgres node and a skip is reported, never counted as a pass | AT-E5-1 to AT-E5-3, AT-E1-2 | assert only that output parses |
| 9 | Behavior-preserving refactor drift | 82-E1a and 82-E2a are pure moves (keyed baselines re-keyed by path with equal counts; schema snapshot); 82-E3a keeps every existing assertion and error path unchanged; null-free leaves and the single form stay byte-identical | AT-E1a-1, AT-E2a-1, AT-E3a-1, AT-E1-12, AT-E1-13, AT-E3b-6 | rename a field in the move |
| 10 | Frozen contract drift | Additive defaulted fields only; contract text, frozen-surface map row and corpus sample in the same slice | AT-E2-7, AT-E4b-5, AT-E4b-6, `tests/sentry/release/test_frozen_surface_map.py` | make a new field required |

Class 11 (no raised caps): nothing in this plan raises a size ceiling, fan-out allowlist,
baseline, pin or allowlist. The `execution/_strategies` freeze is lowered (29 to 28). Keyed
baselines are re-keyed by path with equal counts (82-E1a). The list pin in
`tests/native/test_capabilities.py:121` gains the new codes; it is a list of codes, not a cap. The
`.importlinter` bottom tier gains one member (placement); no ignore line is added.

## 14. Enumerations

### Exit paths

- Cell fault (oversized, malformed, too deep, duplicate key): row error, then quarantine or job
  failure (`src/decoy_engine/execution/_strategies/_nested.py:325`).
- Rule overlap, a rule that matches nothing, an unknown child: `StrategyError`, the job fails and
  nothing is published (`src/decoy_engine/execution/_strategies/_nested.py:400`).
- Reference leaf kind mismatch, selected integer over 4300 digits, child `inf` output: row
  error plus a warning code (new).
- A rule with `references` and no bound `key_kind` (a hand-written plan): `StrategyError`
  `nested_reference_requires_profile`, the job fails.
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
- Path relation with a singular name path, a scalar leaf, an integer or string parent, and
  `hash` or `tokenize`: supported (82-E4a), orphans counted report-only (82-E4b).
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
  `rules[].namespace`, `rules[].references.table`, `rules[].references.column`, and
  `rules[].references.key_kind` (written by compile only; refused from the user).
- `KeyResult.path`, `KeyResult.unreadable_rows`, `FKPreservationFinding.path`.
- `StrategyRequirement.unless_present`, `StrategyContext.nested_draw_column` (internal).
- `scan_sources` keywords `nested_paths` and `path_relations`.

### Output surfaces

- Masked output cells of `nested` columns (serialization contract).
- `scan-set/v1` core (value-free) and the `detail` member (unchanged, value-bearing by contract).
- Post-scan `fk_preservation` findings for path relations and the `path_keys` report member.
- Row errors, quarantine records, `QualityWarning`s, `StrategyError` and `PlanCompileError` texts.
- Logs: one count-only debug line per scanned table.

## 15. Slices, gates and risk

| Slice | What | Production files (max 10) | Lines (about) | Risk and gate | After |
|---|---|---|---|---|---|
| 82-E1a | Move only: `_nested.py` to `nested/_handler.py`, importers and keyed baselines re-keyed by path, freeze 29 to 28, CODEMAP span | 3: `nested/_handler.py` (moved), `nested/__init__.py`, `_strategies/__init__.py` (registry import); plus test imports, five keyed baselines, the fan-out freeze in two files, `CODEMAP.md` | 40 changed, plus 585 moved | R1: Codex | none |
| 82-E1 | Bounded lexeme-keeping mode of the one strict reader, writer, leaf column dtype rule, child output rule, `MASK_*` constants, warning codes in the three registries | 8: `_canonical/_json.py`, `_canonical/__init__.py`, `nested/_handler.py`, `nested/_leaves.py`, `execution/_mixed_admission.py`, `execution/native/_capabilities.py`, `reasons/warning/_nested_cells.py`, `reasons/warning/__init__.py` | 650 | R2 (data handling): Dennis then Codex | 82-E1a |
| 82-E2a | Move the scan-set core models to `profiling/_scan_core.py`, importers moved, frozen-surface row | 5: `_scan_core.py`, `scan_set.py`, `profiling/__init__.py`, `scan_set_read.py`, `scan_diff.py` | 280 (moved) | R1: Codex | none |
| 82-E2b | `profiling/paths/` (two-pass walk with bounded pass-1 state, key rule with per-key detectors and appearance, cells cap), `SCAN_*` constants, `NestedCore`, scan wiring, scan warning codes, contract text | 10: `paths/__init__.py`, `paths/_walk.py`, `paths/_observe.py`, `_scan_core.py`, `scan_set.py`, `profiling/__init__.py`, `_canonical/_json.py`, `_canonical/__init__.py`, `reasons/warning/_nested_paths.py`, `reasons/warning/__init__.py` | 800 | R2 (value leaks): Dennis then Codex | 82-E1, 82-E2a |
| 82-E3a | `nested_children(provider_config)` choke point with `config_path`, migrate the seven child readers, sentry, layer contract | 10: `_nested_json/__init__.py`, `_nested_json/_rules.py`, `.importlinter`, `nested/_handler.py`, `plan/_checks_top_code.py`, `plan/_checks_date_shift.py`, `plan/_checks_bucket_perturb.py`, `secret_providers/_requirements.py`, `execution/_column_access.py`, `execution/_pipeline_multi_table.py` | 400 | R2 (cross-cutting refactor): Dennis then Codex | 82-E1 |
| 82-E3b | `rules` form, either-form requirement rows, separate per-rule draw identity, one `code_set` rule per column, match-all-before-write overlap on path tuples, preflight to every child, plan checks | 10: `_nested_json/_rules.py`, `nested/_handler.py`, `nested/_apply.py`, `plan/checks/_nested_rules.py`, `plan/checks/__init__.py`, `plan/_compile.py`, `contracts/strategy_requirements.py`, `execution/_adapter.py`, `reasons/plan/_nested_rules.py`, `reasons/plan/__init__.py` | 750 | R2 (masking identity): Dennis then Codex | 82-E3a |
| 82-E4a | References: path shape, identity and gated-parent refusals, key kind bound at compile, leaf-kind row error and its warning code in the three registries; `path_relations` and `path_key_batches` defined, not yet read | 10: `_nested_json/_rules.py`, `_nested_json/_paths.py`, `nested/_handler.py`, `nested/_apply.py`, `plan/checks/_nested_rules.py`, `plan/_compile.py`, `reasons/plan/_nested_rules.py`, `reasons/warning/_nested_cells.py`, `execution/_mixed_admission.py`, `execution/native/_capabilities.py` | 700 | R2 (referential integrity): Dennis then Codex | 82-E3b |
| 82-E4b | Pre-scan facts, post-scan gate and findings, gate applies for a path relation, report-only cap, additive child facts, `KeyResult.path`, `FKPreservationFinding.path`, `path_keys`, contract text | 9: `config/_post_scan.py`, `profiling/_scan_integrity.py`, `profiling/scan_set.py`, `profiling/_scan_core.py`, `profiling/__init__.py`, `verification/postmask/_keys.py`, `execution/pipeline/_post_scan.py`, `verification/postmask/fk_preservation.py`, `verification/postmask/types.py` | 600 | R2 (referential integrity, frozen report, gate activation): Dennis then Codex | 82-E4a, 82-E2b |
| 82-E5 | JSONB `pg_integration` acceptance, `docs/nested-json.md`, changelog, roadmap note | 0 | 400 (tests and docs) | R1: Codex | 82-E4b |

The ten-file limit counts production files under `src/` and `.importlinter` only. Tests,
baselines, fixtures, sentry maps, `CODEMAP.md` and docs are listed in a row where they move but
are not counted.

The split of row 82-E4 follows the ten-file limit. Dennis round 2 proposed references plus
pre-scan in 82-E4a and post-scan in 82-E4b; that puts 12 files in 82-E4a. The split above keeps
pre-scan and post-scan together in 82-E4b, because AT-E4b-2 (both sides count the same orphans
through one extractor) needs both in one slice. Revision 4 adds `config/_post_scan.py` to
82-E4b (the gate applies for a path relation) and moves the two pure definitions
`path_relations` and `path_key_batches` into 82-E4a, so 82-E4a has 10 production files and
82-E4b has 9.
`verification/postmask/_blocked.py` does not change (section 4.4).

Expected size in total: about 4,350 changed lines including tests, plus the 585-line handler move. New public names:
`NestedCore`, `PathObservationCore`, `PathRelation`, `path_relations`, `TableScan.nested`,
`FieldCore.nested`, and the `scan_sources` keywords `nested_paths` and `path_relations` (exported
from `decoy_engine.profiling`). A slice that runs well past its line budget stops and explains before
review.

Test depth per slice: T0 and T1 by the builder on a test VM or the Mac, never the devbox; T2 at
the gate on the exact head with the mutations above. Full-suite triggers: 82-E1a (moved module,
keyed baselines and a fan-out freeze change), 82-E1 (nested output bytes), 82-E3a (layer contract
is test configuration), 82-E2a, 82-E2b and 82-E4b (serialization of a frozen contract). These run once
per merge-batch head under the merge-train rule.

## 16. Dependencies, release and repin

- 82-E1a and 82-E2a start at once (no shared file). 82-E1 after 82-E1a. 82-E2b after 82-E1 and
  82-E2a. 82-E3a after 82-E1. 82-E3b after 82-E3a. 82-E4a after 82-E3b. 82-E4b after 82-E4a and
  82-E2b. 82-E5 last.
- One writer at a time on the nested handler sub-package (82-E1a, 82-E1, 82-E3a, 82-E3b, 82-E4a
  in that order), on `_nested_json/_rules.py` (82-E3a, 82-E3b, 82-E4a), on
  `_canonical/_json.py` (82-E1, 82-E2b), on the nested warning-code registries (82-E1, 82-E4a) and
  on `profiling/scan_set.py` and `_scan_core.py` (82-E2a, 82-E2b, 82-E4b).
- Each merged slice ships in the next daily engine release. No CLI repin is required for this row;
  the CLI follow-up row (OQ-8) waits for the release that carries 82-E4b.

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
  `SCAN_ARRAY_ITEMS` 16, `SCAN_MAX_PATHS` 256, `SCAN_MAP_KEYS` 64, `SCAN_LEAF_SAMPLE` 1000,
  `SCAN_MAX_CELLS` 20480, `SCAN_KEY_APPEARANCE` 0.1),
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
- **OQ-8. CLI exposure.** Recommended: a new CLI row after the engine release that carries 82-E4b:
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
- A nested module grows past 600 lines across 82-E3b and 82-E4a. Guard: the 82-E1a move into
  `nested/`, per-slice line reports, rule application in `nested/_apply.py` and the rule model in
  `_nested_json/_rules.py`, not in the handler.
- Growing `strict_json_loads` changes behavior for its existing callers (records codec, native
  faker admission). Guard: AT-E1-12 runs their tests unchanged and pins the defaults.
- A child keys draws or evidence on something other than the column name the handler passes, so
  two rules still share a slot. Guard: AT-E3b-6 and AT-E3b-7, and the stop rule in section 4.3.
- The leaf dtype rule moves bytes for a child that reads dtype, on null-free leaves. Guard:
  AT-E1-13 runs every nested-usable child on the base and the head; only columns with an integer
  and a null change dtype, and those are listed as a pre-GA change.
- `_post_scan.py` (583 lines) passes 600 with the path wiring. Guard: the merge of declared ends
  goes into `_keys.py` (section 4.4); the builder reports the count.
- A post-scan path finding blocks a run by mistake through a later change to `_blocked.py`.
  Guard: AT-E4b-4 runs a publishing run with path orphans and a blocking control on a column
  relation.
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
- F-6 (V2-LOG): custom detectors (`run_all_detectors(custom=)`) and the `pre_scan` model detector
  are not run on path leaves; path `detector_hits` come from the built-in regex detectors only
  (section 4.2).

## 20. Review record

- Revision 1 (`917571fee`), Dennis round 1: GO-WITH-FIXES, 4 HIGH, 8 MEDIUM, 5 LOW, all plan edits.
  Owner answers kept as recommended. Revision 2 applies all of them:
  - HIGH-1: one strict reader; the bounded mode grows `_canonical/_json.py` (section 4.1, section 11).
  - HIGH-2: per-rule draw and evidence identity (section 4.3; AT-E3b-6, AT-E3b-7).
  - HIGH-3: null leaves kept out of the child, object-dtype leaf column (section 4.1; AT-E1-8,
    AT-E4a-1).
  - HIGH-4: per-key detectors and the appearance rule (section 4.2; AT-E2-10).
  - MEDIUM-1: `QualityWarning` beside the `RowError` is the code carrier (section 4.1; AT-E1-3).
  - MEDIUM-2: `JsonNumber` defined, deep conversion, size check order, surrogates, long integers,
    non-finite child output (section 4.1; AT-E1-9 to AT-E1-11).
  - MEDIUM-3: two-pass walk and `SCAN_MAX_CELLS` (section 4.2; AT-E2-5).
  - MEDIUM-4: match all rules before writing, equal or prefix overlap, preflight to every child
    (section 4.3; AT-E3b-2, AT-E3b-8).
  - MEDIUM-5: gated parent refused, wrong-kind leaf counted unreadable (section 4.4; AT-E4a-2,
    AT-E4b-2).
  - MEDIUM-6: `KeyResult.path` and the `check_keys` keyword (sections 4.4 and 12; AT-E4b-6).
  - MEDIUM-7: handler split into `execution/_strategies/nested/` in 82-E1, freeze lowered to 28
    (sections 4.1, 9, 10).
  - MEDIUM-8: allowed dependencies per package; `nested_children` takes a provider-config
    mapping (sections 4.3 and 6).
  - LOW-1: importers moved, no re-export. LOW-2: read model accepts `str` kinds. LOW-3: contract
    text names the null members. LOW-4: `nested_rule_namespace_unknown` dropped. LOW-5:
    first-character prefilter (AT-E2-11).
- Revision 3, Dennis round 2 (last Dennis round): 1 HIGH, 9 MEDIUM, 8 LOW. Each finding was
  checked against `origin/main`; all were found correct and applied as below.
  - H1: post-scan wiring moved to the real site: `_post_scan.py` (`_relationships`, `tee_reader`,
    `_keys`), `fk_preservation.fk_findings`, `FKPreservationFinding.path`, `KeyResult.path`, a
    `path_keys` report member and additive `post-scan-integrity/v3` text. Report-only: findings
    capped at `warning`, `_blocked.py` unchanged (sections 4.4, 12; AT-E4b-3, AT-E4b-4,
    AT-E4b-7). Row 82-E4 split into 82-E4a (references and plan checks, 9 files) and 82-E4b
    (pre-scan and post-scan, 10 files). This differs from the suggested split (pre-scan in
    82-E4a): that gives 82-E4a 12 files, and AT-E4b-2 needs both scan sides in one slice.
    Choke-point mutations name `_post_scan._PostScanGate._keys` and `fk_findings` (section 6).
  - M1: `RecursionError` maps to `too_deep` only when `max_depth` is set; nested mode passes
    `max_int_digits=None` (section 4.1; AT-E1-5, AT-E1-10).
  - M2: a separate draw identity `StrategyContext.nested_draw_column` read only by
    `context_draw_identity` and `draw_column`; evidence keys keep the real column, child modules
    unchanged; `code_set` is refused when repeated in one column because its record cache is keyed
    on the column (section 4.3; AT-E3b-6, AT-E3b-7).
  - M3: deviation from revision 2: null leaves are no longer dropped, because that shifts
    positional ordinals (`test_categorical_seeded_nondet.py:318`). Nulls keep their place; object
    dtype only for integer leaves with at least one null; null-free leaves unchanged. Listed as a
    pre-GA change with the characterization cell AT-E1-13 (section 4.1, section 9).
  - M4: `native/_capabilities.py` and `_mixed_admission.py` in 82-E1 and 82-E4a with the
    reason modules; the list pin is extended (AT-E1-14, AT-E4a-3).
  - M5: size measured with `encode("utf-8", "surrogatepass")`; a raw lone surrogate is `not_json`
    at any size, an escaped one is kept (AT-E1-4, AT-E1-10).
  - M6: pass-1 state bounded: online collapse past `SCAN_MAP_KEYS`, key rules 1 and 2 in pass 1,
    tracked levels capped, qualification bounded by the cell cap, cells re-parsed in pass 2
    (section 4.2; AT-E2-12).
  - M7: compile binds `key_kind` into `references`, outside the child `strategy_config`;
    `no_profile` refuses and a hand plan fails closed (section 4.4; AT-E4a-2, AT-E4a-4).
  - M8: move is its own slice 82-E1a with every keyed path listed and re-keyed by path only with
    equal counts (sections 4.1, 9; AT-E1a-1).
  - M9: `MASK_*` and `SCAN_*` constants live in `_canonical/_json.py`, bottom tier, importable
    by `_nested_json/_paths.py` (section 4.1).
  - L1: path is `execution/_adapter.py`. L2: `_canonical` imports `reasons` and `_error_base`
    (section 6). L3: one warning per faulty cell. L4: overlap compares `_path_segments` tuples
    (AT-E3b-2). L5: scan reads with `non_finite="keep"`; `NaN`, `Infinity` and `1e400` leaves are
    kind `number` (AT-E2-13). L6: `test_scanml_m3a_record.py` added to the importers; no
    re-export from `scan_set.py`. L7: custom and model detectors dropped on paths, recorded as
    F-6. L8: `StrategyRequirement.unless_present` either-form (AT-E3b-9), `NestedChild.config_path`
    prefix (AT-E3a-1), single-cell collapse documented (AT-E2-10).
- Revision 4, Codex round 1: NO-GO, 1 V1 and 3 V2-LOG findings, all plan edits, all applied.
  Base refreshed to `62353dc0b`.
  - V1-1: a path relation now makes the post-scan gate apply on its own. `post_scan_gate_applies`
    reads `path_relations(config)` through the one choke point, in 82-E4b with the post-scan
    wiring, so the gate never applies before it can count path keys. Report-only kept: path rows
    and findings never block; existing gate wiring faults fail closed as for a relationship-only
    job (sections 2, 4.4, 5 F29, 6, 12; AT-E4b-8 red first, mutation "gate ignores path
    relations"; the old AT-E4b-3 cell that pinned the gate as unchanged is removed). F-7 removed
    from the follow-ups. To keep 82-E4b within ten production files, `path_relations` and
    `path_key_batches` are defined (not yet read) in 82-E4a (AT-E4a-6): 82-E4a has 10 production
    files, 82-E4b has 9.
  - V2-LOG-2: 82-E1a lists the two warning entries `nested_cell_json_parse_error` and
    `nested_jsonpath_path_overlap` (`reason-baseline.json:835` to `:836`) beside the eight runtime
    entries; AT-E1a-1 counts ten entries and its mutation covers a warning entry (sections 4.1, 9).
  - V2-LOG-3: the slice-table note states the ten-file limit counts production files only
    (`src/` and `.importlinter`); tests, baselines, maps, `CODEMAP.md` and docs are listed, not
    counted (section 15).
  - V2-LOG-4: base moved from `3bddfc9ff` to `62353dc0b`. Citations re-checked: the contract
    lines move to `docs/compatibility-contract.md:295` and `:1029`, `profiling/__init__.py:75`
    moves to `:77`; the nested handler, the keyed baselines, `CODEMAP.md` rows and the other cited
    lines are unchanged.
- Codex round 2 (head fe6ad913e): GO. One V2-LOG fixed by the orchestrator: the Placement row now assigns `_nested_json/_paths.py` to E4a. Plan PASSED.
