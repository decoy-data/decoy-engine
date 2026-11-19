Status: plan (revision 3.3, 2026-11-19; O3 build blocker on fixed-schema Parquet sinks resolved by the orchestrator; revision 3.2: Dennis rounds 1 and 2, Codex rev 3 gate, and orchestrator O3 self-check addressed; owner answered Q1 to Q12)

# 1.0 freeze batch: the experimental tier, the frozen surface, and the output shapes that change before the freeze

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

This plan covers the three 1.0 rows that had no plan: EXPERIMENTAL-TIER, FREEZE-SURFACE and FREEZE-OUTPUT (1.0 scope triage, `C:docs/records/2026-11-18-1.0-scope-triage.md`, CLI branch `claude/focused-sagan-0arhsp`, PR #320). They are planned in that order because each one decides the next: the tier says which names are not frozen, so FREEZE-SURFACE only cleans up what stays frozen, and FREEZE-OUTPUT only fixes output bytes of frozen routes. Every slice lands before row 93 (REL-GATE), and every engine slice lands before the D-4 engine release (REL-GATE G1).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `f1da00f5`. The plan lives in the engine repo on branch `plan/freeze-batch` because most of the slices and both contracts it edits are engine-owned.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (the compatibility trigger makes every slice that changes a frozen or compatibility surface R2), `development-loop.md` (PLAN: scope, behaviour and failure modes, acceptance tests first with their mutation, placement, slice table, owner questions), `profiles/local-operations.md` (local plan and review tiers), `architecture.md` (placement, fan-out and central rules), `exploration.md` (source-backed route and caller checks), `verification.md` (exact-artifact evidence), `code-review.md` (proposal and finding checks), `api-and-compatibility.md` (consumer inventory, explicit breaking changes, contract tests), `cross-cutting-concerns.md` (one choke point plus a sentry and its mutation), `security.md` (outbound URL schemes and redirects), `data-and-migrations.md` (output format bytes), `testing.md` (T0 to T2, mutations), `proportionality.md`, `reuse-first.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2 overall and for every implementation slice. `risk-and-exceptions.md` makes compatibility an R2 trigger: X0 and X1 define stability tiers; S1 and S2 remove public surfaces; S4 to S7 change frozen names, accepted inputs, outbound policy or artifact tags; O1 to O3 change output contracts. Approver: Cam (owner) for the plan and the owner questions; Dennis then Codex for the plan gate.

Why 1.0: all three rows pass the "freeze" test of the triage. After 1.0, any of these changes is a 2.0 break under the triage's definition (a public name, a default, an output byte, an exit code, a reason string, a schema field, a report tag, or a new refusal for a config or run that is valid today). The tier must exist before 1.0, or every public name is frozen by default.

### Revision 2 changes (Dennis round 1: 1 BLOCKER, 9 HIGH, 9 MEDIUM, 3 LOW)

| Finding | Change | Where |
|---|---|---|
| B1 | Superseded by the owner Q10 re-decision recorded in revision 3. | Revision 3 B1 |
| H1 | One `lossless_int_columns(plan, registry, graph)` in `_fk_keys.py`, called from every ingestion site and `native/_when_mask.py`; it includes the integer columns `when:` reads. Drift sentry. Second output change (int64 instead of double on whole-frame routes) listed. | 4.3, 5.5, 10.6 |
| H2 | O3: no new module. `narrow_text` in the passthrough branch of `native/_chunked_schema_rule.py`; `kernel/_scalar.py::passthrough_array` narrows per batch. Text over 2 GiB is split, never refused. | 4.3, 10.3 |
| H3 | S6 folds telemetry's `validate_endpoint` in as purpose `otel`. The sentry is import-based over every network module spelling, with a (path, name) allowlist. | 4.2, 10.7 |
| H4 | Redirect rule per purpose; installer and bundle purposes follow https-to-https redirects; new test. Notify keeps its behaviour. | 10.7, AT-S6e |
| H5 | Tiers are assigned by object identity. sdk names that are `errors.*` objects stay frozen. Root re-exports handled. Constants are covered by their module docstring marker. | 4.1, 10.1 |
| H6 | One default: the census reads contract 3.4 plus every public subpackage `__all__`; each name has an explicit tier. | 4.1, AT-X0e |
| H7 | Tag regex allows dots and underscores; revision 3 corrects the outside-3.1 count to 30. The classification rule is written down; f-string tags are a known limit. | 4.2, 5.6 |
| H8 | O2 covers `.tar.gz` (same gzip wrapper, `TarInfo.mtime=0`) and zip (fixed `date_time`); pinned compression level; the claim is scoped to the same zlib build. | 4.3, 10.4 |
| H9 | Order against FAKER-MIGRATE, PROP-batch C-F1b and E-S1a/E-S1b written down (Q11). | 10.5 |
| M1 to M9 | Notify URLs come from `--notify`, value-free `NotifySpecError`; F12 and old AT-O3c dropped; S7 sized honestly; Removed and Breaking fragments and a contract section 1 entry; AT-S5a labelled a guard with the case policy; G1 narrowed to what the tests check; gzip header bytes asserted; route lists recorded as a known limit; upgrade-document artifact purpose added. | throughout |
| L1 to L3 | `pyproject.toml:549` and `:1019` entries removed in S1; S4 updates the durable `FREEZE-SURFACE` row in `C:docs/roadmap/groups/health.md` and keeps `report.*` descriptors in the one descriptor module; compression level pinned. | S1, S4, O2 |

### Revision 3 changes (Dennis round 2: 1 BLOCKER, 6 HIGH, 7 MEDIUM, 4 LOW)

| Finding | Change | Where |
|---|---|---|
| B1 | Q10 now requires one NaN-style null-selection rule for every column class and route. The Breaking entry names FK keys, declared integers, date-shift anchors, `top_code`, and `group_key` siblings. AT-O1b pins each class on every route and mutates each class independently. | 1, 4.3, 5.3 to 5.6, 6 to 8, 10.6, 14, 15 |
| H1, H2 | Object evaluation is selected when either a referenced value or any integer literal is outside `[-2**53, 2**53]`, including int64-to-float-literal comparisons. AT-O1b and AT-O1c include a literal-only trigger, chunk size 1, and a mutation that removes the literal check. | 4.3, 8, 10.6 |
| H3 | The ingestion census has six direct sites, including `_unified_slice_admission.py:364`; `_faker_null_mask.py` widens its protected set with `lossless_int_columns`. The exact caller allowlist names indirect diagnostic callers and flag-on/flag-off parity. | 4.3, 5.1, 5.3, 8, 10.6 |
| H4 | One split-and-narrow helper in `_arrow_types.py` serves chunked schema normalization and out-of-core passthrough. Analytic passthrough typing is narrowed too, including FK resolution. `mask_batch` splits record batches by row slice. AT-O3e patches the shared helper on every route. | 4.3, 5.3, 8, 9, 10.3 |
| H5 | X0 uses the measured 59-package, 1,186-name walk, a per-package rule registry with exceptions, an optional-extra import policy, and a sub-700-line budget. Public subpackage names outside contract 3.4 default to documented internal unless explicitly listed. | 1, 4.1, 8, 11, 12, 15 |
| H6 | X0 and S7a are R2 with Dennis then Codex. S7a writes representative artifacts and rejects any `INTERNAL_TAGS` literal in files or `--json`. Zip stages CSV bytes and sets `ZipInfo.file_size`, with a patched `ZIP64_LIMIT` test and no new 2 GiB refusal. | 7, 8, 10.4, 12 |
| M1 | The `when:`-read nullable-integer output change and AT-O1f cover every strategy and every route, including the chunked oracle. | 5.3, 5.5, 8 |
| M2 | O2 states that chunked gzip is a deterministic concatenation of one member per chunk, pins `TextIOWrapper` settings, and guards `.tar`, `.tar.bz2`, `.tar.xz`, `.bz2`, `.xz`, and `.zst`. | 4.3, 8, 10.4 |
| M3 | `RefuseRedirects` moves into `_outbound`; `_update_check` is a purpose caller, not an allowlisted network owner. Notify parsing uses the central scheme rule and notify redirects re-check every hop. G6 excludes engine connectors and third-party libraries. | 1, 4.2, 8, 9, 10.7 |
| M4 | Reciprocal ordering with `plan/output-metadata-leak` rev 3 is explicit. E1 conditionally rides the freeze release, C1 follows O2, and the compatibility-contract route-metadata paragraph has one owner. | 5.6, 10.5, 12 |
| M5 | The golden inventory names testflight fingerprints, parity captures and proof outputs affected by O1/O3, with the same rerun-on-final-head rule as `plan/faker-migrate`. | 5.6, 7, 10.5, 12.1 |
| M6 | AT-O1e checks an exact AST `(path, function)` caller allowlist for both ingestion helpers. Plain `to_pandas()` remains a documented limit, and `_pipeline_full_frame.py:57` stays on its diagnostic path because it has no plan or registry. | 8, 10.6 |
| L1 | The engine has 30 tag literals outside 3.1; `flagged-redacted/v2` and `distribution-snapshot/v2` are already classified there. | 4.2, 5.6, 8 |
| L2 | Zip `external_attr` is fixed explicitly; tar coverage in AT-O2b is labelled a guard. | 8, 10.4 |
| L3 | The import sentry handles `import urllib`, aliased `from urllib import request`, and AST-resolved constants. | 8, 10.7 |
| L4 | The pre-mortem records the memory and conversion cost of forcing NaN-style evaluation for nullable integer `when:` columns. | 14 |

### Revision 3.3 changes

The O3 builder measured that a fixed-schema Parquet sink cannot keep the `origin/main` failure for a later unsplittable value once batch one narrowed its schema to `string`. On pyarrow 24, `ParquetWriter(schema=string).write_batch(<large_string batch>)` raises `ValueError` (schema mismatch), and a cast of the 2 GiB value to `string` raises `ArrowInvalid` outside the file-access guard. Neither matches main. Translating the error by hand is not allowed.

| Change | Closed in |
|---|---|
| A Parquet sink whose writer schema is fixed at construction (out-of-core sink, streamed chunked Parquet sink) keeps the source pass-through `large_string` field as on `origin/main`. Narrow batches are widened back to `large_string` at the sink boundary by copying offsets only. That sink's file bytes and every failure stay identical to main. Narrowing still applies to in-memory results, resident collectors, CSV, and `run_mask_chunked` chunks. | 4 (O3 paragraph), 5.5, 5.6, 7, AT-O3a, AT-O3f |
| AT-O3a: the fixed-schema Parquet sink cells assert `large_string` and byte equality with `origin/main`; every other cell asserts `string`. A new mutation: narrow the fixed-schema sink field, and the 2 GiB parity cell goes red. | 8 |
| Whole-frame Parquet writes (schema built from the complete result) narrow as before, because their schema is chosen after every batch is seen. | 5.6 |

### Revision 3.2 changes

| Finding | Change | Where |
|---|---|---|
| V1 SELF-CHECK | O3 drops the whole-source pre-scan. The first batch sets the initial width. Each later batch uses its total offset span as a fast bound. The helper reads all offsets only to split or detect one unsplittable value. CSV keeps a later unsplittable value as `large_string` without rereading the source. Parquet keeps each `origin/main` writer outcome. Raw and local writers raise `ArrowInvalid`. Strict file-access writers raise `FileAccessReadError`. One width state supplies the data, analytic, and FK types. | 2.1, 4.3, 5.2 to 5.6, 7, 8, 10.3, 12, 14 |
| DESIGN | The outbound-policy sentry moves into the named `C:tests/sentry/io_policy/outbound/` sub-package because `io_policy/` already has 25 direct modules. The Placement row cites the revised CLI CODEMAP row. | 9 |
| V2-LOG | AT-O1a, AT-O1b and AT-O1f assert route evidence. FK and relationship cells that unified admission rejects assert the rejection and the physical fallback route explicitly. | 5.3, 8 |
| V2-LOG | The rules line now names the local profile and every routed architecture, exploration, verification and review rulebook. Every compatibility-changing slice is R2. | top matter, 12 |
| V2-LOG | The metadata-leak citation is rev 3.1 at `176f5cf34`, CLI citations use `f1da00f5`, and S4 updates the durable `FREEZE-SURFACE` row in `docs/roadmap/groups/health.md`. | top matter, 4.2, 9, 10.5 |

## 1. Guarantee and non-goals

Guarantees after this batch:

- G1. Every name in `decoy_engine.__all__`, and every name found by the 59-package, 1,186-name public-subpackage walk, has one rule-derived tier with explicit exceptions: frozen, experimental or documented internal. The tier is keyed by object identity, so one object exported from two places has one tier. A public subpackage name outside contract 3.4 defaults to documented internal unless the registry lists it as frozen or experimental. Optional-extra packages are recorded and skipped only for their named missing extra. Every CLI `_LAZY_API` name has exactly one tier. AT-X0a, AT-X0e and AT-X1a check this. Visible CLI commands and options stay frozen through the existing `C:tests/unit/test_cli_surface.py`; hidden ones get a tier through S2.
- G2. An experimental class or function starts its docstring with the fixed marker; an experimental constant is covered by its module docstring marker. A sentry checks the markers against the registry.
- G3. Hidden CLI options and commands are listed with a tier. A new hidden name fails the build until it is listed.
- G4. Every `"<name>/vN"` tag literal (dots and underscores allowed) in engine and CLI source is classified: frozen format (contract 3.1), frozen determinism label (contract 3.3), or internal with a reason. A new literal fails the build until it is classified. Tags built with f-strings are a known limit.
- G5. The `when:` grammar's keyword literals are all reserved names, and the reserved set is pinned by an exact snapshot.
- G6. Every outbound network call in first-party CLI source goes through one function with a per-purpose scheme and redirect rule, except a short `(path, function)` allowlist. Engine connectors and calls performed inside third-party libraries are outside this CLI guarantee.
- G7. Three output shapes are fixed before the freeze. Integer `when:` comparisons are exact outside the float-exact range. Every route and dtype uses one NaN-style null rule. A compressed CSV target (`.gz`, `.tar.gz`, `.zip`) contains no staging name or wall-clock time. A pass-through `large_string` column becomes `string` when every value fits 32-bit offsets. If a later batch contains one wider value, CSV and resident outputs retain `large_string` without rereading the source. Each Parquet policy mode raises the same class and reason as `origin/main`.

Non-goals:

- No runtime `ExperimentalWarning` (Q2, owner: no).
- No change to the experimental surfaces themselves (no connector SDK entry point, no `load_custom_providers` caller, no `api.scan` port to `scan_sources`). Audit J2 moves to v1+ (Q4, owner: yes).
- No new public name. FREEZE-SURFACE removes or relabels.
- No rename of experimental names (the `decoy_engine.FileSource` and `decoy_engine.config.FileSource` collision is a 1.x candidate).
- No snapshot of every CLI reason code. Only the gate and warning vocabulary is pinned (S4); the rest is a known limit in the CLI map.
- No change to the chosen NaN-style `when:` truth table between routes or column classes after O1. Q10 explicitly permits the pre-GA change from today's `pd.NA` behaviour on FK keys, declared integers, date-shift anchors, `top_code`, and `group_key` siblings.
- Platform: parked. No platform slice.

## 2. Established solutions

| Concern | Established solution | What we take |
|---|---|---|
| Stability tiers | Node.js Stability Index (0 Deprecated, 1 Experimental, 2 Stable, 3 Legacy); PEP 411 provisional packages; Kubernetes alpha, beta, GA; Rust `#[unstable]`; Go `x/exp` | Three tiers: frozen (Stable), experimental (Node 1, PEP 411 provisional), internal. PEP 411: a provisional name may change in a minor release, and the docs say so at the top of the page. |
| Marking a name | optuna and MLflow `@experimental` decorators | The docstring prefix only, driven by one registry per repo. No decorator: mutmut 3.7 skips decorated-class bodies, and a wrapper changes the signature in the API reference. |
| Gate-time tier decision | Kubernetes feature gates graduate at a named release | `decoy library` gets the tier value `gate`; a sentry refuses `gate` once `RELEASE_PHASE == "ga"`. |
| Public surface check | `griffe check`, Typer `utils docs` | Reuse the map sentries and `C:tests/command_tree.py`; `griffe check` stays REL-GATE Q6. |
| Reproducible archives | RFC 1952 (FNAME optional, MTIME 0 means no time); reproducible-builds.org archive guidance (`SOURCE_DATE_EPOCH`, fixed tar mtime, uid, gid, fixed zip `date_time`) | `gzip.GzipFile(filename="", mtime=0)`, `TarInfo.mtime=0` with uid, gid 0 and empty owner names, `ZipInfo.date_time=(1980, 1, 1, 0, 0, 0)`, pinned compression level. |
| Exact integers with nulls | pandas nullable integer dtypes; the DE-10 contract `execution/_fk_keys.py::to_pandas_fk_safe` | One function names the lossless columns for every ingestion site. |
| Three-valued comparison | SQL and pandas `NA` propagate unknown; float `NaN` compares unequal | Use one owner-chosen NaN-style rule for `when:` on every ingestion dtype and route (Q10): a reference evaluator over Python ints with `NaN` for null is the oracle. |
| URL allow list and redirects | OWASP SSRF guidance (allow list, re-check every redirect hop); `urllib.request` `HTTPRedirectHandler.redirect_request` | One function with per-purpose schemes and a per-purpose redirect handler that re-checks the scheme of every hop. |
| Large text output | The [Parquet PLAIN encoding specification](https://parquet.apache.org/docs/file-format/data-pages/encodings/#plain-plain--0) stores a `BYTE_ARRAY` value with a 4-byte length. Arrow maps both `string` and `large_string` to Parquet `BYTE_ARRAY`. PyArrow 24.0.0 rejects a value of 2 GiB or more. CSV has no typed field-width prefix. | Narrow each source batch from its offsets, without decoding text. Do not pre-scan or reread the source. Preserve the Parquet writer failure for an unsplittable value. Retain that batch as `large_string` for CSV. |

### 2.1 O3 writer experiment

The check used engine `origin/main` `ad36687a6` and CLI `origin/main` `f1da00f5`. The Parquet paths use the file-access adapter and the CLI Parquet calls. The CSV paths call `generated_table_to_pandas` and then `DataFrame.to_csv`. CSV has no Arrow schema or 32-bit field length on disk. Arrow IPC is only an intermediate format. It is not a supported final output.

The experiment ran in `/tmp/freeze-o3-pyarrow-uvvenv`. It used Python 3.10.20, PyArrow 24.0.0, and pandas 2.3.3 from the `origin/main` lock. The script built one `large_string` row over a sparse 2 GiB mmap. Thus, it used virtual backing instead of 2 GiB of resident memory. It also read an ordinary offsets buffer and wrote a normal `large_string` CSV control. The temporary script was deleted after capture. It ran as `/tmp/freeze-o3-pyarrow-uvvenv/bin/python o3_width_experiment.py`.

```text
python=3.10.20
pyarrow=24.0.0
pandas=2.3.3
offset_probe=offset_bytes:40,values_bytes:6,max_value_bytes:3
oversize_array=type:large_string,rows:1,offset_bytes:16,values_bytes:2147483648
parquet=pyarrow.lib.ArrowInvalid:Parquet cannot store strings with size 2GB or more, got: 2147483648
csv_control=WRITE_SUCCEEDED:17_bytes
```

A follow-up passed the same sparse table through the actual `origin/main` file-access adapter in both policy modes:

```text
adapter_strict_False=pyarrow.lib.ArrowInvalid:Parquet cannot store strings with size 2GB or more, got: 2147483648
adapter_strict_True=decoy_engine.fileaccess._types.FileAccessReadError:file could not be read: target
```

Conclusion: Parquet cannot store the value on `origin/main`. A row split cannot change this because one value is one `BYTE_ARRAY`. CSV can store the value because its format and writer have no 32-bit field length. A real 2 GiB CSV cell still needs sufficient memory and I/O. O3 preserves this CSV case without a source pre-scan. For Parquet, O3 preserves the raw/local and strict-adapter errors. It does not add an engine refusal.

## 3. Reuse inventory

| Need | Existing piece | Path |
|---|---|---|
| Engine frozen map and sentry | RG-F1 map, `OTHER_SURFACES`, one-row rule | `docs/frozen-surfaces.md`, `tests/sentry/release/test_frozen_surface_map.py` |
| CLI frozen map and sentry | RG-F2 map, `findings(text)` | `C:docs/release/frozen-surfaces.md`, `C:tests/sentry/release/test_frozen_surface_map.py` |
| CLI public names | `_LAZY_API` | `C:src/decoy/__init__.py` |
| CLI command tree | `walk`, `visible_paths`, `registry` | `C:tests/command_tree.py` |
| Retired names | residual-name sentry | `C:tests/sentry/release/test_retired_name_residual.py` |
| Contract tag block | contract 3.1 code block | `docs/compatibility-contract.md` |
| Reserved `when:` names | `RESERVED_NAMES` | `src/decoy_engine/expressions/_when_parser.py:55` |
| Lossless int ingestion | `to_pandas_fk_safe`, `fk_columns_for_table` | `src/decoy_engine/execution/_fk_keys.py:314`, `:301` |
| Predicate eval | `_eval_predicate` | `src/decoy_engine/execution/_when_gate.py:115` |
| Text narrowing | `narrow_text` | `src/decoy_engine/_arrow_types.py:22` |
| Chunked output schema | `build_schema_rule` passthrough branch | `src/decoy_engine/execution/native/_chunked_schema_rule.py:294` |
| Out-of-core pass-through | `passthrough_array` | `src/decoy_engine/kernel/_scalar.py:36` |
| Final output writers | Parquet through policy-issued file handles. CSV through pandas text output. | `src/decoy_engine/fileaccess/adapters/arrow.py:97`, `C:src/decoy/cli/io/_targets.py:381`, `:412`, `:506` |
| CSV compression option | `csv_compression`, `split_compression` | `C:src/decoy/cli/io/_compression.py:44` |
| Redirect refusal | `RefuseRedirects` | `C:src/decoy/_update_check.py:60` |
| OTel endpoint rule | `validate_endpoint` | `C:src/decoy/telemetry.py:93` |
| Shape changelog check | `check_shape_changelog.py` (REL-GATE G3) | `C:scripts/release/check_shape_changelog.py` |
| Changelog fragments | Breaking and Removed fragments | `changelog.d/README.md` |

No new module is added under `src/decoy_engine/execution/` (104 direct Python modules today; the CODEMAP fan-out freeze is not raised).

## 4. Behaviour

### 4.1 EXPERIMENTAL-TIER

Contract text (new section 3.6 "Experimental surfaces" in `docs/compatibility-contract.md`, mirrored in `C:docs/release/versioning.md`):

1. A surface is frozen, experimental or internal. Frozen follows sections 3.1 to 3.5 and section 4. The engine registry is rule-based per package, with a short exception table. Names in packages named by contract 3.4 follow that contract; names in other public subpackages default to documented internal unless an exception lists them as frozen or experimental. Internal names may change in any release, but no name is unclassified: a name must match exactly one package rule or exception. CLI internal names start with `_` or have an explicit row.
2. An experimental surface may change or be removed in any minor release. The change gets a `Changed` or `Removed` fragment that starts with "Experimental:". No deprecation window is promised.
3. Determinism is never experimental. Output bytes produced through an experimental surface (a custom provider's values, a connector's rows once masked) follow section 3.3. Stored records are never experimental: everything under `.decoy/` is frozen whatever the tier of the command that wrote it.
4. An experimental class or function starts its docstring with `Experimental:`. An experimental constant has no docstring of its own; its module docstring starts with the marker and names it. The doc page has the marker in its first paragraph.
5. An experimental surface becomes frozen by moving its registry row and removing the marker, in a minor release. It never goes from frozen back to experimental inside a major.
6. A tier belongs to an object, not to a name. The census resolves each exported name to its object; the same object exported from two modules has one tier. The walk imports all 59 public packages and classifies all 1,186 exported names. An optional-extra package may raise `ImportError` only for its registered missing dependency, for example `providers_v2.mimesis` without the `mimesis` extra; the census still classifies its statically declared names and fails on any other import error.

The 1.0 tier lists (owner Q1 answered yes):

| Repo | Experimental | Stays frozen |
|---|---|---|
| engine | connector SDK: `sdk.__all__` objects defined in `sdk.py` (`FileSource`, `FileSink`, `ConnectorConfig`, `FileMeta`, `CheckResult`, `WriteResult`, `TransientError`, `PermanentError`, `SDK_VERSION`, the `CAP_*` flags), and the same objects re-exported at the root (`src/decoy_engine/__init__.py:295`) | `ConfigError` and `ConnectorError`: `sdk` re-exports them from `decoy_engine.errors`, so they are `errors.*` objects and stay frozen |
| engine | provider registration: `register_faker_provider`, `register_faker_provider_v2`, `register_faker_list_provider`, `unregister_faker_provider`, `load_custom_providers`, `atomic_swap_db_providers` | `ProviderRegistry`, `ProviderSpec`, `ProviderError`, `get_default_registry`, `list_generate_faker_providers`, `BackendAdapter`, `AdapterError`, `CapabilityMatrix` |
| CLI | Python API: `mask`, `scan`, `MaskSecretConfigError`, `ConfigValidationError`, `UnsupportedCloudEndpointError` | - |
| CLI | `decoy library` command group: tier `gate`, decided at REL-GATE G0 by the Q3 rule | `.decoy/` record formats |

Contract section 1 gets a "Pre-GA corrections taken with the freeze batch" entry. It lists the names that move from implicitly frozen (section 3.4 named `sdk.py` and `providers.py`) to experimental, the S1 removal, and the O1 to O3 output changes.

### 4.2 FREEZE-SURFACE

1. S1 (engine): delete `internal/base.py` and `transforms/base.py`. `FormulaStrategy` becomes a plain class with a module logger. Its class name, method name and module path stay, because the draw-site label `transforms/formula.py::FormulaStrategy.apply` (`src/decoy_engine/execution/native/_draw_sites_mask.py:375`) and two secret-material census rows name it. `transforms.__all__` becomes empty. Remove the `pyproject.toml:549` ruff entry and the `pyproject.toml:1019` mypy entry for `internal/base`. A `Removed` fragment names `BaseMaskingStrategy`.
2. S2 (CLI): delete demo `--ref` and `--rows` (`C:src/decoy/cli/demo.py:554`) and the never-called `_generate_ref_datasets` (`C:src/decoy/cli/demo.py:401`). `decoy demo --ref` moves from exit 1 (deferral) to exit 2 (no such option); Q8 answered yes. A new hidden-name sentry lists every hidden command and option with a tier: internal (`_scan`, `_gate`) or frozen-hidden (`upgrade --url`, `ci --unsafe-debug-log`).
3. J2: moved to v1+ (Q4). No slice.
4. S4 (CLI): rename `layout.report_source_ambiguous` (`C:src/decoy/cli/io/_layout_errors.py:159`) to `report.source_ambiguous` (Q5). The descriptor stays in `_layout_errors.py`, the one descriptor module, in a new `REPORT_DESCRIPTORS` tuple that joins `GATE_DESCRIPTORS`. Exact snapshot of `GATE_CODES`, `WARNING_CODES` and `_CLI_GATE_CODES`. S4 updates the durable `FREEZE-SURFACE` row in `C:docs/roadmap/groups/health.md` to say the gate and warning set is pinned and the rest stays a known limit.
5. S5 (engine): add `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith`, `endswith` to `RESERVED_NAMES` (Q6). Case policy: reserved names match exactly, case-sensitive, as `_name()` does today (`src/decoy_engine/expressions/_when_parser.py:116`); only the lowercase forms are reserved, so a column named `NULL` or `Between` stays a column. A sentry checks that every keyword literal in `when_grammar.lark` is a reserved name (a guard: green today), and an exact snapshot pins the set.
6. S6 (CLI): one outbound function `C:src/decoy/_outbound.py::open_url(url, purpose)`. Purposes and rules are in 10.7 (Q7). `RefuseRedirects` moves from `C:src/decoy/_update_check.py:60` into `_outbound`, so `_update_check` is only the caller for purpose `update_check`, not an allowlisted network owner. The `urlopen` sites (`C:src/decoy/cli/upgrade.py:55`, `C:src/decoy/distribution/installer.py:250`, `C:src/decoy/notify.py:254`, `C:src/decoy/notify.py:319`) call the choke point, and telemetry's `validate_endpoint` (`C:src/decoy/telemetry.py:93`) becomes the `otel` purpose's rule. Notify URLs come from `--notify kind:target`, so `parse_notify_spec` calls the same `_outbound` scheme-policy function used immediately before opening. `notify_webhook` and `notify_slack` re-check every redirect hop against that purpose. Every `NotifySpecError` message becomes value-free (today `C:src/decoy/notify.py:128` echoes the whole spec, which can hold a webhook token).
7. S7 (engine, then CLI): a "Public renames before 1.0" table in contract section 1 (the detection taxonomy renames), and a tag census in each repo with the regex `"[a-z][a-z0-9._-]*/v[0-9]+"`. The engine has 30 tag literals outside the 3.1 block; `flagged-redacted/v2` and `distribution-snapshot/v2` are already in 3.1 and are not counted again. Each remaining literal is classified by the rule in 5.6.

### 4.3 FREEZE-OUTPUT

1. O1 (engine), decided by Q10: a `when:` predicate uses one NaN-style rule regardless of ingestion dtype. A blank row is selected by `!=`, by `not (...)` around a comparison that is false for the blank, and by `not in`; it is not selected by `==`, `<`, `<=`, `>`, `>=`, or `in`. `and` and `or` follow that same operand table. This applies to plain columns and to columns currently ingested as pandas `Int64` with `pd.NA`: FK keys, declared integers, date-shift anchors, `top_code`, and `group_key` siblings. The difference for those five classes is a Breaking changelog entry. The `when:` eval frame is built by one function `when_eval_frame(frame, refs, literals)` in `_when_gate.py`, after ingestion and before evaluation on every route. A referenced integer column takes the Python-object path when any non-null value is outside `[-2**53, 2**53]`. It also takes that path when any compared integer literal is outside the range. The literal rule applies when the current chunk contains only in-range values and when the chunk size is 1. Every comparison between an int64 column and a float literal takes the object path. It never depends on float64 rounding. Object columns contain Python ints and `NaN` for blanks, never `pd.NA`, and use the pandas Python engine. Other referenced nullable integer columns are converted to float64 with `NaN` solely for evaluation. The result equals the uniform reference evaluator on every chunking.
2. O1 ingestion: one function `lossless_int_columns(plan, registry, graph) -> dict[str, set[str]]` in `src/decoy_engine/execution/_fk_keys.py` returns the union every site builds by hand today (FK keys, date-shift anchors, `top_code`, `group_key` siblings, and declared integers) plus integer columns any `when:` reads. Six direct ingestion sites use it: `src/decoy_engine/execution/_pandas_adapter.py:214`, `_sequential.py:422`, `_chunked_carry.py:215`, `_unified_slice_admission.py:364`, `native/_when_mask.py:58`, and `native/_faker_null_mask.py:81`. The unified-slice frame then reaches `compute_when_masks` at `_unified_slice.py:244`. `_faker_null_mask.py` widens its existing protected set with `lossless_int_columns`, rather than replacing its positional-Faker rule. Indirect diagnostic callers `_chunked_oracle.py:465` and `_chunked_carry.py:143` use the same set. `_pipeline_full_frame.py:57` remains a diagnostic-only allowlist entry because it has no plan or registry and converts one column to attribute an existing failure. Second output change: any null-bearing integer column read by `when:` and passed through is written as `int64` instead of `double` for every strategy and route, including `run_mask_pipeline_chunked`'s oracle at `_chunked_oracle.py:195`. Flag-on and flag-off runs have identical values, types, nullability, and metadata.
3. O2 (CLI): compressed CSV targets are written through one function in `C:src/decoy/cli/io/_compression.py`, used by `C:src/decoy/cli/io/_targets.py:405` and `write_chunked_output` at `:543`. Every text layer is `io.TextIOWrapper(binary, encoding="utf-8", newline="")`. `.gz`: `gzip.GzipFile(fileobj=tmp, mode="wb", filename="", mtime=0, compresslevel=9)`. The non-chunked path has one member; `write_chunked_output` preserves today's exact shape of one gzip member per CSV chunk, concatenated in chunk order, with the fixed header on each member. `.tar.gz`: the same gzip wrapper around `tarfile.open(fileobj=..., mode="w|")` with one `TarInfo(name=member, mtime=0, mode=0o644, uid=0, gid=0, uname="", gname="")`. `.zip`: stage the complete CSV first, set `ZipInfo.file_size` to the staged byte count before `ZipFile.open`, fix `date_time`, `external_attr`, compression type, and compression level, then copy the staged bytes. This lets `zipfile` choose the ZIP64 header before data and adds no refusal beyond 2 GiB. `.bz2`, `.xz`, and `.zst` remain on their existing writers; `.tar`, `.tar.bz2`, and `.tar.xz` remain unchanged. Claim: two runs give byte-identical files for the same input, Decoy version and compression-library build.
4. O3 (engine): a pass-through `large_string` column becomes `string` when its values fit 32-bit offsets. O3 does not pre-scan the source. One stateful helper in `src/decoy_engine/_arrow_types.py` observes batches in source order. The first batch sets the provisional width. Each ordinary batch needs two 64-bit offset reads. A larger batch needs a scan of its offsets. This scan selects row boundaries and detects an unsplittable value. It does not decode or copy payload bytes. Individually narrowable rows return ordered `string` slices. A later unsplittable value promotes the state to `large_string`. Resident collectors widen prior `string` chunks by copying offsets only. The CSV path writes the retained `large_string` batch directly. Neither path rereads the source. Parquet cannot store the value. Raw and local writes raise the same `ArrowInvalid` as `origin/main`. A strict file-access write raises the same `FileAccessReadError`. O3 adds no earlier engine refusal. The passthrough branch in `normalize_chunk` (`execution/native/_chunked_schema_rule.py:331`) and `passthrough_array` use the shared state. `_safe_cast` at `execution/native/_chunked_schema_rule.py:308` stays a generic wrapper. `masked_output_type` (`execution/out_of_core/_mask.py:248`) and the two FK resolvers use the same state. Thus, the data, analytic, parent, and child types stay aligned. `mask_batch` splits record batches at the returned row boundaries. It preserves order, nulls, and every non-text column. Contract 3.4 records the narrow, promotion, and Parquet error rules.

## 5. Enumerations

### 5.1 Callers and consumers of what changes

- Tier registry (engine): the map sentry, the marker sentry, the docs build. No runtime caller.
- `FormulaStrategy`: `src/decoy_engine/execution/_strategies/_formula.py:18`, the draw-site label at `src/decoy_engine/execution/native/_draw_sites_mask.py:375`.
- `REPORT_SOURCE_AMBIGUOUS`: raised at `C:src/decoy/cli/_sources.py:335`, exported at `C:src/decoy/cli/io/__init__.py:78`, tested at `C:tests/e2e/config_explicit/test_config_explicit_reports.py:230`.
- Outbound: the four `urlopen` sites; `C:packaging_tools/smoke_install.py:290` (the upgrade document and its `file://` artifact URLs); `C:src/decoy/telemetry.py:93`.
- `when:` frame: `src/decoy_engine/execution/_when_gate.py:248`, `src/decoy_engine/execution/native/_when_mask.py:59`, `src/decoy_engine/execution/_unified_slice_when.py:88`, and unified-slice `compute_when_masks` at `src/decoy_engine/execution/_unified_slice.py:244` after admission converted the source at `_unified_slice_admission.py:364`.
- Lossless ingestion: the six direct sites and two indirect diagnostic callers in 4.3 item 2. `_pipeline_full_frame.py:57` is the diagnostic-only exception.
- O3 width state: `native/_chunked_schema_rule.py::normalize_chunk`, `kernel/_scalar.py::passthrough_array`, `out_of_core/_mask.py::masked_output_type` and `mask_batch`, `_pipeline_routing_fk_dtype.py`, and `out_of_core/_batch_join.py::_resolve_output_types`. Final consumers are the resident collector, the Parquet sink through `fileaccess/adapters/arrow.py`, and the CLI CSV loop in `C:src/decoy/cli/io/_targets.py::write_chunked_output`.

### 5.2 Exit paths

| Path | Before | After | Test |
|---|---|---|---|
| `decoy demo --ref` | exit 1, deferral message | exit 2, Click usage error | AT-S2a |
| `decoy upgrade --url ftp://x` | urllib error, exit 3 | exit 1, `url_scheme_refused` | AT-S6b |
| `--notify webhook:file:///etc/passwd` | file read, "sent" | exit 1 at option parse, `notify_url_scheme_refused`, value-free | AT-S6c |
| upgrade artifact redirected https to http | followed | exit 3, `url_redirect_refused` | AT-S6e |
| `when:` naming a column `null` | ran | exit 1, `when_outside_closed_grammar` | AT-S5b |
| report with an ambiguous `--source` | exit 1, `layout.report_source_ambiguous` | exit 1, `report.source_ambiguous` | AT-S4a |
| compressed target write fails mid-stream | old output kept | old output kept | AT-O2c |
| pass-through text over 2 GiB in one batch, with every value narrowable | written as `large_string` | offset-only row split writes ordered `string` slices, no refusal or source reread | AT-O3e |
| one pass-through text value over the 32-bit-offset limit | CSV writes the value. Local Parquet raises `ArrowInvalid`. Strict file-access Parquet raises `FileAccessReadError`. | CSV retains that batch and promotes resident output to `large_string` without rereading. Each Parquet mode raises its same class and reason. Analytic and FK types agree up to the writer. | AT-O3f |

No exit integer changes meaning.

### 5.3 Routes

| Route | O1 (`when:` frame and ingestion) | O3 (pass-through type) |
|---|---|---|
| whole-frame (`run_pipeline`) | `_pandas_adapter.py` ingestion; `_when_gate.py` uniform frame | resident helper observes existing chunks; promotes retained chunks without rereading source |
| sequential | `_sequential.py` ingestion; `_when_gate.py` uniform frame | first batch plus per-batch offset bounds; CSV may promote, Parquet retains writer parity |
| `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:382`) | `_chunked_oracle.py` through adapter; `_when_gate.py` uniform frame | first batch plus per-batch offset bounds; no iterator replay |
| `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:589`) | `_when_mask.py`; Faker null masks use the widened set | `_chunked_schema_rule.py::normalize_chunk` observes the shared width state for each batch and applies returned row slices |
| unified slice | `_unified_slice_admission.py:364` ingestion, then `_unified_slice.py:244` and `_unified_slice_when.py:88`; flag-on/off parity required | resident helper observes produced batches; no source pre-scan |
| out-of-core FK | no `when:` (rejected at plan time) | `passthrough_array`, `masked_output_type`, FK resolver, and `mask_batch` observe one shared per-table state before each batch |
| full-frame mixed route diagnosis | `_pipeline_full_frame.py:77` | n/a |

Known limit: there is no route registry, so AT-O1a and AT-O3a carry the route list as a constant in the test module, with a map row that says so. A new route must add itself; the same limit applies to the other route-parametrized suites.

AT-O1 route cells assert a route-owned production witness before checking values or schemas. The unified cell requires `quality_metrics["unified_slice_activation"]`; chunked cells require their `chunked_route` or `auto_chunk` evidence; other cells use their existing route result or a route-owned call recorder. A requested unified FK or relationship job is not labelled unified: the test asserts that `unified_slice_activation` is absent, asserts the unified refusal record, and asserts `quality_metrics["execution"]["execution_mode"] == "full_frame"`, the physical fallback that handled the job.

### 5.4 FK shapes

- An FK key column read by `when:`: already lossless at ingestion; `when_eval_frame` treats it like any integer column. AT-O1d.
- An FK key column passed through as `large_string`: each parent and child batch is observed before its join type is selected. Narrowable batches use `string`; an unsplittable value promotes the shared per-table state and retained resident chunks to `large_string`. Parent, child, analytic, and emitted types use that state. A Parquet write of the unsplittable value still fails after the aligned join exactly as on `origin/main`. AT-O3b and AT-O3f.
- No other FK shape is touched.

### 5.5 Fields

| Field | Change | Where |
|---|---|---|
| reason `layout.report_source_ambiguous` | renamed `report.source_ambiguous` | `--json` error `code`, CI report |
| reasons `url_scheme_refused`, `url_redirect_refused`, `notify_url_scheme_refused` | added | `--json` error `code` |
| Arrow type of pass-through text | `large_string` to `string` batch slices when values fit 32-bit offsets. A later wider value promotes resident and CSV output to `large_string` without a source reread. Parquet keeps its existing 2 GiB writer failure. A Parquet sink whose schema is fixed at construction (out-of-core, streamed chunked) keeps `large_string` exactly as `origin/main` (revision 3.3). | In-memory and whole-frame Parquet schema. CSV text is type-free. |
| Arrow type of any null-bearing integer column read by `when:` and passed through | `double` to `int64` where a route or strategy widened it; source `int64` retained everywhere | Parquet schema, CSV text (`5` instead of `5.0`) |
| `when:` blank-row selection for FK keys, declared integers, date-shift anchors, `top_code`, and `group_key` siblings | pandas `pd.NA` route-dependent selection to the uniform NaN-style table | selected rows on every route; Breaking entry names all five classes |
| gzip header FNAME and MTIME; tar member mtime, uid, gid, names; zip entry `date_time` | removed or fixed | compressed output bytes |
| registry tier per public object | added | docs, both maps |

### 5.6 Output surfaces

- Parquet schema and CSV text of the routes in 5.3 (O1, O3). For O3, CSV converts each batch independently to text. Thus, it accepts a later unsplittable batch. Parquet fixes its schema at writer construction, so a fixed-schema Parquet sink keeps the source `large_string` field and widens narrow batches back at the sink boundary (revision 3.3). Its file bytes and each `origin/main` failure for one 2 GiB value stay unchanged. Whole-frame Parquet output narrows, because its schema is chosen after every batch.
- Compressed CSV bytes (O2).
- Rows selected by `when:` on integer columns when a value or integer literal is outside `[-2**53, 2**53]`, for int64-to-float-literal comparisons that cannot be proved exact, and for blanks in the five formerly `pd.NA` classes (O1).
- `--json` error `code` (S4, S6).
- Docs: contract sections 1, 3.1, 3.3, 3.4 and new 3.6; both frozen maps; `C:docs/release/versioning.md`; the SDK, provider and Python API pages.
- Tag classification. The rule (Q9 answered yes, and the answer covers the builder's reclassifications under this rule): a tag that reaches disk, `--json`, a signed or hashed record, or a derivation input is frozen; a tag that never leaves the process is internal and needs a one-line reason. Frozen tags that name a file or record format go in the 3.1 block with a map row and a pinning test that reads the tag from the written artifact; frozen tags that are derivation labels go in a new 3.3 list, pinned by the existing determinism goldens. The S7a artifact sentry runs the writer fixtures for every `INTERNAL_TAGS` owner and scans every resulting file plus captured `--json`; no internal-tag literal may appear. Proposed, for the S7 builder to check at each write site: frozen formats `decoy-publication/v1`, `publication/v1`, `pinned-plan/v1`, `pinned-plan-fingerprint/v1`, `decoy-safe-output/v1`, `decoy-quarantine/v1`, `decoy-support-bundle/v1`, `decoy-reasons/v1`, `checkpoint-index/v1`, `decoy-resume-key-check/v1`, `decoy-model-pack/v1`, `dps-marginal/v3`, `post-scan-integrity/v2`, `canary-span-report/v1`, `flagged-redacted/v1`, `decoy.evidence.statement/v1`, `decoy.trust-policy/v1`, `decoy.required-catalog/v1`, `immutable_directory/v1`; frozen derivation labels `fpe-key/v1`, `tokenize-key/v1`, `secret-provider/v1`, `decoy.shuffle.unkeyed/v1`, `name_email/v1`, `canary-span-normalization/v1`, `policy-expansion/v1`; internal candidates `phase-result/v1`, `phase-event/v1`, `decoy-probe/v1`, `decoy-telemetry/v1`. `flagged-redacted/v2` and `distribution-snapshot/v2` are already in 3.1. The builder's census output is the final list; the count outside 3.1 today is 30.
- Golden inventory for O1 and O3: `testflight/golden_fingerprints.json` entries `a_healthcare_claims`, `b_retail_m2m`, `c_hr_selfref`, `d_longitudinal_visits`, `e_hostile_edge_cases`, and `f_tokenize_vault` are expected unchanged because their fixtures contain neither the changed `when:` integer-null shapes nor pass-through `large_string`. O1 parity captures in `tests/parity/_f0_expected.py` and FR0 refreeze data are expected unchanged but are rerun. O3 moves the exact type signatures in `tests/parity/test_phase_d_dcomp_composite_ooc.py::test_g7_large_string_parent_component_keeps_its_width_out_of_core_only`; its tool-owned replacement is reviewed with any resulting `tests/fileaccess/route_corpus_golden.json` and `tests/native/_c8_iii_a_main_goldens.json` hash moves. `docs/proof-manifest.json` moves because O1/O3 change tracked source and test files; `scripts/gen_proof_manifest.py` owns it. `docs/capability-matrix.md` is expected unchanged and is regenerated by `scripts/gen_capability_matrix.py` to prove that. The build record gives moved or unchanged for every listed item. After FREEZE-OUTPUT, `plan/faker-migrate` S2, or GEN-PROVIDERS E#661 changes the shared head, whichever lands later reruns every owning tool from faker-migrate section 5.6 plus these O1/O3 parity and proof owners, and `git status` must stay clean.

## 6. Frozen contracts

- `docs/compatibility-contract.md`: section 1 (renames table; "Pre-GA corrections taken with the freeze batch"), 3.1 (tag block grows), 3.3 (derivation label list), 3.4 (CLI line and the pass-through sentence), new 3.6.
- `docs/frozen-surfaces.md` and `C:docs/release/frozen-surfaces.md`: tier rows; new rows for hidden CLI names, the reserved-name snapshot, the gate code snapshot, the route-list known limit, the f-string tag known limit.
- `C:docs/release/versioning.md`: "Public surface" gains an "Experimental" list.
- Reason registries: one rename and three additions (CLI).
- Output bytes: O1, O2, O3, each with a `Breaking:` fragment and a shape-changelog entry, so `check_shape_changelog.py` passes at REL-GATE G3. S1 has a `Removed:` fragment.
- Must not change: the draw-site label and census rows of `FormulaStrategy.apply` (AT-S1b); after O1, the uniform `when:` selection table for blanks and exact integer comparisons on every route and column class (AT-O1b and AT-O1c).

## 7. Failure modes

| Id | Failure | Guard |
|---|---|---|
| F1 | A public name added later has no tier | census: each public object has exactly one tier (AT-X0a, AT-X0e, AT-X1a) |
| F2 | An experimental docstring loses its marker | marker sentry (AT-X0b, AT-X1b) |
| F3 | `decoy library` ships with tier `gate` | AT-X1c |
| F4 | S1 changes the formula call site or output | AT-S1b |
| F5 | A hidden option is added after 1.0 without a decision | AT-S2b |
| F6 | A real lowercase column called `true` or `like` is refused | Q6 answered yes; the refusal says to rename; Breaking fragment |
| F7 | `file://` refused on upgrade breaks the release smoke | `file` allowed for `upgrade_document` and `upgrade_artifact`; AT-S6a uses the smoke's call shape |
| F8 | A new network call bypasses the choke point | import-based sentry (AT-S6d) |
| F9 | GitHub release downloads stop working because the CDN redirect is refused | `upgrade_artifact` follows https-to-https redirects; AT-S6e |
| F10 | O1 uses `pd.NA` on one route or column class and selection diverges | Q10 uniform NaN-style semantics; AT-O1b per-route, per-class matrix over every operator |
| F11 | The ingestion column sets drift apart again | `lossless_int_columns` plus AT-O1e |
| F12 | O2 drops the atomic staging | the writer runs inside the staging context; AT-O2c |
| F13 | O3 refuses or corrupts a total payload over 2 GiB whose rows are narrowable. O3 can also reduce throughput by pre-scanning the source. | Per-batch offset bound and split-then-narrow. One-shot iterator and payload-buffer tripwire in AT-O3e. |
| F14 | A tag classified internal reaches disk | the rule in 5.6; S7 builder checks each write site |
| F15 | FAKER-MIGRATE and this batch both move goldens and one overwrites the other | order in 10.5; the second to land reruns the golden tools on its own head |
| F16 | A large integer literal rounds even though the current chunk contains only small values | literal-aware object-path rule; AT-O1b and AT-O1c chunk-size-1 cell and mutation |
| F17 | An internal tag reaches an artifact or `--json` | S7a writer-fixture artifact scan rejects every `INTERNAL_TAGS` literal |
| F18 | Zip crosses the ZIP64 threshold after a streaming header was chosen | stage CSV, set `ZipInfo.file_size`, and test with patched `ZIP64_LIMIT` |
| F19 | A later batch has one value that cannot fit 32-bit offsets. CSV can refuse it. Resident output can fail to promote. Parquet can change its existing failure. Analytic and FK types can disagree. | One monotonic shared width state. CSV and resident promote without source replay. Parquet main-to-head parity. AT-O3f. |

## 8. Acceptance tests (red first)

| Id | Test | Red because | Mutation | Slice |
|---|---|---|---|---|
| AT-X0a | every object in `decoy_engine.__all__` has exactly one tier, keyed by identity; root re-exports of sdk objects share the sdk tier | no tiers | give `decoy_engine.FileSource` a second tier row | X0 |
| AT-X0b | every experimental class or function has a docstring starting with `EXPERIMENTAL_MARKER`; every experimental constant's module docstring starts with it and names the constant | no markers | drop the marker from `register_faker_provider` | X0 |
| AT-X0c | the registry equals the map's tier rows, both ways | no registry | add a name to the map only | X0 |
| AT-X0d | contract section 3.6 lists the same experimental names as the registry | no section | delete one name from 3.6 | X0 |
| AT-X0e | census: the real walk finds at least 59 public packages and 1,186 names; each name matches exactly one per-package rule or explicit exception; `decoy_engine.sdk` is included; a fixture optional package that raises its registered missing-extra `ImportError` is classified statically, while a different `ImportError` fails | no census | skip one package in the walk; separately change the `providers_v2.mimesis` missing dependency name | X0 |
| AT-X0f | `ConfigError` and `ConnectorError` reached through `sdk` are frozen | no identity rule | tier by name instead of object | X0 |
| AT-X1a | every `_LAZY_API` name is in exactly one tier row | no tier | drop `scan` from the experimental row | X1 |
| AT-X1b | `mask`, `scan` and the three error docstrings start with the CLI marker | no marker | remove the marker from `ConfigValidationError` | X1 |
| AT-X1c | `library` tier is one of `frozen`, `experimental`, `gate`; `gate` fails when `RELEASE_PHASE == "ga"` | no rule | let `gate` pass in ga | X1 |
| AT-S1a | `decoy_engine.internal.base` and `decoy_engine.transforms.base` do not import; `transforms.__all__ == []`; `pyproject.toml` has no `internal/base` entry | modules exist | keep `BaseMaskingStrategy` export | S1 |
| AT-S1b | the draw-site label and both census rows resolve to a live `FormulaStrategy.apply`; formula golden output unchanged | guard: green before and after | rename `apply` | S1 |
| AT-S2a | `decoy demo --ref` exits 2 with "No such option"; `_generate_ref_datasets` is gone | option exists | keep `--ref` hidden | S2 |
| AT-S2b | the hidden commands and options from `walk()` equal the map's hidden-names row, each with a tier; the walk finds at least the four known names | no sentry | add a hidden option to `run` | S2 |
| AT-S4a | the ambiguous `--source` error carries `report.source_ambiguous` in `--json` | old code | restore the old string | S4 |
| AT-S4b | exact snapshot of `GATE_CODES`, `WARNING_CODES`, `_CLI_GATE_CODES` | no snapshot | add a descriptor without the snapshot | S4 |
| AT-S5a | guard: every quoted keyword in `when_grammar.lark` is in `RESERVED_NAMES` (green today; turns red when a keyword is added to the grammar only) | guard: green today | add `"between"` to the grammar only | S5 |
| AT-S5b | `when: "null > 1"` and `when: "like == 1"` are refused with `when_outside_closed_grammar`; `when: "NULL > 1"` reads column `NULL` | names not reserved | reserve case-insensitively | S5 |
| AT-S5c | exact snapshot of `RESERVED_NAMES` | no snapshot | remove `match` | S5 |
| AT-S6a | `open_url("file:///tmp/v.json", purpose="upgrade_document")` opens; the same URL with `purpose="notify_webhook"` refuses | no choke point | allow `file` for every purpose | S6 |
| AT-S6b | `decoy upgrade --url ftp://x --json` exits 1 with `url_scheme_refused`, opens no socket, and the message holds no URL | no check | skip the check for upgrade | S6 |
| AT-S6c | `--notify webhook:file:///x` exits 1 with `notify_url_scheme_refused`; `--notify slack:http://x` is refused; no `NotifySpecError` message contains the spec text | no check, spec echoed | echo the spec in the message | S6 |
| AT-S6d | AST import sentry over `C:src/`: no function outside the exact `(path, function)` allowlist owns a first-party network call. It resolves aliases and module string constants and covers `import urllib`, `import urllib.request as r`, `from urllib import request as r`, `from urllib.request import urlopen as u`, and the other 10.7 spellings | four direct sites | `import urllib` then `urllib.request.urlopen(...)` in `notify.py`; separately bind a module constant for `import_module` | S6 |
| AT-S6e | `upgrade_artifact`: a local test server redirects https to https, followed; https to http, refused with `url_redirect_refused`; `update_check` refuses every redirect through `_outbound.RefuseRedirects`; `notify_webhook` and `notify_slack` preserve their allowed hops but re-check each one | no per-purpose rule | follow a notify redirect to a disallowed scheme | S6 |
| AT-S6f | the `otel` purpose refuses exactly what `validate_endpoint` refuses today (table-driven from its current tests) | guard | drop the header rule | S6 |
| AT-S7a | engine tag census: every literal matching `"[a-z][a-z0-9._-]*/v[0-9]+"` under `src/` is in 3.1, the 3.3 label list, or `INTERNAL_TAGS` with a reason; the base has 30 outside 3.1 | 30 unlisted | add a new tag literal | S7 |
| AT-S7b | CLI tag census: same rule over `C:src/` and the CLI map | no sentry | add `"x.tag/v1"` | S7 |
| AT-S7c | each new 3.1 tag has a map row and a pinning test that reads it from a written artifact | no rows | drop one map row | S7 |
| AT-S7d | contract section 1 renames table lists every pair of the taxonomy map, and each old name is in the retired-name residual list | no table | drop `run_storm` | S7 |
| AT-S7e | artifact-scan sentry runs the writer fixtures for every `INTERNAL_TAGS` owner and asserts no internal-tag literal occurs in any written file or captured `--json`; each fixture proves it wrote at least one artifact | no artifact proof | write one internal tag into a fixture's JSON output | S7 |
| AT-O1a | for every route in 5.3: an integer column holding `2**53`, `2**53 + 1` and a blank; `when: "id == 9007199254740993"` selects exactly one row; flag-on and flag-off results have equal values, type, nullability, and metadata. Before those assertions, each cell checks the route-owned production witness from 5.3 and therefore proves which physical route ran. Its FK-key and relationship variant requested with unified enabled asserts unified rejection, absence of `unified_slice_activation`, the unified refusal record, and `execution_mode == "full_frame"` | float64 rounding selects two; a requested route can silently fall back without proof | skip the object path in `when_eval_frame`; separately make the route harness accept a missing or wrong witness or drop the fallback assertion | O1 |
| AT-O1b | uniform selection matrix runs once for each column class (plain, FK key, declared integer, date-shift anchor, `top_code`, `group_key` sibling) on every applicable route in 5.3 and for chunk sizes 1, 2, 3 and whole-frame. Every cell first asserts its route-owned production witness. It pins `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `not (==)`, `not (<)`, `and`, and `or`: blanks are selected by `!=`, `not in`, and `not (...)`. It includes a chunk with only in-range values and the literal `9007199254740993`, and int64 against exact and inexact float literals. For FK and relationship jobs requested with unified enabled, it asserts unified admission rejects, `unified_slice_activation` is absent, the refusal record names unified slice, and `execution_mode == "full_frame"` before checking the same oracle | today's Int64 classes use `pd.NA`; literal-only trigger is absent; a unified-requested relationship cell can pass on an unproved fallback | one mutation per class restores `pd.NA`; another removes the literal-range check; another drops the fallback-route witness | O1 |
| AT-O1c | generated frames with ints across `+-2**63`, blanks, integer literals across the same range, and int64/float-literal pairs equal the Python-int-and-NaN reference evaluator on every route; a fixed chunk-size-1 example has only in-range values and an out-of-range literal | float64 path | drop the value-range check; separately drop the literal-range check | O1 |
| AT-O1d | an FK integer key read by `when:` still matches the DE-10 contract | guard | drop FK columns from the set | O1 |
| AT-O1e | AST drift sentry checks exact `(path, function)` callers of both `fk_columns_for_table` and `to_pandas_fk_safe`. `_fk_keys.py:lossless_int_columns` is the sole production caller that builds the complete set from `fk_columns_for_table`. Direct ingestion rows are `_pandas_adapter.py:PandasExecutionAdapter.run`, `_sequential.py:run_sequential`, `_chunked_carry.py:adapter_fk_safe_columns`, `_unified_slice_admission.py:cheap_admission`, `native/_when_mask.py:when_mask`, `native/_faker_null_mask.py:plan_faker_null_masks` and `faker_missing_mask`. Indirect diagnostic rows are `_chunked_oracle.py:_oracle_masked` and `_chunked_carry.py:CarryPlan.diagnose_adapter`. Narrow-purpose rows are `_mixed_fk_bridge.py:_write_back_fk_column`, `_transforms_table.py:to_transform_frame`, and `native/_group_key_kernel.py:_stringify_sibling`. `_pipeline_full_frame.py:_raise_if_source_value_unrepresentable` is the diagnostic-only exception. Each row has a reason; any other caller fails. Plain `.to_pandas()` ingestion is a known limit, not claimed by this sentry | sets built by hand | build the set by hand in `_chunked_carry.py`; separately call the helper from a new function with an allowlisted bare name | O1 |
| AT-O1f | for every route and every admitted strategy, a null-bearing integer column read by `when:` and passed through is `int64`, including `run_mask_pipeline_chunked` oracle; flag-on and flag-off schema equality includes metadata. Each cell first asserts its route-owned production witness. FK and relationship jobs requested with unified enabled explicitly assert unified rejection, absence of `unified_slice_activation`, the unified refusal record, and `execution_mode == "full_frame"` before schema checks | some routes write `double`; a requested route can silently fall back and make the schema assertion vacuous | leave `when:` columns out of the set; separately drop the fallback-route assertion | O1 |
| AT-O2a | two runs to `out.csv.gz`, `out.csv.tar.gz` and `out.csv.zip` give byte-identical files; chunked gzip parses as exactly one member per input chunk and concatenates to the uncompressed CSV bytes | time in headers | `mtime=None`; separately collapse chunked gzip to one member | O2 |
| AT-O2b | gzip header: byte 3 has FNAME clear and bytes 4 to 8 are zero for every member; tar guard: member mtime 0, uid 0, gid 0, empty names; zip entry has fixed `date_time`, explicit fixed `external_attr`, expected compression and staged `file_size` | staging name and time stored | pass `filename=tmp.name`; separately omit `external_attr` | O2 |
| AT-O2c | a failure after chunk one keeps the old output for each compressed suffix | guard | open the final path directly | O2 |
| AT-O2d | the decompressed CSV equals the uncompressed run's bytes | guard | change the line terminator | O2 |
| AT-O2e | with `zipfile.ZIP64_LIMIT` patched below the fixture size, zip writes and reads successfully with a ZIP64 local header and no new refusal; the staged size was set before `ZipFile.open` | streaming header lacks ZIP64 | omit `ZipInfo.file_size` | O2 |
| AT-O2f | `.tar`, `.tar.bz2`, `.tar.xz`, `.bz2`, `.xz`, and `.zst` output bytes and decoded CSV match the base; wrappers use `encoding="utf-8", newline=""` | guard | route `.xz` through the new gzip writer | O2 |
| AT-O3a | For every route in 5.3, ordinary pass-through `large_string` batches are `string` in successful output, except a fixed-schema Parquet sink, which keeps `large_string` and is byte-equal to `origin/main` (revision 3.3). Each cell asserts its route witness. | `run_mask_chunked` keeps `large_string`; a fixed-schema Parquet sink narrows its field. | Remove the narrow in the passthrough branch. Narrow the fixed-schema sink field. | O3 |
| AT-O3b | an FK pass-through `large_string` key joins the same rows | guard | narrow the parent only | O3 |
| AT-O3c | AT-E3-2 (`tests/native/test_chunked_nondet_categorical_admission.py:709`) and the G7 signatures in `tests/parity/test_phase_d_dcomp_composite_ooc.py` expect `string`, changed in the same commit as the cast; the gate checks that only the expected type/signature assertions and test name change | pin `large_string` | none: diff-checked at the gate | O3 |
| AT-O3d | Out-of-core: `passthrough_array` observes and narrows each chunk. It never calls `combine_chunks` or reads a values buffer. | Combined or decoded first. | Narrow after `combine_chunks`. Separately access `buffers()[2]`. | O3 |
| AT-O3e | Patch the shared width helper with a small byte threshold. Run every route in 5.3 over a one-shot source iterator. A fitting batch reads its first and last offsets. A larger batch scans only its offsets and returns ordered row slices. The width decision never accesses its values buffer. A total payload above the threshold succeeds when each row fits. FK analytic resolution equals the data type. The iterator is consumed once. No route pre-scans or replays the source. | A pre-scan consumes the iterator or doubles source reads. `ArrowInvalid` is raised. The analytic type stays `large_string`. | Add `list(source)` before schema selection. Bypass the helper in `normalize_chunk`. Separately return the source type from `masked_output_type`. | O3 |
| AT-O3f | Use two batches under a reduced threshold. The first batch is narrow. The later batch has one value over the limit. CSV exits 0 and preserves the value, order, and nullability. It does not replay the source. The resident result promotes its earlier chunk. The final column, `masked_output_type`, and both FK resolvers are `large_string`. Test the real sparse-mmap 2 GiB array on `origin/main` and the new head. Local mode raises `ArrowInvalid` with the C++ writer reason. Strict mode raises `FileAccessReadError` with `file could not be read: target`. Record both heads. Pin that the CLI CSV writer has no schema-width refusal. | The first-batch decision becomes permanent. CSV refuses or replays the source. Resident, analytic, or FK types disagree. Parquet gains an earlier engine refusal or a different policy-specific error. | Freeze the state after batch one. Make one FK resolver ignore promotion. Separately translate either Parquet error. | O3 |

## 9. Placement

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/contracts/stability.py` | new: `PACKAGE_TIERS`, `TIER_EXCEPTIONS`, optional-extra rules, `EXPERIMENTAL_MARKER`, `INTERNAL_TAGS`, `DERIVATION_LABELS` | Versioned contracts | `contracts/distribution_snapshot.py` |
| `docs/compatibility-contract.md`, `docs/frozen-surfaces.md` | changed | Feature and contract docs | - |
| `tests/sentry/release/test_frozen_surface_map.py` | changed | Sentry test (release) | - |
| `tests/sentry/release/test_public_census.py` | new (AT-X0a, AT-X0e, AT-X0f) | Sentry test (release) | the map sentry |
| `tests/sentry/release/test_experimental_marker.py` | new | Sentry test (release) | the map sentry |
| `tests/sentry/release/test_tag_census.py` | new | Sentry test (release) | the map sentry |
| `src/decoy_engine/sdk.py`, `src/decoy_engine/providers.py` | changed (module and function docstrings) | Public API | - |
| `src/decoy_engine/internal/base.py`, `src/decoy_engine/transforms/base.py` | deleted | Transforms | - |
| `src/decoy_engine/transforms/formula.py`, `pyproject.toml` | changed | Transforms | - |
| `src/decoy_engine/expressions/_when_parser.py` | changed (set) | existing expressions package | - |
| `tests/sentry/defects/test_when_reserved_names.py` | new | Sentry test (recurring-defect) | - |
| `src/decoy_engine/execution/_when_gate.py` | changed (`when_eval_frame`) | Pipeline spine and routes | - |
| `src/decoy_engine/execution/_fk_keys.py` | changed (`lossless_int_columns`; 380 lines today) | Pipeline spine and routes | - |
| `src/decoy_engine/execution/_pandas_adapter.py`, `_sequential.py`, `_chunked_carry.py`, `_unified_slice_admission.py`, `native/_when_mask.py`, `native/_faker_null_mask.py` | changed (six direct call sites) | Pipeline spine; Native companion bridge | - |
| `tests/sentry/defects/test_lossless_int_columns.py` | new | Sentry test (recurring-defect) | - |
| `src/decoy_engine/execution/native/_chunked_schema_rule.py` | changed (passthrough branch) | Native companion bridge | - |
| `src/decoy_engine/kernel/_scalar.py` | changed (`passthrough_array`) | Arrow kernels | - |
| `src/decoy_engine/_arrow_types.py`, `src/decoy_engine/execution/out_of_core/_mask.py`, `_pipeline_routing_fk_dtype.py`, `out_of_core/_batch_join.py` | changed (one incremental width state, offset-only split/narrow rule, resident promotion, and analytic type consumers) | Shared bottom leaf; Out-of-core FK; Pipeline routing | - |
| `C:src/decoy/__init__.py`, `C:src/decoy/api.py` | changed | Python API | `_LAZY_API` |
| `C:CODEMAP.md` | changed: add the shared first-party outbound policy row and put new outbound-policy sentries in `tests/sentry/io_policy/outbound/` | Where Things Go: Shared private primitives and Source readers and target writers | existing Notifications and Shipped install rows |
| `C:docs/release/frozen-surfaces.md`, `C:docs/release/versioning.md`, `C:docs/roadmap/groups/health.md` | changed | Release runbooks, logs and maps; Roadmap, plans and records | `FREEZE-SURFACE` is the durable group row after the roadmap split |
| `C:tests/sentry/release/test_frozen_surface_map.py` | changed | Release runbooks, logs and maps | - |
| `C:tests/sentry/release/test_hidden_names.py`, `C:tests/sentry/release/test_tag_census.py` | new | Sentry test | `test_frozen_surface_map.py` |
| `C:src/decoy/cli/demo.py` | changed | Command module | - |
| `C:src/decoy/cli/io/_layout_errors.py` | changed (`REPORT_DESCRIPTORS`) | Project layout services | - |
| `C:src/decoy/_outbound.py` | new | New CODEMAP row "Shared first-party outbound policy": `src/decoy/_outbound.py`; the existing map has no network-policy row, so S6 adds it before the module | beside `_update_check.py`, `notify.py`, and `telemetry.py` at their shared root |
| `C:src/decoy/_update_check.py`, `C:src/decoy/notify.py`, `C:src/decoy/telemetry.py`, `C:src/decoy/cli/upgrade.py`, `C:src/decoy/distribution/installer.py` | changed | Shared outbound caller; Notifications, telemetry; Command module; Shipped install and update | - |
| `C:tests/sentry/io_policy/outbound/__init__.py`, `C:tests/sentry/io_policy/outbound/test_outbound_choke_point.py` | new named sub-package and sentry | Revised Source readers and target writers CODEMAP row: outbound-policy sentries go in `tests/sentry/io_policy/outbound/`; the general Sentry test row permits `tests/sentry/<group>/test_<rule>.py` | beside the parent policy test `test_update_check_no_identifiers.py`, without adding a 26th direct module to `io_policy/` |
| `C:src/decoy/cli/io/_compression.py`, `C:src/decoy/cli/io/_targets.py` | changed (one compressed writer) | Source readers and target writers | - |

No new module is added under `src/decoy_engine/execution/` or at the engine root. The registry goes in `contracts/`. CLI `src/decoy/` has 17 direct Python modules today, below the about-25 limit; `_outbound.py` is placed there only after the CODEMAP gains its explicit shared-outbound row. `C:tests/sentry/io_policy/` already has 25 direct modules, so S6 adds no direct module there and uses the named `outbound/` sub-package.

## 10. Design notes

### 10.1 One registry per repo, keyed by object

`contracts/stability.py` holds package rules plus a short `(module, name, tier)` exception tuple, the marker, and the two tag lists. Contract 3.4 packages derive frozen rows from the contract; other public subpackages derive documented-internal rows unless an exception marks a name frozen or experimental. The census imports all 59 public packages, resolves 1,186 names, and groups non-constant exports by `id(obj)`; each group must map to exactly one tier. Constants are matched by `(module, name)` and their defining module wins. Optional-extra packages have one registry from package to expected missing dependency and statically declared exports; only that exact `ImportError` may skip runtime resolution. The CLI keeps `EXPERIMENTAL_API` beside `_LAZY_API`. No decorator (mutmut 3.7, API reference signatures). The census test module stays below the 700-line hand-written module cap, with a 650-line ceiling and expected size about 330 lines.

### 10.2 Hidden names

The sentry reads `walk()` from `C:tests/command_tree.py` and compares the hidden set to one map row listing `name: tier`. Internal names start with `_`; frozen-hidden names are frozen like visible ones.

### 10.3 Pass-through narrowing

`_arrow_types.py` owns one `TextWidthState` and one `split_narrow_text` operation. There is no route-level pre-scan. The first batch sets a provisional `string` width. Each observation first compares the first and last 64-bit offsets. A fitting total span proves that every value fits. The batch then narrows immediately. A larger span requires a scan of adjacent offsets. This scan selects row slices and detects an unsplittable value. It does not combine chunks, read payload buffers, decode UTF-8, or consume a source iterator.

A batch of narrowable rows returns ordered `string` slices. An unsplittable row promotes the state to `large_string`. A resident collector replaces the 32-bit offsets of prior chunks with 64-bit offsets. It shares the existing payload buffers. CSV writes the current `large_string` batch without replay.

The `normalize_chunk` passthrough branch and `passthrough_array` consume this state. `_safe_cast` stays the generic wrapper. No caller implements a separate split or width test. `masked_output_type`, pipeline FK routing, and `_batch_join._resolve_output_types` observe the state before each batch. Therefore, the analytic, parent, child, and data types align. `mask_batch` splits record batches at the returned row boundaries. It repeats untouched arrays as matching slices.

A batch larger than 2 GiB succeeds as `string` when each row fits. A later wider value succeeds as `large_string` for CSV and resident output. Parquet reaches the unchanged C++ writer limit. The local policy raises `ArrowInvalid`. The strict policy raises `FileAccessReadError`. These results match `origin/main`. The ordinary path adds two 64-bit offset reads per batch. Only an oversized batch scans its offsets. That scan is O(rows) over the offsets buffer. It does not read the payload. O3 adds no source reread and no new refusal.

### 10.4 Compressed writer

One function in `_compression.py` returns a context manager that yields `TextIOWrapper(..., encoding="utf-8", newline="")` for `to_csv` and closes every compression layer in its `finally`. `write_chunked_output` opens and closes one fixed-header gzip member per chunk, preserving today's concatenated-member shape. Tar needs the member size in advance, so the CSV is written to a second staging temp and then added with `TarInfo.size` set. Zip also stages the CSV, sets `ZipInfo.file_size` before `ZipFile.open`, fixes `date_time` and `external_attr`, and copies the bytes; this chooses ZIP64 in the local header when needed. Compression levels are pinned to today's defaults (gzip 9, zip deflate 6). Existing `.tar`, `.tar.bz2`, `.tar.xz`, `.bz2`, `.xz`, and `.zst` paths are guards and do not move to this function.

### 10.5 Order with other plans (Q11)

- FAKER-MIGRATE (`E:plan/faker-migrate`) edits contract sections 1 and 3.3, adds Breaking fragments, rewrites the testflight goldens, and has its own engine release and CLI repin. Owner Q11: this batch's engine release goes first; FAKER-MIGRATE S2 comes after. Whichever of FREEZE-OUTPUT, FAKER-MIGRATE S2, and GEN-PROVIDERS E#661 lands later reruns every owning tool in faker-migrate section 5.6 plus the O1/O3 parity and proof owners listed in 5.6, on its final head, and requires a clean `git status`. It never edits a golden by hand.
- PROP-batch C-F1b changes `C:src/decoy/cli/io/_targets.py` `write_targets` and the demo writer; O2 changes the two write functions in the same module, and S2 changes `C:src/decoy/cli/demo.py`. O2 and S2 start after C-F1b merges and rebase on it.
- PROP-batch E-S1a and E-S1b delete root bindings and `ExecutionContext` members. X0's census requires registry rows equal to `__all__` both ways, so whichever lands second removes or adds the rows in its own diff. Recommended: E-S1a first, then X0.
- REL-GATE G3 runs both map sentries, so X0, X1, S2, S4, S5 and S7 merge before G0.
- OUTPUT-METADATA-LEAK rev 3.1 at `176f5cf34` reciprocally orders its E1/C1 against this batch. E1 rebases after X0. If E1 is merged when this engine release is cut, the release carries E1 with X0, S1, S5, S7, O1, and O3, and the one CLI repin contains it. Otherwise E1 rides the next daily engine release and requires a second CLI repin. C1 always lands after O2 because both edit `_targets.py`. O3 owns the contract 3.4 passthrough-type sentence; metadata-leak E1 owns the adjacent route-metadata paragraph and must not retain its old claim that passthrough columns always keep the source field, because O3 narrows `large_string` fields when every individual value fits 32-bit offsets and retains them otherwise.
- The freeze engine release carries X0, S1, S5, S7, O1, O3, and conditionally metadata-leak E1; one CLI repin follows, unless the E1 fallback requires the recorded second repin.

### 10.6 `lossless_int_columns`

It replaces direct-site unions with one function in `_fk_keys.py` (the module that owns the DE-10 contract). `_pandas_adapter.py:214` and `_chunked_carry.py:215` currently disagree because the latter omits declared integers and date-shift/group anchors; both call the new function. `_sequential.py:422`, `_unified_slice_admission.py:364`, and `native/_when_mask.py:58` call it too. `native/_faker_null_mask.py:81` unions it with the positional-Faker protected set. Indirect diagnostic paths `_chunked_oracle.py:465` and `_chunked_carry.py:143` receive the same result. AT-O1e parses the AST and checks exact `(path, function)` identities for both helpers; the complete identities are in the AT-O1e row, and a bare helper-name allowlist is forbidden. `_pipeline_full_frame.py:_raise_if_source_value_unrepresentable` stays as a diagnostic exception because it receives no plan or registry and deliberately retries one column. Plain `to_pandas()` ingestion remains a known limit outside the helper claim. `when_eval_frame` is the post-ingestion choke point that replaces `pd.NA` with `NaN` for evaluation, so lossless storage dtype and uniform selection semantics do not conflict.

### 10.7 Outbound purposes and the import sentry

| Purpose | Schemes | Redirects | Caller |
|---|---|---|---|
| `upgrade_document` | https, file | https to https only | `upgrade --url`, default version document |
| `upgrade_artifact` | https, file | https to https only (GitHub release downloads redirect to a CDN) | installer download, artifact URLs inside the document (`C:packaging_tools/smoke_install.py:290`) |
| `update_check` | https | none (`_outbound.RefuseRedirects`) | `_update_check.py` calls `_outbound` |
| `notify_webhook` | https, http | followed only while every hop remains allowed for this purpose | `--notify webhook:` |
| `notify_slack` | https | https-to-https only | `--notify slack:` |
| `otel` | the rules of today's `validate_endpoint`, moved unchanged | as today (requests) | telemetry |

Each hop of every followed redirect is re-checked against the purpose's schemes, including notify. `parse_notify_spec` asks `_outbound` for the purpose's scheme decision; it does not copy the table. Import sentry spellings covered: `import urllib`, `import urllib.request`, either with aliases; `from urllib import request as r`; `from urllib.request import urlopen` with any alias; `import http.client` and `from http import client`; `import requests`, `urllib3`, `httpx`, `socket`, and `smtplib`; and `importlib.import_module` or `__import__` when the name is a literal or a module-level constant the AST can resolve. Allowlist entries are exact `(path, function)`: `_outbound.py` owns urllib request opening and redirect handlers; `telemetry.py` owns the third-party `requests` call after applying the `otel` rule; `notify.py` owns SMTP only. `_update_check.py` is not allowlisted. Known limit: a dynamic import with a computed non-constant name is not seen and is V2-LOG.

## 11. Size

| Slice | Source lines | Test lines | Docs lines |
|---|---|---|---|
| X0 | 100 | 330 | 180 |
| X1 | 30 | 120 | 80 |
| S1 | -170 net | 40 | 10 |
| S2 | -120 net | 90 | 20 |
| S4 | 40 | 80 | 30 |
| S5 | 10 | 70 | 20 |
| S6 | 220 | 320 | 40 |
| S7a (engine census, 3.1 and 3.3 rows, pinning tests) | 60 | 450 | 200 |
| S7b (CLI census, renames table) | 20 | 120 | 60 |
| O1 | 140 | 380 | 40 |
| O2 | 110 | 220 | 20 |
| O3 | 85 | 300 | 40 |

X0 is about 610 hand-written lines total, and `test_public_census.py` has a 650-line ceiling below the 700-line module cap. S7 is split because the per-tag pinning and artifact tests would otherwise put one module past 700 lines. Every other hand-written module remains below its applicable cap.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| X0 | engine | contract 3.6 and section 1 entry, rule-based `contracts/stability.py`, 59-package census and marker sentries, optional-extra handling, docstrings | R2 | AT-X0a to AT-X0f | E-S1a (10.5) | T2 plus the new sentries and mutations; Dennis then Codex |
| X1 | CLI | `EXPERIMENTAL_API`, CLI map and `versioning.md` tiers, API docstrings, `library` tier `gate` | R2 | AT-X1a to AT-X1c | X0 | T2; Dennis and Codex |
| S1 | engine | delete the two base modules and `pyproject.toml` entries; `FormulaStrategy` plain; Removed fragment | R2 | AT-S1a, AT-S1b | - | T2 plus formula and draw-site tests; mutations on `formula.py`; Dennis and Codex |
| S2 | CLI | remove demo `--ref`, `--rows`, `_generate_ref_datasets`; hidden-name sentry | R2 | AT-S2a, AT-S2b | X1; PROP C-F1b | T2; Dennis and Codex |
| S4 | CLI | `report.source_ambiguous`, `REPORT_DESCRIPTORS`, code snapshot, durable `FREEZE-SURFACE` group row | R2 | AT-S4a, AT-S4b | - | T2; Dennis and Codex |
| S5 | engine | reserved names, guard sentry, snapshot | R2 | AT-S5a to AT-S5c | X0 | T2; Dennis and Codex |
| S6 | CLI | `_outbound.open_url`, purposes, redirect handlers, value-free notify errors, import sentry | R2 | AT-S6a to AT-S6f | - | T2 plus the smoke-install test; Dennis and Codex |
| S7a | engine | tag census, 3.1 and 3.3 rows, map rows, pinning tests, `INTERNAL_TAGS`, writer-fixture artifact scan | R2 | AT-S7a, AT-S7c, AT-S7e | X0 | T2 including artifact mutations; Dennis then Codex |
| S7b | CLI | CLI tag census; contract section 1 renames table and residual list | R2 | AT-S7b, AT-S7d | S7a | T2; Dennis and Codex |
| O1 | engine | uniform `when_eval_frame`, literal-aware object path, `lossless_int_columns`, six direct sites, exact-caller sentry, Breaking fragment naming five changed classes | R2 | AT-O1a to AT-O1f | - | T2 over every route/class/strategy; value, literal, and per-class mutations; Dennis and Codex |
| O2 | CLI | deterministic gz members, tar.gz, staged ZIP64-safe zip, guard suffixes; Breaking fragment | R2 | AT-O2a to AT-O2f | PROP C-F1b | T2 including patched ZIP64 limit; Dennis and Codex |
| O3 | engine | shared incremental narrow-or-promote width state in the schema rule and `passthrough_array`, offset-only split rule, no source pre-scan, resident/CSV promotion, Parquet writer parity, analytic and FK alignment, contract 3.4, AT-E3-2 | R2 | AT-O3a to AT-O3f | - | T2 over every route and both output formats; Dennis and Codex |

Order: S1, O1 and O3 start at once. X0 starts after E-S1a. X1, S5 and S7a follow X0; S7b follows S7a. S4 and S6 start at once on the CLI; S2 and O2 wait for PROP C-F1b. The engine release (X0, S1, S5, S7a, O1, O3, plus metadata-leak E1 if it has merged by the cut) ships before FAKER-MIGRATE S2; one CLI repin follows. If metadata-leak E1 misses the cut, it ships in the next daily release and causes the recorded second CLI repin; its C1 still lands after O2. Target: all freeze slices merged before REL-GATE G0 on 2026-12-04.

## 12.1 Done when

Every slice is merged with its acceptance tests green and its mutations red; both map sentries are green on the engine release head and the CLI repin head; the Breaking fragments for O1, O2, O3, S2, S4, S5 and S6 and the Removed fragment for S1 are in `changelog.d/` or the CLI `CHANGELOG`; contract section 1 lists the freeze batch corrections. O1/O3 record each golden, parity hash, and proof output in 5.6 as moved or unchanged. On the final shared head, every owning tool from faker-migrate section 5.6 plus the O1/O3 owners is rerun and leaves the tree clean. The release manifest conditionally includes metadata-leak E1 exactly as 10.5 specifies.

## 13. Recurring-defect class check

- A test weakened to pass: AT-O3c lists every edited existing assertion; the gate checks that each changes only the expected type or signature and that all value, row, null, metadata, and parity assertions remain.
- Two copies of a central mechanism: one tier registry per repo, one outbound function, one lossless-column function, one `when:` frame function, one compressed writer. The ingestion drift found in `_chunked_carry.py` is the class this closes.
- A frozen surface changed without its records: each output slice carries its contract sentence, map row and fragment in the same commit.
- Value-free errors: the new refusals name the purpose and scheme only; `NotifySpecError` stops echoing the spec.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a webhook token in an error; a `when:` literal in a log) | refusals name purpose and scheme only; `NotifySpecError` fixed text; `_eval_predicate` already logs no expression | AT-S6b, AT-S6c | echo the spec | S6, O1 |
| 2 | Cleanup on every exit (gzip, tar or zip layer left open; staging temp left) | one writer context closes every layer in its `finally` inside the staging context | AT-O2c | close only the outer layer | O2 |
| 3 | State completeness (each public object has a tier; each tag has a class; each operator has a null rule) | registry plus census; the AT-O1b operator matrix | AT-X0a, AT-X0e, AT-S7a, AT-O1b | allow a name with no row | X0, S7a, O1 |
| 4 | Route coverage (one route keeps ordinary `large_string`, pre-scans, or loses a later promotion; or keeps a float64 frame) | one incremental width state per table and one frame function used by every route | AT-O1a, AT-O3a, AT-O3e and AT-O3f over 5.3 | skip the narrow in the schema rule; freeze width after batch one | O1, O3 |
| 5 | Referential integrity (FK keys after the narrow or the frame change) | FK keys stay on the DE-10 path; the narrow keeps values | AT-O1d, AT-O3b | narrow the parent only | O1, O3 |
| 6 | Untrusted input (a URL from a flag or a version document) | per-purpose scheme allow list; every redirect hop re-checked | AT-S6a, AT-S6e | follow https to http | S6 |
| 7 | TOCTOU or check-then-use (scheme checked, a different URL opened) | `open_url` parses once, checks and opens that parsed value; redirect hops are checked inside the handler before the request | AT-S6a, AT-S6e | check, then open a re-read string | S6 |
| 8 | Weak proof (a sentry that passes on an empty set; a guard labelled as a red test) | each sentry asserts a minimum set and a known member; guards are labelled | self-tests; AT-X0e floors of 59 packages and 1,186 names; AT-S5a labelled | make the walk return nothing | X0, S2, S5, S6, S7a |
| 9 | Refactor drift (S1 changes formula output; the ingestion move changes a set) | S1 removes bases only; `lossless_int_columns` returns the old union plus `when:` columns, checked per site | AT-S1b, AT-O1e | rename `apply`; drop declared ints | S1, O1 |
| 10 | Frozen contract drift (contract, map and code disagree) | the registry is the source; sentries compare contract 3.6, both maps and docstrings to it | AT-X0c, AT-X0d, AT-S5c, AT-S4b, AT-S7c | edit the map only | X0, X1, S4, S5, S7a |

### 13.2 Recurring defect catalog

| Catalog class | Plan check |
|---|---|
| 1. Anchored validation | Tag and version patterns use `re.fullmatch` or `\Z`, never `$`; newline cells are included in the sentries. |
| 2. Strict wire and stored types | New tier, tag, and purpose records use closed enums and strict primitive types; wrong booleans and numeric strings are refused in registry fixture tests. |
| 3. No exception context | New value-free outbound errors are raised after the caught exception scope; tests assert both `__cause__` and `__context__` are `None`. |
| 4. Versioned read models | No new persisted read model. Existing tag artifacts remain under their owning versioned readers; S7 does not invent a second reader. |
| 5. Normalized guard scanners | AT-S6d resolves aliases and constants; AT-O1e keys helpers by exact `(path, function)`; each has seeded realistic spellings. |
| 6. No private-module imports | CLI calls public engine exports only. New engine imports stay within declared layer contracts and public package APIs. |
| 7. No hidden CI failures | X0, S7a, O1, O2, and O3 sentries fail normally; no skip, report-only mode, `continue-on-error`, or narrowed export. |
| 8. One trust class per entry point | `_outbound` purposes separate program-controlled update URLs, user-chosen notify URLs, and telemetry; no flag switches trust class. |
| 9. Mutations on final head | Every named mutation is rerun after the last artifact change and records the exact head. Golden owners also rerun on the final shared head. |
| 10. Allowlisted helpers checked | AT-O1e checks callers of allowlisted forwarding helpers by exact identity. AT-S6d checks the bodies and callers of its exact allowlist entries. |
| 11. No raised pins | The X0 census floor rises only to the measured real walk and the test file has a 650-line ceiling below the 700 cap. No module or package cap is raised. |

## 14. Pre-mortem

- "The tier is a label nobody reads." The marker is the first word of each docstring and doc page; `versioning.md` lists it next to the frozen list.
- "`decoy library` stayed at `gate` and 1.0 shipped." AT-X1c fails in ga.
- "O1 selected blanks differently by route." Q10 chooses one NaN-style table; AT-O1b runs it for each column class on every route.
- "O1 rounded a large literal in a chunk of small values." Literal magnitude independently selects the object path; AT-O1b and AT-O1c include chunk size 1 and a literal-check mutation.
- "O1 used too much memory on nullable integer columns." Every `when:`-read nullable integer column now gets a temporary NaN-style evaluation representation, including Int64 inputs. This can allocate an object array for a large-value or large-literal predicate and a float64 array otherwise. The O1 build records peak memory and conversion time for plain, FK, declared-int, and anchor columns at the route's normal chunk size; a regression beyond the existing route budget stops the slice for an owner decision rather than changing semantics.
- "S6 broke `decoy upgrade` from GitHub releases." `upgrade_artifact` follows https-to-https redirects; AT-S6e.
- "S6 broke the release smoke." `file` stays allowed for both upgrade purposes; AT-S6a uses the smoke's call.
- "O2 changed the compressed bytes beyond the header." Compression levels are pinned to today's defaults; AT-O2d checks the CSV content.
- "O3 halved streaming throughput to decide text width." The ordinary path reads two offsets per batch and never pre-scans or replays the source; AT-O3e uses a one-shot iterator and a values-buffer tripwire.
- "O3 refused a huge CSV cell or changed the Parquet failure." AT-O3f keeps a later CSV value and promotes resident, analytic, and FK types without replay. Its real 2 GiB sparse-array cell requires the same local `ArrowInvalid` and strict-policy `FileAccessReadError` classes and reasons on `origin/main` and the new head.
- "FAKER-MIGRATE and this batch fought over goldens." 10.5 orders them and says who reruns.

## 15. Owner questions

| Id | Question | Answer | Source |
|---|---|---|---|
| Q1 | Experimental engine set = connector SDK objects plus the six provider-registration functions; provider read names stay frozen? | Yes (owner, 2026-11-18) | owner tier decision |
| Q2 | Emit a runtime `ExperimentalWarning`? | No (owner) | new |
| Q3 | `decoy library` at G0: experimental if L4b (row 40) merges after 2026-11-27 or no command writes records by G0; frozen otherwise | Yes (owner) | owner tier decision |
| Q4 | Move audit J2 to v1+? | Yes (owner) | audit J2 |
| Q5 | `report.source_ambiguous`; other `layout.*` codes unchanged? | Yes (owner) | audit C16 |
| Q6 | Reserve the nine lowercase words in `when:`? | Yes (owner) | contract line on `type` |
| Q7 | Scheme allow list as in 10.7 | Yes (owner); revision 2 adds per-purpose redirect rules, `upgrade_artifact` and `otel` under the same answer | DUP-DEFECTS B11 |
| Q8 | `decoy demo --ref` from exit 1 to exit 2? | Yes (owner) | new |
| Q9 | Tag classification by the rule in 5.6, including the builder's reclassifications under that rule | Yes (owner) | new |
| Q10 | `when:` null semantics with exact integers | Re-decided (owner, 2026-11-18): use one NaN-style rule on every route and column class. Blank rows are selected by `!=`, `not in`, and `not (...)`; they are not selected by `==`, ordering comparisons, or `in`. `when_eval_frame` enforces it even for Int64 ingestion. FK keys, declared integers, date-shift anchors, `top_code`, and `group_key` siblings are named in the Breaking entry. | Dennis round 2 B1 |
| Q11 | Order against FAKER-MIGRATE: this batch's engine release first, FAKER-MIGRATE S2 after, the later shared-head change reruns all owning tools | Decided as recommended (owner, 2026-11-18): yes | Dennis round 1 H9; owner decision |
| Q12 | Default tier for names exported by public subpackages outside contract 3.4 | Decided as recommended (owner, 2026-11-18): documented internal unless a registry exception lists the name as frozen or experimental | Dennis round 2 H5; owner decision |

## 16. Unresolved

- Q3 is applied at G0; X1 builds the `gate` value and the ga refusal either way.
- The S7a builder may move a tag between classes under the 5.6 rule; that is covered by Q9 and recorded in the slice's build record.
