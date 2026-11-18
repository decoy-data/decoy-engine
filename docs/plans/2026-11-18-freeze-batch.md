Status: plan (revision 2, 2026-11-18; Dennis round 1 NO-GO addressed; owner answered Q1 to Q10)

# 1.0 freeze batch: the experimental tier, the frozen surface, and the output shapes that change before the freeze

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

This plan covers the three 1.0 rows that had no plan: EXPERIMENTAL-TIER, FREEZE-SURFACE and FREEZE-OUTPUT (1.0 scope triage, `C:docs/records/2026-11-18-1.0-scope-triage.md`, CLI branch `claude/focused-sagan-0arhsp`, PR #320). They are planned in that order because each one decides the next: the tier says which names are not frozen, so FREEZE-SURFACE only cleans up what stays frozen, and FREEZE-OUTPUT only fixes output bytes of frozen routes. Every slice lands before row 93 (REL-GATE), and every engine slice lands before the D-4 engine release (REL-GATE G1).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`. The plan lives in the engine repo on branch `plan/freeze-batch` because most of the slices and both contracts it edits are engine-owned.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1 for docs, registries and the dead-base removal; R2 for output bytes, a frozen `--json` reason code and the outbound URL check), `development-loop.md` (PLAN: scope, behaviour and failure modes, acceptance tests first with their mutation, placement, slice table, owner questions), `api-and-compatibility.md` (consumer inventory, explicit breaking changes, contract tests), `cross-cutting-concerns.md` (one choke point plus a sentry and its mutation), `security.md` (outbound URL schemes and redirects), `data-and-migrations.md` (output format bytes), `testing.md` (T0 to T2, mutations), `proportionality.md`, `reuse-first.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2 overall, because O1 to O3 change output bytes and S4 and S6 change what a user sees in `--json`. X0, X1, S1, S2, S5 and S7 are R1 (docs, registries, sentries, dead code). Approver: Cam (owner) for the plan and the owner questions; Dennis then Codex for the plan gate.

Why 1.0: all three rows pass the "freeze" test of the triage. After 1.0, any of these changes is a 2.0 break under the triage's definition (a public name, a default, an output byte, an exit code, a reason string, a schema field, a report tag, or a new refusal for a config or run that is valid today). The tier must exist before 1.0, or every public name is frozen by default.

### Revision 2 changes (Dennis round 1: 1 BLOCKER, 9 HIGH, 9 MEDIUM, 3 LOW)

| Finding | Change | Where |
|---|---|---|
| B1 | O1 keeps today's null-row selection for every operator (owner Q10, decided). Only integers at or above 2**53 change. AT-O1b is a null-row matrix over every operator pinned to today; AT-O1c compares to a Python-int reference evaluator. | 4.3, 8, 15 |
| H1 | One `lossless_int_columns(plan, registry, graph)` in `_fk_keys.py`, called from every ingestion site and `native/_when_mask.py`; it includes the integer columns `when:` reads. Drift sentry. Second output change (int64 instead of double on whole-frame routes) listed. | 4.3, 5.5, 10.6 |
| H2 | O3: no new module. `narrow_text` in the passthrough branch of `native/_chunked_schema_rule.py`; `kernel/_scalar.py::passthrough_array` narrows per batch. Text over 2 GiB is split, never refused. | 4.3, 10.3 |
| H3 | S6 folds telemetry's `validate_endpoint` in as purpose `otel`. The sentry is import-based over every network module spelling, with a (path, name) allowlist. | 4.2, 10.7 |
| H4 | Redirect rule per purpose; installer and bundle purposes follow https-to-https redirects; new test. Notify keeps its behaviour. | 10.7, AT-S6e |
| H5 | Tiers are assigned by object identity. sdk names that are `errors.*` objects stay frozen. Root re-exports handled. Constants are covered by their module docstring marker. | 4.1, 10.1 |
| H6 | One default: the census reads contract 3.4 plus every public subpackage `__all__`; each name has an explicit tier. | 4.1, AT-X0e |
| H7 | Tag regex allows dots and underscores; 32 unlisted tags; `flagged-redacted/v1` and `/v2` frozen; the classification rule is written down; f-string tags are a known limit. | 4.2, 5.6 |
| H8 | O2 covers `.tar.gz` (same gzip wrapper, `TarInfo.mtime=0`) and zip (fixed `date_time`); pinned compression level; the claim is scoped to the same zlib build. | 4.3, 10.4 |
| H9 | Order against FAKER-MIGRATE, PROP-batch C-F1b and E-S1a/E-S1b written down (Q11). | 10.5 |
| M1 to M9 | Notify URLs come from `--notify`, value-free `NotifySpecError`; F12 and old AT-O3c dropped; S7 sized honestly; Removed and Breaking fragments and a contract section 1 entry; AT-S5a labelled a guard with the case policy; G1 narrowed to what the tests check; gzip header bytes asserted; route lists recorded as a known limit; upgrade-document artifact purpose added. | throughout |
| L1 to L3 | `pyproject.toml:549` and `:1019` entries removed in S1; S4 updates the deferred row in `C:docs/roadmap/post-1.0-plan.md` and keeps `report.*` descriptors in the one descriptor module; compression level pinned. | S1, S4, O2 |

## 1. Guarantee and non-goals

Guarantees after this batch:

- G1. Every name in `decoy_engine.__all__`, in the `__all__` of every public engine subpackage (contract 3.4 plus the census walk, 39 packages today), and in the CLI `_LAZY_API` has exactly one tier: frozen, experimental or internal. The tier is keyed by object identity, so one object exported from two places has one tier. AT-X0a, AT-X0e and AT-X1a check this. Visible CLI commands and options stay frozen through the existing `C:tests/unit/test_cli_surface.py`; hidden ones get a tier through S2.
- G2. An experimental class or function starts its docstring with the fixed marker; an experimental constant is covered by its module docstring marker. A sentry checks the markers against the registry.
- G3. Hidden CLI options and commands are listed with a tier. A new hidden name fails the build until it is listed.
- G4. Every `"<name>/vN"` tag literal (dots and underscores allowed) in engine and CLI source is classified: frozen format (contract 3.1), frozen determinism label (contract 3.3), or internal with a reason. A new literal fails the build until it is classified. Tags built with f-strings are a known limit.
- G5. The `when:` grammar's keyword literals are all reserved names, and the reserved set is pinned by an exact snapshot.
- G6. Every outbound network call the CLI makes goes through one function with a per-purpose scheme and redirect rule, except a short (path, name) allowlist.
- G7. Three output shapes are fixed before the freeze: `when:` on integer columns compares exactly at or above 2**53 with today's null semantics; a compressed CSV target (`.gz`, `.tar.gz`, `.zip`) holds no staging name and no wall-clock time; a pass-through text column is `string` on every route.

Non-goals:

- No runtime `ExperimentalWarning` (Q2, owner: no).
- No change to the experimental surfaces themselves (no connector SDK entry point, no `load_custom_providers` caller, no `api.scan` port to `scan_sources`). Audit J2 moves to v1+ (Q4, owner: yes).
- No new public name. FREEZE-SURFACE removes or relabels.
- No rename of experimental names (the `decoy_engine.FileSource` and `decoy_engine.config.FileSource` collision is a 1.x candidate).
- No snapshot of every CLI reason code. Only the gate and warning vocabulary is pinned (S4); the rest is a known limit in the CLI map.
- No change to `when:` null semantics (Q10, owner: keep today's).
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
| Three-valued comparison | SQL and pandas `NA` propagate unknown; float `NaN` compares unequal | Keep Decoy's current `NaN` semantics for `when:` (Q10): a reference evaluator over Python ints with `NaN` for null is the oracle. |
| URL allow list and redirects | OWASP SSRF guidance (allow list, re-check every redirect hop); `urllib.request` `HTTPRedirectHandler.redirect_request` | One function with per-purpose schemes and a per-purpose redirect handler that re-checks the scheme of every hop. |

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
| CSV compression option | `csv_compression`, `split_compression` | `C:src/decoy/cli/io/_compression.py:44` |
| Redirect refusal | `RefuseRedirects` | `C:src/decoy/_update_check.py:60` |
| OTel endpoint rule | `validate_endpoint` | `C:src/decoy/telemetry.py:93` |
| Shape changelog check | `check_shape_changelog.py` (REL-GATE G3) | `C:scripts/release/check_shape_changelog.py` |
| Changelog fragments | Breaking and Removed fragments | `changelog.d/README.md` |

No new module is added under `src/decoy_engine/execution/` (frozen at 103 modules; caps are never raised).

## 4. Behaviour

### 4.1 EXPERIMENTAL-TIER

Contract text (new section 3.6 "Experimental surfaces" in `docs/compatibility-contract.md`, mirrored in `C:docs/release/versioning.md`):

1. A surface is frozen, experimental or internal. Frozen follows sections 3.1 to 3.5 and section 4. Internal names are listed with tier `internal` in the registry (engine) or start with `_` (CLI); they may change in any release. Nothing is internal by omission: an unlisted public name fails the census.
2. An experimental surface may change or be removed in any minor release. The change gets a `Changed` or `Removed` fragment that starts with "Experimental:". No deprecation window is promised.
3. Determinism is never experimental. Output bytes produced through an experimental surface (a custom provider's values, a connector's rows once masked) follow section 3.3. Stored records are never experimental: everything under `.decoy/` is frozen whatever the tier of the command that wrote it.
4. An experimental class or function starts its docstring with `Experimental:`. An experimental constant has no docstring of its own; its module docstring starts with the marker and names it. The doc page has the marker in its first paragraph.
5. An experimental surface becomes frozen by moving its registry row and removing the marker, in a minor release. It never goes from frozen back to experimental inside a major.
6. A tier belongs to an object, not to a name. The census resolves each exported name to its object; the same object exported from two modules has one tier.

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
4. S4 (CLI): rename `layout.report_source_ambiguous` (`C:src/decoy/cli/io/_layout_errors.py:159`) to `report.source_ambiguous` (Q5). The descriptor stays in `_layout_errors.py`, the one descriptor module, in a new `REPORT_DESCRIPTORS` tuple that joins `GATE_DESCRIPTORS`. Exact snapshot of `GATE_CODES`, `WARNING_CODES` and `_CLI_GATE_CODES`. S4 updates the deferred reason-code row in `C:docs/roadmap/post-1.0-plan.md` to say the gate and warning set is pinned and the rest stays a known limit.
5. S5 (engine): add `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith`, `endswith` to `RESERVED_NAMES` (Q6). Case policy: reserved names match exactly, case-sensitive, as `_name()` does today (`src/decoy_engine/expressions/_when_parser.py:116`); only the lowercase forms are reserved, so a column named `NULL` or `Between` stays a column. A sentry checks that every keyword literal in `when_grammar.lark` is a reserved name (a guard: green today), and an exact snapshot pins the set.
6. S6 (CLI): one outbound function `C:src/decoy/_outbound.py::open_url(url, purpose)`. Purposes and rules are in 10.7 (Q7). The `urlopen` sites (`C:src/decoy/cli/upgrade.py:55`, `C:src/decoy/distribution/installer.py:250`, `C:src/decoy/notify.py:254`, `C:src/decoy/notify.py:319`) call it, and telemetry's `validate_endpoint` (`C:src/decoy/telemetry.py:93`) becomes the `otel` purpose's rule. Notify URLs come from `--notify kind:target`, so the scheme check runs in `parse_notify_spec`, and every `NotifySpecError` message becomes value-free (today `C:src/decoy/notify.py:128` echoes the whole spec, which can hold a webhook token).
7. S7 (engine, then CLI): a "Public renames before 1.0" table in contract section 1 (the detection taxonomy renames), and a tag census in each repo with the regex `"[a-z][a-z0-9._-]*/v[0-9]+"`. The engine has 32 tag literals not in the 3.1 block. Each is classified by the rule in 5.6.

### 4.3 FREEZE-OUTPUT

1. O1 (engine), decided by Q10: a `when:` predicate keeps today's null semantics for every operator. Null rows are selected by `!=`, by `not (...)` around a comparison that is false for null, and by `not in`; they are not selected by `==`, `<`, `<=`, `>`, `>=` or `in`. What changes: an integer column that holds a value outside `[-2**53, 2**53]` compares exactly. The `when:` eval frame is built by one function `when_eval_frame(frame, refs)` in `_when_gate.py`. For each referenced nullable integer column: no null, so it stays int64 (as today); every value inside `[-2**53, 2**53]`, so it becomes float64 with `NaN` for null (exactly today's bytes); otherwise it becomes an object column of Python ints with `NaN` for null, and that predicate runs on the pandas python engine. The result equals a Python-int reference evaluator on every chunking. Callers: `_eval_predicate` (`src/decoy_engine/execution/_when_gate.py:115`) calls it first, so `native/_when_mask.py:59` and `_unified_slice_when.py:88` get it too.
2. O1 ingestion (H1): one function `lossless_int_columns(plan, registry, graph) -> dict[str, set[str]]` in `src/decoy_engine/execution/_fk_keys.py` returns the union every site builds by hand today (FK keys, group anchors, `top_code`, `group_key` siblings, declared ints, date-shift group columns) plus the integer columns any `when:` reads. Every ingestion site calls it: `src/decoy_engine/execution/_pandas_adapter.py:205`, `src/decoy_engine/execution/_sequential.py:422`, `src/decoy_engine/execution/_pipeline_full_frame.py:77`, `src/decoy_engine/execution/_chunked_carry.py:215` (`adapter_fk_safe_columns`, which has already drifted: it lacks declared ints and group anchors), and `src/decoy_engine/execution/native/_when_mask.py:58`. Second output change: a null-bearing integer column read by `when:` and passed through is written as `int64` instead of `double` on the whole-frame and sequential routes (the chunked native leg already writes the source type).
3. O2 (CLI): compressed CSV targets are written through one function in `C:src/decoy/cli/io/_compression.py`, used by `C:src/decoy/cli/io/_targets.py:405` and `:543`. `.gz`: `gzip.GzipFile(fileobj=tmp, mode="wb", filename="", mtime=0, compresslevel=9)`. `.tar.gz`: the same gzip wrapper around `tarfile.open(fileobj=..., mode="w|")` with one `TarInfo(name=member, mtime=0, mode=0o644, uid=0, gid=0, uname="", gname="")`. `.zip`: `ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))`, `ZIP_DEFLATED`, `compresslevel=6`. bz2 and xz keep pandas (their headers hold no name or time). Claim: two runs give byte-identical files for the same input, Decoy version and zlib build.
4. O3 (engine): a pass-through `large_string` column is written as `string` on every route. Chunked: the passthrough branch of `build_schema_rule` (`src/decoy_engine/execution/native/_chunked_schema_rule.py:294`) records `pa.string()` for a `large_string` field and casts each batch with `narrow_text`. Out-of-core: `passthrough_array` (`src/decoy_engine/kernel/_scalar.py:36`) narrows each chunk with `narrow_text` and never the combined array. Over 2 GiB: when one batch's text does not fit 32-bit offsets, `narrow_text` raises `ArrowInvalid`; the caller splits that batch in halves until each half narrows, and writes the halves as chunks of one `string` column. A run that works today never gets a new refusal. Contract 3.4's "the source type for passthrough" becomes "`string` for a `string` or `large_string` source; the source type otherwise".

## 5. Enumerations

### 5.1 Callers and consumers of what changes

- Tier registry (engine): the map sentry, the marker sentry, the docs build. No runtime caller.
- `FormulaStrategy`: `src/decoy_engine/execution/_strategies/_formula.py:18`, the draw-site label at `src/decoy_engine/execution/native/_draw_sites_mask.py:375`.
- `REPORT_SOURCE_AMBIGUOUS`: raised at `C:src/decoy/cli/_sources.py:335`, exported at `C:src/decoy/cli/io/__init__.py:78`, tested at `C:tests/e2e/config_explicit/test_config_explicit_reports.py:230`.
- Outbound: the four `urlopen` sites; `C:packaging_tools/smoke_install.py:290` (the upgrade document and its `file://` artifact URLs); `C:src/decoy/telemetry.py:93`.
- `when:` frame: `src/decoy_engine/execution/_when_gate.py:248`, `src/decoy_engine/execution/native/_when_mask.py:59`, `src/decoy_engine/execution/_unified_slice_when.py:88`.
- Lossless ingestion: the five sites in 4.3 item 2.

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
| pass-through text over 2 GiB in one batch | written as `large_string` | written as `string` in split chunks, no refusal | AT-O3e |

No exit integer changes meaning.

### 5.3 Routes

| Route | O1 (`when:` frame and ingestion) | O3 (pass-through type) |
|---|---|---|
| whole-frame (`run_pipeline`) | `_pandas_adapter.py` ingestion; `_when_gate.py` frame | already `string` |
| sequential | `_sequential.py` ingestion; `_when_gate.py` frame | already `string` |
| `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:382`) | `_when_gate.py` frame | already `string` |
| `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:589`) | `_when_mask.py` | `_chunked_schema_rule.py` passthrough branch |
| unified slice | `_unified_slice_when.py:88` | already `string` |
| out-of-core FK | no `when:` (rejected at plan time) | `kernel/_scalar.py::passthrough_array` |
| full-frame mixed route diagnosis | `_pipeline_full_frame.py:77` | n/a |

Known limit: there is no route registry, so AT-O1a and AT-O3a carry the route list as a constant in the test module, with a map row that says so. A new route must add itself; the same limit applies to the other route-parametrized suites.

### 5.4 FK shapes

- An FK key column read by `when:`: already lossless at ingestion; `when_eval_frame` treats it like any integer column. AT-O1d.
- An FK key column passed through as `large_string`: narrowed to `string`; values are unchanged, so joins match. AT-O3b.
- No other FK shape is touched.

### 5.5 Fields

| Field | Change | Where |
|---|---|---|
| reason `layout.report_source_ambiguous` | renamed `report.source_ambiguous` | `--json` error `code`, CI report |
| reasons `url_scheme_refused`, `url_redirect_refused`, `notify_url_scheme_refused` | added | `--json` error `code` |
| Arrow type of pass-through text | `large_string` to `string` on `run_mask_chunked` and out-of-core | Parquet schema |
| Arrow type of a null-bearing integer column read by `when:` and passed through | `double` to `int64` on whole-frame and sequential | Parquet schema, CSV text (`5` instead of `5.0`) |
| gzip header FNAME and MTIME; tar member mtime, uid, gid, names; zip entry `date_time` | removed or fixed | compressed output bytes |
| registry tier per public object | added | docs, both maps |

### 5.6 Output surfaces

- Parquet schema and CSV text of the routes in 5.3 (O1, O3).
- Compressed CSV bytes (O2).
- Rows selected by `when:` on integer columns with a value outside `[-2**53, 2**53]` (O1).
- `--json` error `code` (S4, S6).
- Docs: contract sections 1, 3.1, 3.3, 3.4 and new 3.6; both frozen maps; `C:docs/release/versioning.md`; the SDK, provider and Python API pages.
- Tag classification. The rule (Q9 answered yes, and the answer covers the builder's reclassifications under this rule): a tag that reaches disk, `--json`, a signed or hashed record, or a derivation input is frozen; a tag that never leaves the process is internal and needs a one-line reason. Frozen tags that name a file or record format go in the 3.1 block with a map row and a pinning test that reads the tag from the written artifact; frozen tags that are derivation labels go in a new 3.3 list, pinned by the existing determinism goldens. Proposed, for the S7 builder to check at each write site: frozen formats `decoy-publication/v1`, `publication/v1`, `pinned-plan/v1`, `pinned-plan-fingerprint/v1`, `decoy-safe-output/v1`, `decoy-quarantine/v1`, `decoy-support-bundle/v1`, `decoy-reasons/v1`, `checkpoint-index/v1`, `decoy-resume-key-check/v1`, `decoy-model-pack/v1`, `dps-marginal/v3`, `post-scan-integrity/v2`, `canary-span-report/v1`, `flagged-redacted/v1`, `flagged-redacted/v2`, `decoy.evidence.statement/v1`, `decoy.trust-policy/v1`, `decoy.required-catalog/v1`, `immutable_directory/v1`; frozen derivation labels `fpe-key/v1`, `tokenize-key/v1`, `secret-provider/v1`, `decoy.shuffle.unkeyed/v1`, `name_email/v1`, `canary-span-normalization/v1`, `policy-expansion/v1`; internal candidates `phase-result/v1`, `phase-event/v1`, `decoy-probe/v1`, `decoy-telemetry/v1`, `distribution-snapshot/v2` if it is already covered by 3.1 under another spelling. The builder's census output is the final list; the count today is 32.

## 6. Frozen contracts

- `docs/compatibility-contract.md`: section 1 (renames table; "Pre-GA corrections taken with the freeze batch"), 3.1 (tag block grows), 3.3 (derivation label list), 3.4 (CLI line and the pass-through sentence), new 3.6.
- `docs/frozen-surfaces.md` and `C:docs/release/frozen-surfaces.md`: tier rows; new rows for hidden CLI names, the reserved-name snapshot, the gate code snapshot, the route-list known limit, the f-string tag known limit.
- `C:docs/release/versioning.md`: "Public surface" gains an "Experimental" list.
- Reason registries: one rename and three additions (CLI).
- Output bytes: O1, O2, O3, each with a `Breaking:` fragment and a shape-changelog entry, so `check_shape_changelog.py` passes at REL-GATE G3. S1 has a `Removed:` fragment.
- Must not change: the draw-site label and census rows of `FormulaStrategy.apply` (AT-S1b); `when:` selection for null rows and for values inside `[-2**53, 2**53]` (AT-O1b).

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
| F10 | O1 stops selecting null rows and leaves rows unmasked | Q10: today's null semantics kept; AT-O1b matrix over every operator |
| F11 | The ingestion column sets drift apart again | `lossless_int_columns` plus AT-O1e |
| F12 | O2 drops the atomic staging | the writer runs inside the staging context; AT-O2c |
| F13 | O3 refuses or corrupts text over 2 GiB | split-then-narrow; AT-O3e |
| F14 | A tag classified internal reaches disk | the rule in 5.6; S7 builder checks each write site |
| F15 | FAKER-MIGRATE and this batch both move goldens and one overwrites the other | order in 10.5; the second to land reruns the golden tools on its own head |

## 8. Acceptance tests (red first)

| Id | Test | Red because | Mutation | Slice |
|---|---|---|---|---|
| AT-X0a | every object in `decoy_engine.__all__` has exactly one tier, keyed by identity; root re-exports of sdk objects share the sdk tier | no tiers | give `decoy_engine.FileSource` a second tier row | X0 |
| AT-X0b | every experimental class or function has a docstring starting with `EXPERIMENTAL_MARKER`; every experimental constant's module docstring starts with it and names the constant | no markers | drop the marker from `register_faker_provider` | X0 |
| AT-X0c | the registry equals the map's tier rows, both ways | no registry | add a name to the map only | X0 |
| AT-X0d | contract section 3.6 lists the same experimental names as the registry | no section | delete one name from 3.6 | X0 |
| AT-X0e | census: every name in the `__all__` of every public subpackage (walk of `decoy_engine`, excluding `_`-prefixed and `internal`) has an explicit tier; the walk finds at least 39 packages and includes `decoy_engine.sdk` | no census | skip one package in the walk | X0 |
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
| AT-S6d | import sentry over `C:src/`: no module outside the (path, name) allowlist imports a network module in any covered spelling (10.7) | four direct sites | `import urllib.request as r` in `notify.py` | S6 |
| AT-S6e | `upgrade_artifact`: a local test server redirects https to https, followed; https to http, refused with `url_redirect_refused`; `update_check` refuses every redirect; `notify_webhook` behaves as today | no per-purpose rule | follow https-to-http | S6 |
| AT-S6f | the `otel` purpose refuses exactly what `validate_endpoint` refuses today (table-driven from its current tests) | guard | drop the header rule | S6 |
| AT-S7a | engine tag census: every literal matching `"[a-z][a-z0-9._-]*/v[0-9]+"` under `src/` is in 3.1, the 3.3 label list, or `INTERNAL_TAGS` with a reason | 32 unlisted | add a new tag literal | S7 |
| AT-S7b | CLI tag census: same rule over `C:src/` and the CLI map | no sentry | add `"x.tag/v1"` | S7 |
| AT-S7c | each new 3.1 tag has a map row and a pinning test that reads it from a written artifact | no rows | drop one map row | S7 |
| AT-S7d | contract section 1 renames table lists every pair of the taxonomy map, and each old name is in the retired-name residual list | no table | drop `run_storm` | S7 |
| AT-O1a | for every route in 5.3: an integer column holding `2**53`, `2**53 + 1` and a null; `when: "id == 9007199254740993"` selects exactly one row | float64 rounding selects two | skip the object path in `when_eval_frame` | O1 |
| AT-O1b | null-row matrix: for `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `not (==)`, `not (<)`, `and`, `or`, on a null-bearing integer column with ordinary values and with a value beyond 2**53, over chunk sizes 1, 2, 3 and whole-frame, the selected rows equal a pinned table of today's selection (null rows selected by `!=`, `not in`, `not (...)`) | object path without `NaN` nulls selects differently | use `pd.NA` for null in the object path | O1 |
| AT-O1c | on random frames (ints across `+-2**63`, nulls), the mask equals a Python-int reference evaluator that uses `NaN` semantics for null | float64 path | drop the range check | O1 |
| AT-O1d | an FK integer key read by `when:` still matches the DE-10 contract | guard | drop FK columns from the set | O1 |
| AT-O1e | drift sentry: `fk_columns_for_table` and `to_pandas_fk_safe` at the five ingestion sites take their column set only from `lossless_int_columns`; other callers are on a (path, reason) allowlist | sets built by hand | build the set by hand in `_chunked_carry.py` | O1 |
| AT-O1f | a null-bearing integer column read by `when:` and passed through is `int64` on whole-frame and sequential | written as `double` | leave `when:` columns out of the set | O1 |
| AT-O2a | two runs to `out.csv.gz`, `out.csv.tar.gz` and `out.csv.zip` give byte-identical files | time in headers | `mtime=None` | O2 |
| AT-O2b | gzip header: byte 3 has the FNAME bit clear and bytes 4 to 8 are `00 00 00 00`; tar member has mtime 0, uid 0, gid 0, empty names; zip entry `date_time` is `(1980, 1, 1, 0, 0, 0)` | staging name and time stored | pass `filename=tmp.name` | O2 |
| AT-O2c | a failure after chunk one keeps the old output for each compressed suffix | guard | open the final path directly | O2 |
| AT-O2d | the decompressed CSV equals the uncompressed run's bytes | guard | change the line terminator | O2 |
| AT-O3a | for every route in 5.3, a pass-through `large_string` column is `string` in the output | `run_mask_chunked` keeps `large_string` | remove the narrow in the passthrough branch | O3 |
| AT-O3b | an FK pass-through `large_string` key joins the same rows | guard | narrow the parent only | O3 |
| AT-O3c | AT-E3-2 (`tests/native/test_chunked_nondet_categorical_admission.py:709`) expects `string`, changed in the same commit as the cast; the gate checks the edit is the type assertion only | pins `large_string` | none: diff-checked at the gate | O3 |
| AT-O3d | out-of-core: `passthrough_array` narrows each chunk; it never calls `combine_chunks` on a `large_string` input | combined first | narrow after `combine_chunks` | O3 |
| AT-O3e | with `narrow_text` patched to refuse arrays above a small byte size, a long pass-through column is written as `string` in split chunks and the run exits 0 | `ArrowInvalid` raised | re-raise instead of split | O3 |

## 9. Placement

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/contracts/stability.py` | new: `TIERS`, `EXPERIMENTAL_MARKER`, `INTERNAL_TAGS`, `DERIVATION_LABELS` | Versioned contracts | `contracts/distribution_snapshot.py` |
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
| `src/decoy_engine/execution/_pandas_adapter.py`, `_sequential.py`, `_pipeline_full_frame.py`, `_chunked_carry.py`, `native/_when_mask.py` | changed (call sites) | Pipeline spine; Native companion bridge | - |
| `tests/sentry/defects/test_lossless_int_columns.py` | new | Sentry test (recurring-defect) | - |
| `src/decoy_engine/execution/native/_chunked_schema_rule.py` | changed (passthrough branch) | Native companion bridge | - |
| `src/decoy_engine/kernel/_scalar.py` | changed (`passthrough_array`) | Arrow kernels | - |
| `C:src/decoy/__init__.py`, `C:src/decoy/api.py` | changed | Python API | `_LAZY_API` |
| `C:docs/release/frozen-surfaces.md`, `C:docs/release/versioning.md`, `C:docs/roadmap/post-1.0-plan.md` | changed | Release runbooks, logs and maps; Roadmap | - |
| `C:tests/sentry/release/test_frozen_surface_map.py` | changed | Release runbooks, logs and maps | - |
| `C:tests/sentry/release/test_hidden_names.py`, `C:tests/sentry/release/test_tag_census.py` | new | Sentry test | `test_frozen_surface_map.py` |
| `C:src/decoy/cli/demo.py` | changed | Command module | - |
| `C:src/decoy/cli/io/_layout_errors.py` | changed (`REPORT_DESCRIPTORS`) | Project layout services | - |
| `C:src/decoy/_outbound.py` | new | Private shared filesystem or process primitives | `_atomic.py` |
| `C:src/decoy/notify.py`, `C:src/decoy/telemetry.py`, `C:src/decoy/cli/upgrade.py`, `C:src/decoy/distribution/installer.py` | changed | Notifications, telemetry; Command module; Shipped install and update | - |
| `C:tests/sentry/io_policy/test_outbound_choke_point.py` | new | Sentry test | `test_update_check_no_identifiers.py` |
| `C:src/decoy/cli/io/_compression.py`, `C:src/decoy/cli/io/_targets.py` | changed (one compressed writer) | Source readers and target writers | - |

No new module under `src/decoy_engine/execution/` (frozen at 103) or at the engine root (at its fan-out cap). The registry goes in `contracts/`.

## 10. Design notes

### 10.1 One registry per repo, keyed by object

`contracts/stability.py` holds `TIERS`, a tuple of `(module, name, tier)` rows, plus the marker and the two tag lists. The census sentry imports every public package, resolves each `__all__` name to its object, and groups by `id(obj)`; each group must map to exactly one tier. Constants (ints, strings) are not unique objects, so constants are matched by `(module, name)` and their defining module wins. The CLI keeps `EXPERIMENTAL_API` beside `_LAZY_API`. No decorator (mutmut 3.7, API reference signatures).

### 10.2 Hidden names

The sentry reads `walk()` from `C:tests/command_tree.py` and compares the hidden set to one map row listing `name: tier`. Internal names start with `_`; frozen-hidden names are frozen like visible ones.

### 10.3 Pass-through narrowing

Chunked: `SchemaRule.passthrough_types` records `pa.string()` for a `large_string` field, so the per-batch cast in `_safe_cast` produces `string`. Out-of-core: `passthrough_array` returns a `pa.ChunkedArray` of narrowed chunks when given a chunked input; its two callers (`execution/native/_kernels_scalar.py:79`, `execution/out_of_core/_mask.py:214`) already pass the result to writers that accept chunked arrays; the builder confirms both. Split rule: on `ArrowInvalid` from `narrow_text`, slice the batch in two and retry each half, down to one row (a single value over 2 GiB is not representable as `string` and is not representable in Parquet either, so today's run already fails there).

### 10.4 Compressed writer

One function in `_compression.py` returns a context manager that yields a text stream for `to_csv` and closes the gzip, tar or zip layers in its `finally`. Tar needs the member size in advance, so the CSV is written to a second staging temp first and then added with `TarInfo.size` set; zip uses `ZipFile.open(zinfo, "w")` streaming. Compression levels are pinned to today's library defaults (gzip 9, zip deflate 6), so the deflate stream bytes do not change, only the headers.

### 10.5 Order with other plans (Q11)

- FAKER-MIGRATE (`E:plan/faker-migrate`) edits contract sections 1 and 3.3, adds Breaking fragments, rewrites the testflight goldens, and has its own engine release and CLI repin. Order: this batch's engine release goes first; FAKER-MIGRATE S2 comes after. Whichever lands second reruns the golden tools (section 5.6 of that plan) on its own head and rebases the contract section 1 and 3.3 text; it never edits a golden by hand.
- PROP-batch C-F1b changes `C:src/decoy/cli/io/_targets.py` `write_targets` and the demo writer; O2 changes the two write functions in the same module, and S2 changes `C:src/decoy/cli/demo.py`. O2 and S2 start after C-F1b merges and rebase on it.
- PROP-batch E-S1a and E-S1b delete root bindings and `ExecutionContext` members. X0's census requires registry rows equal to `__all__` both ways, so whichever lands second removes or adds the rows in its own diff. Recommended: E-S1a first, then X0.
- REL-GATE G3 runs both map sentries, so X0, X1, S2, S4, S5 and S7 merge before G0.
- One engine release carries X0, S1, S5, S7, O1 and O3; one CLI repin follows.

### 10.6 `lossless_int_columns`

It moves the five hand-built unions into one function in `_fk_keys.py` (the module that owns the DE-10 contract). `adapter_fk_safe_columns` in `_chunked_carry.py` becomes a call to it, which fixes its drift (missing declared ints and group anchors). Other `to_pandas_fk_safe` callers with a deliberately narrower set (`_mixed_fk_bridge.py`, `_transforms_table.py`, `_unified_slice_admission.py`, `native/_faker_null_mask.py`, `native/_group_key_kernel.py`) go on the AT-O1e allowlist with a reason each.

### 10.7 Outbound purposes and the import sentry

| Purpose | Schemes | Redirects | Caller |
|---|---|---|---|
| `upgrade_document` | https, file | https to https only | `upgrade --url`, default version document |
| `upgrade_artifact` | https, file | https to https only (GitHub release downloads redirect to a CDN) | installer download, artifact URLs inside the document (`C:packaging_tools/smoke_install.py:290`) |
| `update_check` | https | none (existing `RefuseRedirects`) | `_update_check.py` |
| `notify_webhook` | https, http | as today | `--notify webhook:` |
| `notify_slack` | https | as today | `--notify slack:` |
| `otel` | the rules of today's `validate_endpoint`, moved unchanged | as today (requests) | telemetry |

Each hop of a followed redirect is re-checked against the purpose's schemes. Import sentry spellings covered: `import urllib.request`, `import urllib.request as x`, `from urllib import request`, `from urllib.request import urlopen` (any name), `import http.client` and `from http import client`, `import requests`, `import urllib3`, `import httpx`, `import socket`, `import smtplib`, and `importlib.import_module` or `__import__` with any of those names as a string literal. Allowlist (path, name): `_outbound.py` `urllib.request`; `_update_check.py` `urllib.request`; `telemetry.py` `requests`; `notify.py` `smtplib`. Known limit: a dynamic import with a computed name is not seen.

## 11. Size

| Slice | Source lines | Test lines | Docs lines |
|---|---|---|---|
| X0 | 120 | 260 | 180 |
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
| O3 | 60 | 240 | 30 |

S7 is split because the per-tag pinning tests put it past 700 lines. Every slice is under the 800-line budget.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| X0 | engine | contract 3.6 and section 1 entry, `contracts/stability.py`, census and marker sentries, docstrings | R1 | AT-X0a to AT-X0f | E-S1a (10.5) | T1 plus the new sentries; Codex |
| X1 | CLI | `EXPERIMENTAL_API`, CLI map and `versioning.md` tiers, API docstrings, `library` tier `gate` | R1 | AT-X1a to AT-X1c | X0 | T1; Codex |
| S1 | engine | delete the two base modules and `pyproject.toml` entries; `FormulaStrategy` plain; Removed fragment | R1 | AT-S1a, AT-S1b | - | T1 plus formula and draw-site tests; mutations on `formula.py` |
| S2 | CLI | remove demo `--ref`, `--rows`, `_generate_ref_datasets`; hidden-name sentry | R1 | AT-S2a, AT-S2b | X1; PROP C-F1b | T1; Codex |
| S4 | CLI | `report.source_ambiguous`, `REPORT_DESCRIPTORS`, code snapshot, post-1.0 row | R2 | AT-S4a, AT-S4b | - | T2; Dennis and Codex |
| S5 | engine | reserved names, guard sentry, snapshot | R2 | AT-S5a to AT-S5c | X0 | T2; Dennis and Codex |
| S6 | CLI | `_outbound.open_url`, purposes, redirect handlers, value-free notify errors, import sentry | R2 | AT-S6a to AT-S6f | - | T2 plus the smoke-install test; Dennis and Codex |
| S7a | engine | tag census, 3.1 and 3.3 rows, map rows and pinning tests, `INTERNAL_TAGS` | R1 | AT-S7a, AT-S7c | X0 | T1; Codex |
| S7b | CLI | CLI tag census; contract section 1 renames table and residual list | R1 | AT-S7b, AT-S7d | S7a | T1; Codex |
| O1 | engine | `when_eval_frame`, `lossless_int_columns`, five call sites, drift sentry, Breaking fragment | R2 | AT-O1a to AT-O1f | - | T2 over every route; mutations on both functions; Dennis and Codex |
| O2 | CLI | one compressed writer for gz, tar.gz, zip; Breaking fragment | R2 | AT-O2a to AT-O2d | PROP C-F1b | T2; Dennis and Codex |
| O3 | engine | narrow in the schema rule and `passthrough_array`, split rule, contract 3.4, AT-E3-2 | R2 | AT-O3a to AT-O3e | - | T2 over every route; Dennis and Codex |

Order: S1, O1 and O3 start at once. X0 starts after E-S1a. X1, S5 and S7a follow X0; S7b follows S7a. S4 and S6 start at once on the CLI; S2 and O2 wait for PROP C-F1b. One engine release (X0, S1, S5, S7a, O1, O3), before FAKER-MIGRATE S2; one CLI repin. Target: all merged before REL-GATE G0 on 2026-12-04.

## 12.1 Done when

Every slice is merged with its acceptance tests green and its mutations red; both map sentries are green on the engine release head and the CLI repin head; the Breaking fragments for O1, O2, O3, S2, S4, S5 and S6 and the Removed fragment for S1 are in `changelog.d/` or the CLI `CHANGELOG`; contract section 1 lists the freeze batch corrections.

## 13. Recurring-defect class check

- A test weakened to pass: AT-O3c is the only edited existing assertion; the gate checks it changes the type only.
- Two copies of a central mechanism: one tier registry per repo, one outbound function, one lossless-column function, one `when:` frame function, one compressed writer. The ingestion drift found in `_chunked_carry.py` is the class this closes.
- A frozen surface changed without its records: each output slice carries its contract sentence, map row and fragment in the same commit.
- Value-free errors: the new refusals name the purpose and scheme only; `NotifySpecError` stops echoing the spec.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a webhook token in an error; a `when:` literal in a log) | refusals name purpose and scheme only; `NotifySpecError` fixed text; `_eval_predicate` already logs no expression | AT-S6b, AT-S6c | echo the spec | S6, O1 |
| 2 | Cleanup on every exit (gzip, tar or zip layer left open; staging temp left) | one writer context closes every layer in its `finally` inside the staging context | AT-O2c | close only the outer layer | O2 |
| 3 | State completeness (each public object has a tier; each tag has a class; each operator has a null rule) | registry plus census; the AT-O1b operator matrix | AT-X0a, AT-X0e, AT-S7a, AT-O1b | allow a name with no row | X0, S7a, O1 |
| 4 | Route coverage (one route keeps `large_string` or a float64 frame) | one narrow point per writer family and one frame function used by every route | AT-O1a, AT-O3a over 5.3 | skip the narrow in the schema rule | O1, O3 |
| 5 | Referential integrity (FK keys after the narrow or the frame change) | FK keys stay on the DE-10 path; the narrow keeps values | AT-O1d, AT-O3b | narrow the parent only | O1, O3 |
| 6 | Untrusted input (a URL from a flag or a version document) | per-purpose scheme allow list; every redirect hop re-checked | AT-S6a, AT-S6e | follow https to http | S6 |
| 7 | TOCTOU or check-then-use (scheme checked, a different URL opened) | `open_url` parses once, checks and opens that parsed value; redirect hops are checked inside the handler before the request | AT-S6a, AT-S6e | check, then open a re-read string | S6 |
| 8 | Weak proof (a sentry that passes on an empty set; a guard labelled as a red test) | each sentry asserts a minimum set and a known member; guards are labelled | self-tests; AT-X0e floor of 39; AT-S5a labelled | make the walk return nothing | X0, S2, S5, S6, S7a |
| 9 | Refactor drift (S1 changes formula output; the ingestion move changes a set) | S1 removes bases only; `lossless_int_columns` returns the old union plus `when:` columns, checked per site | AT-S1b, AT-O1e | rename `apply`; drop declared ints | S1, O1 |
| 10 | Frozen contract drift (contract, map and code disagree) | the registry is the source; sentries compare contract 3.6, both maps and docstrings to it | AT-X0c, AT-X0d, AT-S5c, AT-S4b, AT-S7c | edit the map only | X0, X1, S4, S5, S7a |

## 14. Pre-mortem

- "The tier is a label nobody reads." The marker is the first word of each docstring and doc page; `versioning.md` lists it next to the frozen list.
- "`decoy library` stayed at `gate` and 1.0 shipped." AT-X1c fails in ga.
- "O1 stopped masking null rows." Q10 keeps today's null semantics; AT-O1b pins every operator.
- "O1 is slow on big tables." Only a column with a value beyond 2**53 takes the object path; every other column keeps today's dtype and numexpr.
- "S6 broke `decoy upgrade` from GitHub releases." `upgrade_artifact` follows https-to-https redirects; AT-S6e.
- "S6 broke the release smoke." `file` stays allowed for both upgrade purposes; AT-S6a uses the smoke's call.
- "O2 changed the compressed bytes beyond the header." Compression levels are pinned to today's defaults; AT-O2d checks the CSV content.
- "O3 refused a huge text column." The split rule; AT-O3e.
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
| Q10 | `when:` null semantics with exact integers | Decided (owner, 2026-11-18): keep today's behaviour. `!=` and `not` still select null rows, `not in` stays consistent with that, and O1 changes selection only for integers at or above 2**53 | Dennis round 1 B1 |
| Q11 | Order against FAKER-MIGRATE: this batch's engine release first, FAKER-MIGRATE S2 after, the second to land reruns the golden tools on its own head | Recommended: yes; owner to confirm | Dennis round 1 H9 |

## 16. Unresolved

- Q3 is applied at G0; X1 builds the `gate` value and the ga refusal either way.
- Q11 is open. If the owner puts FAKER-MIGRATE first, only the order line in section 12 changes; the rerun rule stays.
- The S7a builder may move a tag between classes under the 5.6 rule; that is covered by Q9 and recorded in the slice's build record.
