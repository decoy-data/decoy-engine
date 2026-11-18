Status: plan (revision 1, 2026-11-18; not yet reviewed)

# 1.0 freeze batch: the experimental tier, the frozen surface, and the output shapes that change before the freeze

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

This plan covers the three 1.0 rows that had no plan: EXPERIMENTAL-TIER, FREEZE-SURFACE and FREEZE-OUTPUT (1.0 scope triage, `C:docs/records/2026-11-18-1.0-scope-triage.md`, CLI branch `claude/focused-sagan-0arhsp`, PR #320). They are planned in that order because each one decides the next: the tier says which names are not frozen, so FREEZE-SURFACE only has to clean up what stays frozen, and FREEZE-OUTPUT only has to fix output bytes of frozen routes. Every slice lands before row 93 (REL-GATE), and every engine slice lands before the D-4 engine release (REL-GATE G1).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`. The plan lives in the engine repo on branch `plan/freeze-batch` because most of the slices and both contracts it edits are engine-owned.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1 for docs, registries and the dead-base removal; R2 for output bytes, a frozen `--json` reason code and the outbound URL check), `development-loop.md` (PLAN: scope, behaviour and failure modes, acceptance tests first with their mutation, placement, slice table, owner questions), `api-and-compatibility.md` (consumer inventory, explicit breaking changes, contract tests), `cross-cutting-concerns.md` (one choke point plus a sentry and its mutation), `security.md` (outbound URL schemes), `data-and-migrations.md` (output format bytes), `testing.md` (T0 to T2, mutations), `proportionality.md`, `reuse-first.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2 overall, because O1 to O3 change output bytes and S4 changes a reason code a user can see in `--json`. X0, X1, S1, S2, S5 and S7 are R1 (docs, registries, sentries, dead code). Approver: Cam (owner) for the plan and the owner questions; Dennis then Codex for the plan gate.

Why 1.0: all three rows pass the "freeze" test of the triage. After 1.0, any of these changes is a 2.0 break under the triage's definition (a public name, a default, an output byte, an exit code, a reason string, a schema field, a report tag, or a new refusal for a config or run that is valid today). The tier itself must exist before 1.0 or every public name is frozen by default.

## 1. Guarantee and non-goals

Guarantees after this batch:

- G1. Every public name of the engine (`decoy_engine.__all__`, `sdk.__all__`, `providers.__all__`) and of the CLI (`_LAZY_API`, the command and option tree) is in exactly one tier: frozen, experimental, or internal. A sentry fails when a name has no tier or two.
- G2. An experimental name says so in its docstring and its doc page, with the same fixed marker text. A sentry checks the marker against the registry.
- G3. Hidden CLI options and commands are listed with a tier. A new hidden name fails the build until it is listed.
- G4. Every `"<name>/vN"` format tag literal in engine and CLI source is either in the frozen tag block (contract 3.1, CLI map) or on an internal list with a reason. A new tag fails the build until it is classified.
- G5. The `when:` grammar's keyword literals are all reserved names, and the reserved set is pinned by an exact snapshot.
- G6. Every outbound URL the CLI opens goes through one function that checks the scheme.
- G7. Three output shapes are fixed before the freeze: `when:` on nullable integer columns selects the same rows on every chunking; a `.gz` CSV target has no file name and a zero mtime in its gzip header; a pass-through string column has one Arrow type on every route.

Non-goals:

- No runtime `ExperimentalWarning` (owner question Q2, recommended no).
- No change to the experimental surfaces themselves (no wiring of the connector SDK entry point, no `load_custom_providers` caller, no `api.scan` port to `scan_sources`). They are labelled, not finished. Audit J2 moves to v1+ (Q4).
- No new public name. FREEZE-SURFACE removes or relabels; it does not add API.
- No rename of experimental names (the `decoy_engine.FileSource` and `decoy_engine.config.FileSource` collision stays; it is a 1.x candidate because the SDK is experimental).
- No snapshot of every CLI reason code. Only the gate and warning vocabulary is pinned (S4); the other code tables are a known limit in the CLI map.
- Platform: parked. No platform slice.

## 2. Established solutions

| Concern | Established solution | What we take |
|---|---|---|
| Stability tiers | Node.js Stability Index (0 Deprecated, 1 Experimental, 2 Stable, 3 Legacy); PEP 411 provisional packages; Kubernetes alpha, beta, GA; Rust `#[unstable]`; Go `x/exp` | Three tiers only: frozen (Stable), experimental (Node 1, PEP 411 "provisional"), internal. The PEP 411 rule: a provisional name may change in a minor release, and the docs must say so at the top of the page. |
| Marking a name | optuna and MLflow `@experimental` decorators (docstring prefix plus a warning) | The docstring prefix only, driven by one registry tuple per repo. No decorator: mutmut 3.7 skips decorated-class bodies, and a decorator on a function changes its `__wrapped__` and signature in the API reference. |
| Gate-time tier decision | Kubernetes feature gates graduate at a named release | `decoy library` gets the tier value `gate`; a sentry refuses `gate` once `RELEASE_PHASE == "ga"`, so the decision cannot be forgotten. |
| Public surface check | `griffe check` (API diff), Typer `utils docs` | Reuse the existing map sentries and `C:tests/command_tree.py`; `griffe check` stays the REL-GATE Q6 post-launch item. |
| gzip header | RFC 1952 (FNAME optional, MTIME 0 means "no time"); Python `gzip.GzipFile(filename="", mtime=0)` | Write the stream ourselves with `filename=""` and `mtime=0` instead of pandas' `compression="gzip"`. |
| Exact integers with nulls | pandas nullable `Int64` family; the existing DE-10 contract `execution/_fk_keys.py::to_pandas_fk_safe` | Reuse `to_pandas_fk_safe` for every integer column a `when:` predicate reads, not only FK columns. |
| URL scheme allow list | OWASP SSRF guidance (allow list, not deny list); `urllib.request` with a custom opener | One CLI function with a per-purpose allow list; redirects keep the existing `RefuseRedirects` opener. |

## 3. Reuse inventory

| Need | Existing piece | Path |
|---|---|---|
| Engine frozen map and sentry | RG-F1 map, `OTHER_SURFACES`, one-row rule | `docs/frozen-surfaces.md`, `tests/sentry/release/test_frozen_surface_map.py` |
| CLI frozen map and sentry | RG-F2 map, `findings(text)` | `C:docs/release/frozen-surfaces.md`, `C:tests/sentry/release/test_frozen_surface_map.py` |
| CLI public names | `_LAZY_API` frozenset | `C:src/decoy/__init__.py` |
| CLI command tree | `walk`, `visible_paths`, `registry` | `C:tests/command_tree.py` |
| Retired names | residual-name sentry | `C:tests/sentry/release/test_retired_name_residual.py` |
| Contract tag block | contract 3.1 code block, read by the engine map sentry | `docs/compatibility-contract.md` (section 3.1) |
| Reserved `when:` names | `RESERVED_NAMES` | `src/decoy_engine/expressions/_when_parser.py:55` |
| Lossless int-with-null to pandas | `to_pandas_fk_safe` | `src/decoy_engine/execution/_fk_keys.py:314` |
| One predicate eval | `_eval_predicate` | `src/decoy_engine/execution/_when_gate.py:115` |
| CSV compression option | `csv_compression` | `C:src/decoy/cli/io/_compression.py:44` |
| Redirect refusal | `RefuseRedirects` opener | `C:src/decoy/_update_check.py:60` |
| Shape changelog check | `check_shape_changelog.py` (REL-GATE G3) | `C:scripts/release/check_shape_changelog.py` |
| Changelog fragments | `changelog.d/` Breaking fragments | `changelog.d/README.md` |

Nothing new is built where one of these fits. The two new registries (section 9) are tuples, not frameworks.

## 4. Behaviour

### 4.1 EXPERIMENTAL-TIER

Contract text (new section 3.6 "Experimental surfaces" in `docs/compatibility-contract.md`, mirrored in `C:docs/release/versioning.md`):

1. A surface is frozen, experimental or internal. Frozen follows sections 3.1 to 3.5 and section 4. Internal is anything not listed; it may change in any release.
2. An experimental surface may change or be removed in any minor release. The change gets a `Changed` or `Removed` changelog fragment with the word "Experimental" in it. No deprecation window is promised.
3. Determinism is never experimental. Output bytes produced through an experimental surface (a custom provider's values, a connector's rows once masked) follow section 3.3 like any other output. Stored records are never experimental: everything under `.decoy/` is frozen whatever the tier of the command that wrote it.
4. Every experimental name starts its docstring with the marker `Experimental:` and its doc page has the same marker in the first paragraph. The marker text is one constant per repo.
5. An experimental surface becomes frozen by moving its row in the map and removing the marker, in a minor release. It never goes from frozen back to experimental inside a major.

The 1.0 tier lists:

| Repo | Experimental | Source |
|---|---|---|
| engine | connector SDK: `sdk.__all__` and the root re-exports `FileSource`, `FileSink` and the `CAP_*` flags | owner, 2026-11-18 |
| engine | custom providers: `register_faker_provider`, `register_faker_provider_v2`, `register_faker_list_provider`, `unregister_faker_provider`, `load_custom_providers`, `atomic_swap_db_providers` | owner, 2026-11-18 |
| CLI | Python API: `mask`, `scan`, `MaskSecretConfigError`, `ConfigValidationError`, `UnsupportedCloudEndpointError` | owner, 2026-11-18 |
| CLI | `decoy library` command group: tier `gate` (decided at REL-GATE G0) | owner, 2026-11-18; rule in Q3 |

The remaining Providers names (`ProviderRegistry`, `ProviderSpec`, `ProviderError`, `get_default_registry`, `list_generate_faker_providers`, `BackendAdapter`, `AdapterError`, `CapabilityMatrix`) stay frozen: the CLI and the YAML schema use them. Q1 asks the owner to confirm the split.

### 4.2 FREEZE-SURFACE

Seven items, re-weighed by the tier:

1. S1 (engine): delete `internal/base.py` (`ConfigValidator` has no subclass; `MaskingStrategy` has one) and `transforms/base.py`. `FormulaStrategy` becomes a plain class with a module logger. Its class name, method name and module path stay, because the draw-site label `transforms/formula.py::FormulaStrategy.apply` (`src/decoy_engine/execution/native/_draw_sites_mask.py:375`) and two secret-material census rows name it. `transforms.__all__` becomes empty.
2. S2 (CLI): delete demo `--ref` and `--rows` (`C:src/decoy/cli/demo.py:554`) and the never-called `_generate_ref_datasets` (`C:src/decoy/cli/demo.py:401`). A run that passes `--ref` today exits 1 with a deferral message; after S2 it exits 2 with Click's "no such option". That is a change to a hidden, deferred option, recorded in the CLI changelog (Q8). A new hidden-name sentry lists every hidden command and option with a tier: internal (`_scan`, `_gate`) or frozen-hidden (`upgrade --url`, `ci --unsafe-debug-log`).
3. J2 (`api.scan` runs `profile_columns`, the CLI runs `scan_sources`): moved to v1+ because `api.scan` is now experimental. No slice. Q4.
4. S4 (CLI): rename `layout.report_source_ambiguous` (`C:src/decoy/cli/io/_layout_errors.py:159`) to `report.source_ambiguous` and pin the gate and warning code vocabulary (`GATE_CODES`, `WARNING_CODES`, `_CLI_GATE_CODES`) with an exact snapshot. Q5 asks about the namespace.
5. S5 (engine): add `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith`, `endswith` to `RESERVED_NAMES`. A sentry checks that every keyword literal in `when_grammar.lark` is a reserved name, and an exact snapshot pins the set. Later functions use call syntax and need no reservation. Q6.
6. S6 (CLI): one outbound URL function, `C:src/decoy/_outbound.py::open_url(url, purpose)`, with a per-purpose scheme allow list. The four `urlopen` sites (`C:src/decoy/cli/upgrade.py:55`, `C:src/decoy/distribution/installer.py:250`, `C:src/decoy/notify.py:254`, `C:src/decoy/notify.py:319`) call it. An AST sentry allows `urlopen` and `build_opener` only in `_outbound.py` and `_update_check.py`. Q7 gives the allow list.
7. S7 (engine, CLI docs): a "Public renames before 1.0" table in contract section 1 (the detection taxonomy renames, `run_storm` to `profile_columns` and the rest), and a tag census sentry in each repo: every `"<name>/vN"` literal in source is in the frozen tag block or on an internal list with a reason. The engine census starts with 26 unlisted tags, among them `decoy-publication/v1`; each is classified in S7 (section 5.6).

### 4.3 FREEZE-OUTPUT

1. O1 (engine): a `when:` predicate reads integer columns through `to_pandas_fk_safe`, so a nullable integer column becomes its own nullable pandas dtype, not float64. The same predicate then selects the same rows whatever the chunking and wherever the blanks fall. Values at or above 2**53 compare exactly. The change sits in the two places that build the eval frame: `src/decoy_engine/execution/native/_when_mask.py:59` and the frame built before `src/decoy_engine/execution/_when_gate.py:248`. If numexpr refuses a nullable extension dtype, pandas falls back to the python engine; `_eval_predicate` already logs that fallback, and AT-O1c checks the result, not the engine.
2. O2 (CLI): a `.gz` CSV target is written through `gzip.GzipFile(fileobj, mode="wb", filename="", mtime=0)` in `C:src/decoy/cli/io/_targets.py:405` and `:543`. The header then holds no staging name (`.<name>.decoy-<hex>.tmp`) and no time. Two runs of the same pipeline write byte-identical `.gz` files. Archive modes (zip, tar) keep pandas and the existing `archive_name`.
3. O3 (engine): every route writes a pass-through `large_string` column as `string`, as `run_mask_pipeline_chunked` and the whole-frame route already do. One cast point (section 10.3). Contract 3.4's "the source type for passthrough" becomes "`string` for any string-family source; the source type otherwise".

## 5. Enumerations

### 5.1 Callers and consumers of what changes

- Experimental registry (engine): the map sentry, the docstring sentry, the docs build. No runtime caller.
- `FormulaStrategy`: `src/decoy_engine/execution/_strategies/_formula.py:18` (`_V1_FORMULA = FormulaStrategy()`), the draw-site label at `src/decoy_engine/execution/native/_draw_sites_mask.py:375`.
- `REPORT_SOURCE_AMBIGUOUS`: raised at `C:src/decoy/cli/_sources.py:335`, exported at `C:src/decoy/cli/io/__init__.py:78`, tested at `C:tests/e2e/config_explicit/test_config_explicit_reports.py:230`.
- `urlopen`: the four sites in 4.2 item 6; `C:packaging_tools/smoke_install.py:286` calls `decoy upgrade --url file://...`.
- `_eval_predicate`: `src/decoy_engine/execution/_when_gate.py:248`, `src/decoy_engine/execution/native/_when_mask.py:59`, `src/decoy_engine/execution/_unified_slice_when.py:88`.

### 5.2 Exit paths

| Path | Before | After | Test |
|---|---|---|---|
| `decoy demo --ref` | exit 1, deferral message | exit 2, Click usage error | AT-S2a |
| `decoy upgrade --url ftp://x` | urllib error, exit 3 | exit 1, `url_scheme_refused` | AT-S6b |
| notify webhook `file:///etc/passwd` | read and "sent" | refused at config validation, exit 1, `notify_url_scheme_refused` | AT-S6c |
| `when:` on `id` with `null` as a column name | ran, read the column | exit 1, `when_outside_closed_grammar` | AT-S5b |
| report with an ambiguous `--source` | exit 1, `layout.report_source_ambiguous` | exit 1, `report.source_ambiguous` | AT-S4a |
| `.gz` target write fails mid-stream | old output kept | old output kept (staging unchanged) | AT-O2c |

No exit integer changes meaning. The demo case changes from 1 to 2 because the option no longer exists; Q8.

### 5.3 Routes

The output items touch every route that writes a masked table:

| Route | O1 (`when:` frame) | O3 (pass-through type) |
|---|---|---|
| whole-frame (`run_pipeline`) | `_when_gate.py` frame | already `string` |
| sequential | `_when_gate.py` frame | already `string` |
| `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:382`) | `_when_gate.py` frame | already `string` |
| `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:589`) | `_when_mask.py` | `large_string` today; fixed |
| unified slice | `_unified_slice_when.py:88` | covered by the cast point |
| out-of-core FK | no `when:` on this route (rejected at plan time) | Arrow arrays; covered by the cast point |

AT-O1a and AT-O3a are parametrized over every row of this table.

### 5.4 FK shapes

- An FK key column read by a `when:` predicate: already lossless through `to_pandas_fk_safe`; O1 widens the same path to non-FK integer columns. AT-O1d keeps an FK case.
- An FK key column passed through as `large_string`: O3 casts it to `string`; the join key is compared on values, so no FK result changes. AT-O3b.
- No other FK shape is touched.

### 5.5 Fields

| Field | Change | Where |
|---|---|---|
| reason code `layout.report_source_ambiguous` | renamed `report.source_ambiguous` | `--json` error `code`, CI report |
| new reason `url_scheme_refused` | added | `--json` error `code` for `upgrade` |
| new reason `notify_url_scheme_refused` | added | config validation finding |
| Arrow field type of pass-through string columns | `large_string` to `string` on one route | Parquet output schema |
| gzip header FNAME, MTIME | removed, 0 | `.gz` output bytes |
| map column "Tier" | added to both frozen maps | docs only |

### 5.6 Output surfaces

- Parquet schema of `run_mask_chunked` output (O3).
- `.gz` CSV bytes (O2).
- Selected rows of `when:` strategies on nullable integer columns at or above 2**53, or across chunkings (O1).
- `--json` error `code` (S4, S6).
- Docs: contract 3.1, new 3.6, section 1 renames table; both frozen maps; `C:docs/release/versioning.md`; the SDK, provider and Python API pages.
- Tag census classification for the 26 engine tags. Proposed here, checked by the S7 builder, confirmed in Q9. Frozen (persisted or user-visible): `decoy-publication/v1`, `publication/v1`, `pinned-plan/v1`, `pinned-plan-fingerprint/v1`, `decoy-safe-output/v1`, `decoy-quarantine/v1`, `decoy-support-bundle/v1`, `decoy-reasons/v1`, `checkpoint-index/v1`, `decoy-resume-key-check/v1`, `fpe-key/v1`, `tokenize-key/v1`, `secret-provider/v1`, `decoy-model-pack/v1`, `distribution-snapshot/v2`, `dps-marginal/v3`, `post-scan-integrity/v2`, `canary-span-report/v1`. Internal (in-process only, or a derivation label whose bytes are covered by section 3.3): `phase-result/v1`, `phase-event/v1`, `policy-expansion/v1`, `flagged-redacted/v1`, `flagged-redacted/v2`, `canary-span-normalization/v1`, `decoy-probe/v1`, `decoy-telemetry/v1`. The S7 builder checks each against its write site before the list is final; a tag that reaches disk or `--json` is frozen.

## 6. Frozen contracts

- `docs/compatibility-contract.md`: sections 1 (renames table), 3.1 (tag block grows), 3.4 (CLI line and the pass-through type sentence), new 3.6.
- `docs/frozen-surfaces.md` and `C:docs/release/frozen-surfaces.md`: a Tier column or an "Experimental surfaces" section; new rows for hidden CLI names, the reserved-name snapshot, the gate code snapshot.
- `C:docs/release/versioning.md`: "Public surface" gains an "Experimental" list.
- Reason registries: one rename (CLI), two additions (CLI).
- Output bytes: O1, O2, O3. Each lands with a Breaking changelog fragment and a shape-changelog entry so REL-GATE G3's `check_shape_changelog.py` passes.
- The draw-site label and the secret-material census rows of `FormulaStrategy.apply`: must not change (AT-S1b).

## 7. Failure modes

| Id | Failure | Guard |
|---|---|---|
| F1 | A public name added later has no tier and is frozen by accident | map sentry: each public name in exactly one row (AT-X0a, AT-X1a) |
| F2 | An experimental docstring loses its marker in a refactor | marker sentry (AT-X0b, AT-X1b) |
| F3 | `decoy library` ships with tier `gate` | sentry refuses `gate` when `RELEASE_PHASE == "ga"` (AT-X1c) |
| F4 | S1 renames the formula call site and changes masked output | AT-S1b pins the draw-site label and census rows |
| F5 | A hidden option is added after 1.0 without a decision | AT-S2b |
| F6 | The reserved-name addition refuses a real column called `true` or `like` | owner question Q6; the refusal names the column and says to rename it; Breaking changelog fragment |
| F7 | `file://` refused on `upgrade --url` breaks the release smoke | allow list keeps `file` for `upgrade` and the bundle base (Q7); AT-S6a runs the smoke's call shape |
| F8 | A new outbound call bypasses the scheme check | AST sentry (AT-S6d) |
| F9 | O1's nullable dtype pushes numexpr to the python engine and changes a result | AT-O1c compares masks across both engines on the same frame |
| F10 | O1 changes rows selected for a config that worked today | expected for values at or above 2**53 and for chunk-dependent cases only; AT-O1b shows ordinary values select the same rows as before |
| F11 | O2's own gzip writer drops the atomic staging | the writer runs inside the existing staging context; AT-O2c |
| F12 | O3 casts a column the user declared `large_string` | the cast applies to pass-through string-family columns with no declared type; a declared type wins (AT-O3c) |
| F13 | A tag literal is classified internal but reaches disk | S7 builder checks write sites; Q9 confirms the list |

## 8. Acceptance tests (red first)

| Id | Test | Red because | Mutation | Slice |
|---|---|---|---|---|
| AT-X0a | engine map sentry: every name in `decoy_engine.__all__`, `sdk.__all__`, `providers.__all__` is in exactly one row across the frozen and experimental sections | no experimental section | list `FileSource` in both sections | X0 |
| AT-X0b | every name in `contracts/stability.EXPERIMENTAL` has a docstring starting with `EXPERIMENTAL_MARKER` | docstrings lack it | drop the marker from `register_faker_provider` | X0 |
| AT-X0c | the registry equals the map's experimental section, both ways | no registry | add a name to the map only | X0 |
| AT-X0d | contract section 3.6 exists and lists the same names (doc test reading the section) | no section | delete one name from 3.6 | X0 |
| AT-X1a | CLI map sentry: every `_LAZY_API` name is in exactly one tier row | no tier | drop `scan` from the experimental row | X1 |
| AT-X1b | `decoy.mask.__doc__`, `decoy.scan.__doc__` and the three error docstrings start with the CLI marker | no marker | remove the marker from `ConfigValidationError` | X1 |
| AT-X1c | `library` row tier is one of `frozen`, `experimental`, `gate`; `gate` fails when `RELEASE_PHASE == "ga"` | no rule | let `gate` pass in ga | X1 |
| AT-S1a | `decoy_engine.internal.base` and `decoy_engine.transforms.base` do not import; `transforms.__all__ == []` | modules exist | keep `BaseMaskingStrategy` export | S1 |
| AT-S1b | the draw-site label `transforms/formula.py::FormulaStrategy.apply` and both census rows still resolve to a live function; the formula golden output is unchanged | guard: green before and after | rename `apply` to `__call__` | S1 |
| AT-S2a | `decoy demo --ref` exits 2 with "No such option"; `_generate_ref_datasets` is gone | option exists | keep `--ref` hidden | S2 |
| AT-S2b | hidden-name sentry: the set of hidden commands and options from `walk()` equals the map's hidden-names row, with a tier for each | no sentry | add a hidden option to `run` | S2 |
| AT-S4a | the ambiguous `--source` report error carries `report.source_ambiguous` in `--json` | old code | restore the old string | S4 |
| AT-S4b | exact snapshot of `GATE_CODES`, `WARNING_CODES` and `_CLI_GATE_CODES` | no snapshot | add a code to `GATE_DESCRIPTORS` without the snapshot | S4 |
| AT-S5a | every quoted keyword literal in `when_grammar.lark` is in `RESERVED_NAMES` | no sentry | add `"between"` to the grammar only | S5 |
| AT-S5b | `when: "null > 1"` and `when: "like == 1"` are refused with `when_outside_closed_grammar` | names not reserved | remove `like` from the set | S5 |
| AT-S5c | exact snapshot of `RESERVED_NAMES` | no snapshot | remove `match` | S5 |
| AT-S6a | `open_url("file:///tmp/v.json", purpose="upgrade")` opens; `purpose="notify_webhook"` refuses | no choke point | allow `file` for every purpose | S6 |
| AT-S6b | `decoy upgrade --url ftp://x --json` exits 1 with `url_scheme_refused` and does not open a socket | no check | skip the check for `upgrade` | S6 |
| AT-S6c | a notify webhook `file://` URL is a config validation finding `notify_url_scheme_refused`; slack `http://` is refused | no check | allow `http` for slack | S6 |
| AT-S6d | AST sentry: `urlopen` and `build_opener` only in `_outbound.py` and `_update_check.py` | four sites | call `urlopen` in `notify.py` | S6 |
| AT-S7a | engine tag census: every `"<name>/vN"` literal under `src/` is in contract 3.1 or `INTERNAL_TAGS` with a reason | 26 unlisted | add a new tag literal in a module | S7 |
| AT-S7b | CLI tag census: same rule over `C:src/` and the CLI map | no sentry | add `"x-tag/v1"` in a module | S7 |
| AT-S7c | contract section 1 renames table lists every pair of the taxonomy map, and each old name is in the retired-name residual sentry list | no table | drop `run_storm` from the table | S7 |
| AT-O1a | for every route in 5.3: an integer column with values `2**53`, `2**53 + 1` and one null; `when: "id == 9007199254740993"` selects exactly one row | float64 rounding selects two | revert to bare `to_pandas()` in `_when_mask.py` | O1 |
| AT-O1b | the same predicate over the same data with chunk sizes 1, 2, 3 and whole-frame selects the same rows; with ordinary values the selection equals today's | a chunk with a null widens | revert the frame builder in `_when_gate.py` only | O1 |
| AT-O1c | the mask from the nullable frame equals the mask from the python engine on the same frame | guard: catches an engine-dependent result | force float64 for one column | O1 |
| AT-O1d | an FK integer key read by `when:` still matches the DE-10 contract | guard: FK path unchanged | drop the FK columns from the protected set | O1 |
| AT-O2a | two runs of the same pipeline to `out.csv.gz` give byte-identical files | mtime differs | use `mtime=None` | O2 |
| AT-O2b | the gzip header has the FNAME flag clear | staging name stored | pass `filename=tmp.name` | O2 |
| AT-O2c | a failure after chunk one keeps the old `.gz` output (staging unchanged) | guard: staging kept | open the final path directly | O2 |
| AT-O3a | for every route in 5.3, a pass-through `large_string` source column is `string` in the Parquet output | `run_mask_chunked` keeps `large_string` | remove the cast | O3 |
| AT-O3b | an FK pass-through `large_string` key joins the same rows after the cast | guard: values kept | cast the parent only | O3 |
| AT-O3c | a column with a declared `large_string` output type stays `large_string` | guard: declared type wins | cast every string-family column | O3 |
| AT-O3d | AT-E3-2 (`tests/native/test_chunked_nondet_categorical_admission.py:709`) is updated to expect `string`, in the same commit as the cast, and the gate diff-checks it | pins `large_string` | none: the gate checks the edit is the type assertion only | O3 |

## 9. Placement

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/contracts/stability.py` | new: `EXPERIMENTAL`, `EXPERIMENTAL_MARKER`, `INTERNAL_TAGS` | Versioned contracts | `contracts/distribution_snapshot.py` |
| `docs/compatibility-contract.md` | changed | Feature and contract docs | - |
| `docs/frozen-surfaces.md` | changed | Feature and contract docs | - |
| `tests/sentry/release/test_frozen_surface_map.py` | changed (tier rule) | Sentry test (release) | - |
| `tests/sentry/release/test_experimental_marker.py` | new | Sentry test (release) | the map sentry |
| `tests/sentry/release/test_tag_census.py` | new | Sentry test (release) | the map sentry |
| `src/decoy_engine/internal/base.py`, `src/decoy_engine/transforms/base.py` | deleted | Transforms | - |
| `src/decoy_engine/transforms/formula.py` | changed | Transforms | - |
| `src/decoy_engine/expressions/_when_parser.py` | changed (set) | existing expressions package | - |
| `tests/sentry/defects/test_when_reserved_names.py` | new | Sentry test (recurring-defect) | - |
| `src/decoy_engine/execution/native/_when_mask.py`, `src/decoy_engine/execution/_when_gate.py` | changed | Native companion bridge; Pipeline spine | - |
| `src/decoy_engine/execution/_passthrough_type.py` | new, one function | Pipeline spine and routes (fan-out freeze at 104: check headroom; else place it in `execution/chunked/`) | `_pandas_adapter.py` |
| `C:src/decoy/__init__.py` | changed (`EXPERIMENTAL_API`, marker constant) | Python API | `_LAZY_API` |
| `C:src/decoy/api.py` | changed (docstrings) | Python API | - |
| `C:docs/release/frozen-surfaces.md`, `C:docs/release/versioning.md` | changed | Release runbooks, logs and maps | - |
| `C:tests/sentry/release/test_frozen_surface_map.py` | changed | Release runbooks, logs and maps | - |
| `C:tests/sentry/release/test_hidden_names.py` | new | Sentry test | `test_frozen_surface_map.py` |
| `C:tests/sentry/release/test_tag_census.py` | new | Sentry test | - |
| `C:src/decoy/cli/demo.py` | changed | Command module | - |
| `C:src/decoy/cli/io/_layout_errors.py` | changed (descriptor moves to a report table, Q5) | Project layout services | - |
| `C:src/decoy/_outbound.py` | new | Private shared filesystem or process primitives | `_atomic.py` |
| `C:src/decoy/notify.py`, `C:src/decoy/cli/upgrade.py`, `C:src/decoy/distribution/installer.py` | changed (call `open_url`) | Notifications; Command module; Shipped install and update | - |
| `C:tests/sentry/io_policy/test_outbound_choke_point.py` | new | Sentry test | `test_update_check_no_identifiers.py` |
| `C:src/decoy/cli/io/_targets.py` | changed (gzip writer) | Source readers and target writers | `_compression.py` |

The engine root is at its fan-out cap, which is why the registry goes in `contracts/` and not a new root module. Each placement is checked by the CODEMAP path sentries in both repos.

## 10. Design notes

### 10.1 One registry per repo, no decorator

`contracts/stability.py` holds three tuples and one string constant. The map sentry imports it; nothing at runtime does. The CLI keeps `EXPERIMENTAL_API` beside `_LAZY_API` in `C:src/decoy/__init__.py`, so a new lazy name forces a tier decision in the same diff. A decorator would hide the class bodies from mutmut 3.7 and change the API reference signature.

### 10.2 Hidden names

The sentry reads `walk()` from `C:tests/command_tree.py` and compares the hidden set to one map row whose cell lists `name: tier`. Internal names start with `_` by rule; frozen-hidden names are frozen like visible ones, only left out of `--help`.

### 10.3 Pass-through type cast point

One function `passthrough_arrow_type(source_type, declared) -> pa.DataType` returns `pa.string()` for `large_string` and `string_view` with no declared type, and the source type otherwise. `run_mask_chunked` calls it where it assembles the output schema; the other routes already produce `string` and call it too, so a later route cannot diverge. AT-O3a runs over all routes.

### 10.4 gzip writer

The CSV writer opens the staging temp, wraps it in `gzip.GzipFile(fileobj=..., mode="wb", filename="", mtime=0)`, and passes the wrapper to `to_csv` with `compression=None`. The chunked writer keeps one wrapper open across chunks. `csv_compression` keeps the mapping for every other codec; only `gzip` takes the new path. bz2 and xz headers carry no name or time.

### 10.5 Order with other plans

- PROP-batch (`E:plan/prop-batch`, C-F1b, C-S2) touches `C:src/decoy/cli/demo.py` and `C:src/decoy/api.py`. S2 and X1 rebase on whichever merges first; one writer per file at a time.
- REL-GATE G3 runs both map sentries; X0, X1, S2, S4, S5 and S7 add to them, so they merge before G0.
- O1 and O3 ride one engine release with S1, S5 and S7; the CLI repins once (one release and repin at a time).

## 11. Size

| Slice | Source lines | Test lines | Docs lines |
|---|---|---|---|
| X0 | 60 | 180 | 160 |
| X1 | 30 | 120 | 80 |
| S1 | -170 net | 40 | 10 |
| S2 | -120 net | 90 | 20 |
| S4 | 30 | 80 | 20 |
| S5 | 10 | 70 | 20 |
| S6 | 120 | 220 | 30 |
| S7 | 40 | 200 | 120 |
| O1 | 40 | 220 | 30 |
| O2 | 50 | 140 | 20 |
| O3 | 40 | 200 | 30 |

Every slice is under the 800-line budget.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| X0 | engine | contract 3.6, `contracts/stability.py`, engine map tier section, marker docstrings on the SDK and provider-registration names, sentries | R1 | AT-X0a to AT-X0d | - | T1 plus both new sentries; Codex only |
| X1 | CLI | `EXPERIMENTAL_API`, CLI map and `versioning.md` tier list, API docstrings, `library` row with tier `gate` | R1 | AT-X1a to AT-X1c | X0 merged (contract text) | T1; Codex only |
| S1 | engine | delete the two base modules, `FormulaStrategy` plain class | R1 | AT-S1a, AT-S1b | - | T1 plus formula and draw-site tests; mutations on `formula.py` |
| S2 | CLI | remove demo `--ref`, `--rows`, `_generate_ref_datasets`; hidden-name sentry and map row | R1 | AT-S2a, AT-S2b | X1 (map tier column); PROP-batch C-F1b order | T1 |
| S4 | CLI | rename to `report.source_ambiguous`, gate and warning code snapshot | R2 | AT-S4a, AT-S4b | Q5 | T2; Dennis plus Codex |
| S5 | engine | reserved-name additions, grammar subset sentry, exact snapshot | R2 | AT-S5a to AT-S5c | X0 (map row); Q6 | T2; Dennis plus Codex |
| S6 | CLI | `_outbound.open_url`, four call sites, two reasons, AST sentry | R2 | AT-S6a to AT-S6d | Q7 | T2 plus the smoke-install test; Dennis plus Codex |
| S7 | engine, then CLI | renames table, 3.1 tag block, `INTERNAL_TAGS`, two tag censuses | R1 | AT-S7a to AT-S7c | X0 (registry module); Q9 | T1; Codex only |
| O1 | engine | `when:` frame through `to_pandas_fk_safe` for integer columns | R2 | AT-O1a to AT-O1d | - | T2 over every route; mutations on the two frame builders; Dennis plus Codex |
| O2 | CLI | gzip writer with empty name and zero mtime | R2 | AT-O2a to AT-O2c | - | T2; Dennis plus Codex |
| O3 | engine | pass-through type cast point, contract 3.4 sentence, AT-E3-2 update | R2 | AT-O3a to AT-O3d | - | T2 over every route; Dennis plus Codex |

Order: X0, S1, O1 and O3 start at once (engine, no shared files). X1 follows X0. S5 and S7 follow X0 (both edit the map). CLI slices S2, S4, S6 and O2 run in parallel with each other once X1 is in, one writer per file. Engine release after X0, S1, S5, S7, O1 and O3; one CLI repin. Target: all merged before REL-GATE G0 on 2026-12-04.

## 12.1 Done when

Every slice is merged with its acceptance tests green and its mutations red, both map sentries are green on the engine release head and the CLI repin head, and the Breaking fragments for O1, O2, O3, S2, S4, S5 and S6 are in `changelog.d/` or the CLI `CHANGELOG`.

## 13. Recurring-defect class check

- A test weakened to pass: AT-O3d is the only edited existing assertion; the gate checks it changes the type only.
- Two copies of a central mechanism: one tier registry per repo, one outbound URL function, one pass-through type function, one `when:` frame path.
- A frozen surface changed without its records: each output slice carries its contract sentence, map row and Breaking fragment in the same commit.
- Value-free errors: new refusals (`url_scheme_refused`, `notify_url_scheme_refused`) name the purpose and scheme only, never the URL (a webhook URL can hold a token).

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a webhook URL with a token in an error; a `when:` literal in a log) | refusal text names purpose and scheme only; `_eval_predicate` already logs no expression | AT-S6b, AT-S6c assert the URL is absent from message and `--json` | put the URL in the refusal message | S6, O1 |
| 2 | Cleanup on every exit (gzip wrapper left open, staging temp left) | the gzip wrapper opens inside the staging context and closes in its `finally` | AT-O2c | open the wrapper outside the context | O2 |
| 3 | State completeness (each public name has a tier; each tag has a class) | registries plus the exactly-one-row rule | AT-X0a, AT-X1a, AT-S7a | allow a name with no row | X0, X1, S7 |
| 4 | Route coverage (one route keeps `large_string` or float64 frames) | one cast function and one frame path called by every route | AT-O1a, AT-O3a parametrized over 5.3 | skip the cast on `run_mask_chunked` | O1, O3 |
| 5 | Referential integrity (FK keys after the cast or the frame change) | FK keys go through the same DE-10 path; the cast keeps values | AT-O1d, AT-O3b | cast the parent only | O1, O3 |
| 6 | Untrusted input (a URL from config or a flag) | per-purpose scheme allow list before any open; redirects refused | AT-S6a to AT-S6d | allow every scheme for notify | S6 |
| 7 | TOCTOU or check-then-use (scheme checked, a different URL opened) | `open_url` checks and opens the same parsed value in one call; no URL is returned to the caller | AT-S6a (the opener gets the checked object) | check `url`, then open a re-read `url` | S6 |
| 8 | Weak proof (a sentry that passes on an empty set) | each sentry asserts its input set is non-empty and asserts a known member | self-tests in each new sentry | make `walk()` return nothing | X0, S2, S5, S7 |
| 9 | Refactor drift (S1 changes formula output) | S1 removes bases only; class, method, module path and golden output fixed | AT-S1b | rename `apply` | S1 |
| 10 | Frozen contract drift (contract, map and code disagree) | the registry is the source; sentries compare contract 3.6, both maps and docstrings to it | AT-X0c, AT-X0d, AT-S5c, AT-S4b | edit the map only | X0, X1, S4, S5 |

## 14. Pre-mortem

- "The tier is a label nobody reads, and users build on `decoy.mask`." The marker is the first word of every docstring and doc page, and `versioning.md` lists it next to the frozen list. A runtime warning is Q2.
- "`decoy library` stayed at `gate` and 1.0 shipped." AT-X1c fails in ga.
- "A user has a column called `true` or `like`." Q6; the error says how to rename; the reserved list is small and matches SQL and pandas words users already avoid.
- "S6 broke the release smoke." `file` stays allowed for `upgrade`; AT-S6a uses the smoke's exact call.
- "O1 changed which rows were masked for a customer config." Only values at or above 2**53 and chunk-dependent selections change; both were wrong before. The Breaking fragment says so.
- "O3 broke a downstream reader that expected `large_string`." Only `run_mask_chunked` changes, and the other routes already wrote `string`, so a reader that worked on the default route works after.
- "Two plans edited `demo.py` at once." 10.5 orders S2 after PROP-batch C-F1b.

## 15. Owner questions (taken on the recommended answer; owner to confirm)

| Id | Question | Recommended | Source |
|---|---|---|---|
| Q1 | Experimental engine set = connector SDK plus the six provider-registration functions; the provider registry read names stay frozen? | Yes | owner 2026-11-18 tier; split new |
| Q2 | Emit a runtime `ExperimentalWarning` on first use? | No; docstring and doc marker only (warnings in a data tool get filtered and then ignored) | new |
| Q3 | Rule for `decoy library` at G0: experimental if L4b (row 40) merges after 2026-11-27 or no command writes records by G0; frozen otherwise | Yes | owner 2026-11-18 |
| Q4 | Move audit J2 (`api.scan` on `scan_sources`) to v1+ now that `api.scan` is experimental? | Yes | audit J2 |
| Q5 | New namespace for the report code: `report.source_ambiguous`? | Yes; `layout.*` stays for layout codes. `DELIVERY_ROOT_SPLIT` and the cloud target codes stay where they are (in use, and not wrong enough to break) | audit C16 |
| Q6 | Reserve `null`, `true`, `false`, `between`, `like`, `ilike`, `matches`, `startswith`, `endswith` in `when:`? | Yes | contract line on `type` |
| Q7 | Scheme allow list: notify webhook `https` and `http`; slack `https`; `upgrade --url` and the bundle base `https` and `file` | Yes | DUP-DEFECTS B11 |
| Q8 | Accept `decoy demo --ref` moving from exit 1 to exit 2? | Yes; the option was hidden and only ever printed a deferral | new |
| Q9 | Confirm the tag classification in 5.6 (18 frozen, 8 internal), after the S7 builder checks write sites | Yes | new |

## 16. Unresolved

- Q3 is decided at G0, not now; X1 builds the `gate` value and the ga refusal either way.
- If Q6 is answered no, S5 shrinks to the grammar-subset sentry and the snapshot.
- If Q7 refuses `http` for webhooks, AT-S6c gains one cell; nothing else changes.
- O1 assumes numexpr or pandas' python fallback give the same mask on nullable dtypes; AT-O1c is the check. If it fails, O1 converts each referenced integer column to Python ints in an object column before eval, which is slower but exact; the slice stays under budget.
