# Plan: unkeyed date_shift is refused in V1 (roadmap row 24zb, DATE-SHIFT-UNKEYED)

Status: plan

Date: 2026-11-16. Planned from engine `origin/main` at `be2d36e03` (release 0.27.0) and CLI
`origin/main` at `d8805373` (pins `decoy-engine==0.27.0`).

Rules consulted: `README.md` (routing), `00-universal.md`, `development-loop.md`,
`profiles/local-operations.md`, `risk-and-exceptions.md`, `catalogs/recurring-defects.md`
(classes 3, 5, 9, 11), `testing.md`, `security.md`, `cross-cutting-concerns.md`,
`architecture.md` (Layout), `proportionality.md`, `api-and-compatibility.md`,
`documentation.md`; memory notes `v1-bar-blocking-criteria`, `plan-defines-acceptance-tests`,
`develop-correctly-registries-and-sizing`, `best-practice-becomes-a-sentry`.

## 1. Frame

Row 24zb (automated QA scan 2026-11-11, finding F2; owner 2026-11-11 option (a)): an unkeyed
`date_shift` is refused in V1 in the engine and the CLI. A Mac proof on engine 0.22.0 showed the
legacy `MD5(value)` shift in `src/decoy_engine/transforms/date_shift.py` is reversible by search
(one to four candidate dates per row over a 365-day window, the source always among them). The
same proof showed `decoy run`, `decoy run --chunked`, `decoy.mask()` and engine `run_pipeline`
already refuse an unkeyed `date_shift` with `keyed_strategy_requires_secret` before reading a
source. The row asks for three things: pin the refusal on every surface, hard-delete the MD5 path,
and add a sentry so no unkeyed shift can come back.

What the code shows today (read, not run):

- The live handler is `execution/_strategies/_date_shift.py::DateShiftStrategyHandler`. Its offset
  is `min_days + (derive(ctx.mask_key, namespace, canonical(value))[:8] % range_size)`. It never
  calls MD5.
- `transforms/date_shift.py::DateShiftStrategy` (the V1 class with the MD5 fallback, plus
  `_parse_date`, `_shift_for_value_md5`, `_shift_for_value_keyed`) has no caller in `src/`. Only
  two test files use it (`tests/unit/transforms/test_date_shift_key_failure.py`,
  `tests/unit/execution/test_expression_log_redaction.py`). The module's live exports are
  `_detect_format` (imported by the handler, `transforms/bucket_perturb.py` and the chunked
  bucket route) and `_COMMON_FORMATS` (imported by `transforms/text_mask.py`). TQ finding #11
  and proportionality audit item C9 already flag the class as dead.
- One registry decides keyed-ness: `secret_providers/_requirements.py`
  (`ALWAYS_KEYED_STRATEGIES`, `KNOWN_UNKEYED_STRATEGIES`, `column_is_keyed`). `date_shift` is in
  `ALWAYS_KEYED_STRATEGIES`. A strategy in neither set is treated as keyed.
- Two choke points enforce it. `secret_providers/_preflight.py::admit_mask_key` runs from
  configuration alone before any source read (`run_pipeline` through
  `execution/_pipeline_context.py::build_run_context`, the chunked oracle, `unmask`, the vault
  report). `keyprovider.py::require_mask_key` runs at every adapter and route that builds a mask
  key (`_pandas_adapter.py`, `_sequential.py`, `_chunked_oracle.py`, `native/_chunked_entry.py`,
  `out_of_core/_preflight.py`). Both refuse a missing provider, a `SeedKeyProvider` and a key
  shorter than 32 bytes with `runtime.keyed_strategy_requires_secret`, in every release phase.
- `StrategyContext.__post_init__` defaults an empty `mask_key` to `job_seed`. Both constructions in
  `src/` pass `mask_key=require_mask_key(...)`, so the default never reaches a keyed run today;
  nothing stops a third construction from leaving it out.
- One gap in the pre-read walk: `_walk_keyed_columns` skips any table whose raw dict has a truthy
  `generate_columns`, even when the same dict also has mask `columns`. `TableConfig` refuses that
  shape later (the per-table XOR), and `assert_plan_requirements_admitted` plus `require_mask_key`
  catch it after compile, so it is not a leak today. It is a hole in the "refused before any read"
  promise for a malformed dict, and it costs one line to close.

So the leak is closed at run time already. This row turns the closure into pinned, guarded
behavior and removes the dead code that holds the reversible algorithm.

Risk: engine slice E1 is R2 (privacy logic in the keyed-strategy registry and deletion of a
key-handling code path). CLI slice C1 is R1 (tests and fixed help text). Optional E2 is R2 (a new
compile refusal).

## 2. Guarantee and non-goals

Guarantee (V1 rules 1 to 3 only):

1. No route of the engine or the CLI writes `date_shift` output unless a mask secret of at least
   32 bytes was admitted. Without one the job stops with `runtime.keyed_strategy_requires_secret`
   before any source row is read or profiled, and no target or scratch output is written.
2. The engine contains no unkeyed date shift: no MD5 or other key-free digest feeds a date offset.
3. The refusal text is fixed text. It names no cell value and no secret material.

Non-goals:

- Keyed `date_shift` output does not change. No golden, KAT or native parity value moves.
- No refusal at plan compile (section 3) and no new reason code for the unkeyed case.
- Naming the offending columns in the refusal. `keyed_columns_for_config` exists if a later row
  wants it.
- The rest of row 24za (strategy catalog count, `bucketize` pass-through text, `bucket_perturb`
  and `text_mask` `job_seed` wording) unless the owner folds it in (Q2).
- Weak but keyed shifts (small ranges). Only the degenerate one-day range is raised, as Q3.
- Per-strategy pins for `hash`, `fpe` and the other keyed strategies. The sentry in section 6
  covers the class.

## 3. V1 behavior: where the refusal happens

| Surface | Refused? | When | Code | Message |
|---|---|---|---|---|
| Engine `compile_plan` | No | n/a | n/a | Compile is config plus profile. The secret is a run input (`key_provider=` or `mask_secret_ref`), and `--explain-plan`, `decoy explain` and most tests compile without one. A refusal here would break those and add nothing the run gate does not already enforce. |
| Engine `run_pipeline`, every `execution_mode` (`auto`, `stream`, `sequential`, `full_frame`, `out_of_core`) | Yes (exists) | `admit_mask_key` in `build_run_context`, before profiling and before any source read | `runtime.keyed_strategy_requires_secret` | `KEY_REQUIRED_GUIDANCE` (constant) |
| Engine `run_mask_pipeline_chunked`, `run_mask_chunked` | Yes (exists) | `admit_mask_key` in the chunked oracle, before the iterator is touched | same | same |
| Engine adapters and routes called directly (`PandasExecutionAdapter`, sequential, out-of-core preflight, native chunked entry) | Yes (exists) | `require_mask_key` before the first strategy runs | same | same |
| CLI `decoy run`, `decoy run --chunked` | Yes (exists) | engine admission | same, exit 1 | `_mask_secret_guidance.RUN` (fixed text, names `--mask-secret`) |
| CLI `decoy.mask()` | Yes (exists) | engine admission | same, `MaskSecretConfigError` | `_mask_secret_guidance.API` |
| CLI `decoy validate` | No refusal | n/a | n/a | `validate` takes no secret option and the secret may come from `--mask-secret` at run time, so a refusal would fail valid configs and break GATE-08 (run and validate agree on exit). Recommended (Q1): one fixed hint line on human output when the config is keyed and sets no `mask_secret_ref`, reusing `_mask_secret_guidance.INIT_HINT`; no new finding, `--json` unchanged, exits unchanged. |

The reason code is the existing `runtime.keyed_strategy_requires_secret`, the same family row 24d
(QA-SHUFFLE-DET) relied on: 24d made unkeyed `shuffle` draw from the mask key, which put it under
the same refusal. No reason is added, so the frozen reason baseline does not move.

## 4. Every config shape that reaches date_shift

| Shape | Reaches a date offset? | Classified keyed by | Covered by |
|---|---|---|---|
| `strategy: date_shift` on a mask column (defaults, `min_days`/`max_days`, `date_format`) | yes | `ALWAYS_KEYED_STRATEGIES` | AT-E1, AT-E2, AT-E3, AT-E6 |
| `date_shift` with `group_by` (entity anchor) | yes, digest input is the anchor | same | AT-E4 |
| `date_shift` with `preserve_values` | yes, for non-sentinel rows | same | AT-E4 |
| `date_shift` with `deterministic: false` written out | yes | always keyed whatever the flag | AT-E4 |
| `date_shift` under a `when:` gate | yes, for gated rows | same | AT-E4 |
| `strategy: nested` with child `date_shift` | yes | `column_is_keyed` child rule | AT-E4 |
| `text_mask` with a detector dispatched to `date_shift` (`iso_date`, `us_date`, `eu_date` spans) | yes, `_mask_date_shift` with `HMAC(mask_key, span)` | `text_mask` is always keyed | AT-E4 |
| `bucket_perturb` (date moved inside its bucket) | a keyed date offset, not `date_shift` | always keyed | AT-E9 |
| `windowed_date` | an offset from a row-keyed draw off an anchor, not the source value | always keyed on mask tables; generate tables hold no source data | AT-E9 |
| Raw table dict with both `columns` (holding `date_shift`) and `generate_columns` | only past validation | today: skipped by the pre-read walk; after E1: walked | AT-E5 (red today) |
| A misspelled or unknown strategy name (`date-shift`) | no handler; config validation refuses | unknown is keyed by default | existing `test_unrecognised_strategies_default_to_keyed` |
| `formula` / `derived` expressions | no: the grammar has `days_between` only, no date add | unkeyed, correctly | none needed |
| CLI bundled templates (`hipaa.yaml`, `pci.yaml`, `gdpr.yaml`), `decoy init` inference, engine disguises, profiling recommendations | they write `strategy: date_shift` into a config | that config is refused without a secret; the templates already carry the keyed comment block | AT-C1 covers the run |

## 5. Failure modes

| # | Failure | Today | After |
|---|---|---|---|
| F1 | Someone moves `date_shift` to `KNOWN_UNKEYED_STRATEGIES` (or files a new date strategy there) and the run masks off `job_seed` | no `date_shift` test fails; the admission tests use `hash` | AT-E1 to AT-E4, AT-E6 and AT-E9 go red |
| F2 | A new handler reads `ctx.mask_key` but is classified unkeyed | `test_strategy_universe_is_fully_classified` checks completeness, not correctness | AT-E9 (a) goes red |
| F3 | Someone revives the MD5 class or adds another key-free digest for an offset | `# noqa: S324` silences ruff | AT-E8 and AT-E7 |
| F4 | A new mask route builds `StrategyContext` without `require_mask_key`, so `mask_key` silently becomes `job_seed` | nothing guards a third construction | AT-E9 (c) |
| F5 | A malformed raw dict with both table kinds slips past the pre-read walk | caught only after compile | E1 walks `columns` whatever `generate_columns` holds; AT-E5 |
| F6 | The refusal reads a source first (subset stage, profiling) | admission precedes profiling; `resolve_subset` only splits the config before admission | AT-E1 asserts no `profile_source` call; AT-E2 asserts the source is untouched |
| F7 | Deleting the class breaks a live import (`_detect_format`, `_COMMON_FORMATS`) | n/a | the two helpers stay in place; AT-E7 imports them |
| F8 | The draw-site inventory points at the deleted line (`mask.date_shift` `call_site="transforms/date_shift.py:120"`), so `test_c5b_i_metadata_inventory` and `test_draw_site_inventory_coverage` fail | n/a | E1 repoints `call_site`, `seed_derivation` and notes to the live handler |
| F9 | Ratchet baselines name the deleted symbols (`tests/sentry/baselines/secret-material-census.json`, `tests/sentry/secret_material_census.json`, `tests/sentry/baselines/gcs-call-kwargs.json`) and fail on a missing entry | n/a | E1 removes those entries; a shrink only (catalog class 11) |
| F10 | A one-day range (`min_days == max_days`) makes the offset a constant written in the config, so a reader of the config reverses every date, secret or not | accepted silently | Q3: refuse at compile (E2) or record as a known issue |
| F11 | A builder "fixes" a failing golden by regenerating it | n/a | AT-E10: goldens and KATs are read-only in this row |

## 6. Acceptance tests (written first)

Most engine behavior already holds, so most tests below pass on today's code. For those, the
fail-before proof is a named mutation, rerun on the final head and recorded (catalog class 9).

Mutation M1: move `"date_shift"` from `ALWAYS_KEYED_STRATEGIES` to `KNOWN_UNKEYED_STRATEGIES`.
Removing it from `ALWAYS_KEYED_STRATEGIES` alone is not enough, because an unclassified strategy
defaults to keyed; the mutation must file it as unkeyed.

Engine (E1):

| Id | Test (file) | Asserts | Fail-before |
|---|---|---|---|
| AT-E1 | `tests/secret_providers/test_admission_before_read.py`: `run_pipeline` on a `date_shift` config with no secret, pre-GA and GA, parametrized over every `execution_mode` value | raises `KeyedStrategyRequiresSecret` with `code == "keyed_strategy_requires_secret"`; `profile_spy == []`; target path absent | passes today; red under M1 |
| AT-E2 | same file: `run_mask_pipeline_chunked` and `run_mask_chunked` with the `date_shift` config and a `TouchedSource` | same code; `source.touched == 0`; `SeedKeyProvider.mask_key` patched to raise, so no seed fallback ran | passes today; red under M1 |
| AT-E3 | same file: `run_pipeline(..., key_provider=SeedKeyProvider(...))`, and a duck-typed provider returning 8 bytes | both refused with the same code, before profiling | passes today; the short-key case is red if the `MIN_SECRET_BYTES` check in `_load_legacy` is removed |
| AT-E4 | `tests/secret_providers/test_classifier_equivalence.py`: parametrized raw configs for each keyed row of section 4 (`group_by`, `preserve_values`, `deterministic: false`, `when:`, `nested` child, `text_mask` with a `date_shift` detector) | `secret_requirements_for_config(cfg) == (MASK_ROOT,)` and `admit_mask_key(cfg)` raises the code | passes today; the plain, `group_by`, `preserve_values`, `deterministic: false`, `when:` and `nested` rows are red under M1 |
| AT-E5 | same file: a raw table dict with `columns: [date_shift]` and a non-empty `generate_columns` | `secret_requirements_for_config` returns `(MASK_ROOT,)` | red today (returns `()`); green after E1 |
| AT-E6 | `tests/secret_providers/test_admission_before_read.py`: `PandasExecutionAdapter` and the sequential route on a compiled `date_shift` plan with `key_provider=None` | refused by `require_mask_key` with the code before the handler runs | passes today; red under M1 |
| AT-E7 | `tests/unit/transforms/test_date_shift_key_failure.py` (shrunk in place) | `DateShiftStrategy`, `_shift_for_value_md5`, `_shift_for_value_keyed` and `_parse_date` are absent from `decoy_engine.transforms.date_shift`; `_detect_format` and `_COMMON_FORMATS` import and keep their existing oracles | red today (the names exist) |
| AT-E8 | `tests/sentry/test_source_hygiene.py`: new check | no `hashlib.md5(`, no `from hashlib import md5`, no `hashlib.new("md5"` and no `noqa: S324` under `src/decoy_engine/`; a seeded case per spelling must fail the check | red today (one site) |
| AT-E9 | `tests/secret_providers/test_classifier_equivalence.py`: the keyed-strategy sentry, three parts. (a) For each `SCALAR_HANDLERS` entry, parse the handler class's module (`inspect.getsourcefile`, then `ast`); if it reads `mask_key` (attribute `.mask_key`, a `mask_key=` keyword, or a `mask_key` name passed to `derive` or `DeriveContext`), the strategy must be in `ALWAYS_KEYED_STRATEGIES` or in a shrink-only `CONDITIONALLY_KEYED` allowlist (`faker`, `categorical`, each with its reason: keyed only when `deterministic` or `vault`), and each allowlisted strategy must be keyed by `column_is_keyed` when `deterministic=True`. (b) For every member of `ALWAYS_KEYED_STRATEGIES` that is a handler name, a minimal raw config `{"tables": [{"name": "t", "columns": [{"name": "c", "strategy": s}]}]}` makes `admit_mask_key` raise the code; the list comes from the frozenset, never a hand list. (c) An `ast` walk of `src/decoy_engine/` finds every `StrategyContext(` call and requires a `mask_key=` keyword whose value calls `require_mask_key`. | (a) red under M1 and under "add a handler that reads `ctx.mask_key` to `KNOWN_UNKEYED_STRATEGIES`"; (c) red under "drop `mask_key=` from the construction in `_sequential.py`"; (b) red if the walk drops a member |
| AT-E10 | existing `tests/native/test_determinism_goldens.py`, `tests/native/test_draw_site_providers_golden.py`, `tests/physical/test_shadow_date_shift.py` KATs | unchanged and green; no golden or KAT file is edited in this row | regression guard, not a new test |
| AT-E11 | existing `test_unkeyed_work_needs_no_secret` | an all-unkeyed config still runs with no secret (engine QA KEY-09) | regression guard |
| AT-E12 | AT-E1 extended | the message contains the constant guidance; a marker placed in the source cells appears in no message, log record, `__cause__` or `__context__` (catalog class 3) | passes today; pin |

Scanner scope for AT-E8 and AT-E9 (catalog class 5): the spellings listed above only. Deliberate
evasion (`getattr(ctx, "mask" + "_key")`, `importlib`) is V2-LOG. AT-E9 derives its handler list
from `SCALAR_HANDLERS` and its keyed list from the frozenset, so neither is a hand-kept table.

CLI (C1):

| Id | Test (file) | Asserts | Fail-before |
|---|---|---|---|
| AT-C1 | `tests/e2e/test_run_mask_secret.py`: `decoy run` on a `date_shift` pipeline with no secret (checklist RUN-14, KEY-05) | exit 1; stderr carries `_mask_secret_guidance.RUN`; no run folder, target or scratch; a marker date from the source appears in no output and no `--json` | passes on 0.27.0 (pin); the compensating proof is the engine M1 mutation |
| AT-C2 | same file: `decoy run --chunked` | same | same |
| AT-C3 | same file: `decoy.mask()` | `MaskSecretConfigError` with the `API` text; no output | same |
| AT-C4 | same file: `nested` with child `date_shift`, and a `text_mask` column with a `date_shift` detector, through `decoy run` | same refusal | same |
| AT-C5 | same file: the RUN-14 pipeline with `--mask-secret env:...` | exit 0; each non-null output date differs from its source by an offset in `[min_days, max_days]` | positive control |
| AT-C6 | `tests/e2e/test_explain_command.py` | the `date_shift` one-liner says the offset is keyed and needs a mask secret | red today ("Move dates by a random number of days") |
| AT-C7 (only if Q1 = hint) | validate test in `tests/e2e/` | keyed config with no `mask_secret_ref`: human output has the hint, exit 0; `--json` byte-equal to before; `--fail-on-warning` still exit 0 | red today (no hint) |

E2 (only if Q3 = yes):

| Id | Test | Asserts | Fail-before |
|---|---|---|---|
| AT-E13 | beside the existing `date_shift` compile tests | `min_days == max_days` (also after the swap) refused at compile with `plan.date_shift_range_degenerate`, value-free message naming table and column; `min_days: 0, max_days: 1` compiles | red today |
| AT-E14 | `decoy validate` on the same config (folded into C1 when E2 is released first) | exit 1 with the code | red today |

## 6a. Class table

Classes from the plan contract (`docs/handoffs/DEFECT-CATALOG.md`, section 3).

| # | Class | Closing structure | Proving test | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Value-bearing output | The refusal raises `KeyedStrategyRequiresSecret` with the fixed `KEY_REQUIRED_GUIDANCE` text (`keyprovider.py:224`); E2's message names table and column only | AT-E12 seeded marker in source cells, checked in the message, log records, `__cause__` and `__context__`; AT-C1 checks stdout, stderr and `--json` | Format the first source cell into the refusal message: AT-E12 fails |
| 2 | Cleanup missing on an exit path | The refusal fires in `admit_mask_key` before any target or scratch is opened, so no exit path owns a file yet | AT-E1 target path absent; AT-C1 no run folder, target or scratch | Move `admit_mask_key` after the target writer opens in `build_run_context`: AT-E1 and AT-C1 fail |
| 3 | State machine and concurrency | N/A: the refusal is a pure check on config and provider at entry; no state, lock or cache is added | | |
| 4 | Route parity and silent fallback | One registry (`ALWAYS_KEYED_STRATEGIES`) and two choke points (`admit_mask_key`, `require_mask_key`) serve every route; `StrategyContext` is built only with `mask_key=require_mask_key(...)` | AT-E1 over every `execution_mode`, AT-E2 both chunked entries, AT-E6 adapters, AT-E9 (c) AST walk of every `StrategyContext(` | M1, and "drop `mask_key=` from `_sequential.py:350`": AT-E9 (c) fails |
| 5 | Referential integrity | N/A: no FK handling changes; `group_by` anchors keep their keyed derivation and only gain a pinned refusal | | |
| 6 | Untrusted producer | `require_mask_key` refuses a `SeedKeyProvider` and any provider returning under 32 bytes (exact check on the returned key) | AT-E3 seed provider and an 8-byte duck-typed provider | Remove the `MIN_SECRET_BYTES` check in `_load_legacy`: AT-E3 short-key cell fails |
| 7 | TOCTOU on a path | N/A: no path is checked or used by this change | | |
| 8 | Weak tests and overclaimed evidence | Each test is labelled FAIL-BEFORE (red on main) or PIN (green on main, red under a named mutation); mutations rerun on the final head (catalog class 9) | AT-E5, AT-E7, AT-E8, AT-C6 recorded red on main; AT-E1 to AT-E4, AT-E6 recorded red under M1 | Revert the `_walk_keyed_columns` fix: AT-E5 fails, proving the label is honest |
| 9 | Behavior-preserving refactor drift | Deleting the dead class keeps `_detect_format` and `_COMMON_FORMATS` in place; keyed output is byte-identical | AT-E10 goldens and KATs unchanged; AT-E7 imports both helpers with their oracles | Change `_COMMON_FORMATS` order: AT-E7 or the bucket_perturb oracle fails |
| 10 | Frozen contract drift | No reason code added in E1; `DateShiftStrategy` was never in a public `__all__`; E2 adds one reason with `since=` (additive) | Existing frozen reason baseline sentry; `test_public_import_boundary.py` | Add a reason in E1 without `since=`: the reason baseline sentry fails |

## 6b. Enumerations from the code

Read at `be2d36e03`.

### Exit paths

- Refusal in `admit_mask_key` (`secret_providers/_preflight.py:389`), reached from `build_run_context` (`execution/_pipeline_context.py:314`) and the chunked oracle (`execution/_chunked_oracle.py:122`): raises before profiling and before any source or target is opened.
- Refusal in `require_mask_key` (`keyprovider.py:232`) at an adapter or route: raises before the first strategy runs, after compile; no target is open at that point on any route.
- Success: the run continues with the admitted key; unchanged by this row.

### Routes

- `run_pipeline` (`execution/_pipeline.py:115`) for `auto`, `stream`, `sequential`, `full_frame`, `out_of_core`.
- `run_mask_pipeline_chunked` (`execution/_chunked.py:382`) and `run_mask_chunked` (`execution/_pipeline_route_exec.py:565`, `execution/native/_chunked_entry.py:589`).
- Adapter sites calling `require_mask_key`: `execution/_pandas_adapter.py:245`, `execution/_sequential.py:350`, `execution/_chunked_oracle.py:265`, `execution/native/_chunked_entry.py:262`, `execution/out_of_core/_preflight.py:65`.
- Other `admit_mask_key` callers that do not run `date_shift` but share the walk: `unmask.py:264`, `vault.py:466`.

### FK shapes

- N/A: this row changes no FK handling. The one FK-adjacent shape is `date_shift` with `group_by`, covered in section 4 and AT-E4.

### Fields

- `StrategyContext.mask_key` (defaulted to `job_seed` in `__post_init__` when empty); both constructions at `execution/_pandas_adapter.py:239` and `execution/_sequential.py:344` pass `require_mask_key`.
- `date_shift` column fields: `min_days`, `max_days`, `date_format`, `group_by`, `preserve_values`, `deterministic`, `when` (section 4).
- Registry fields: `ALWAYS_KEYED_STRATEGIES` (`secret_providers/_requirements.py:173`), `KNOWN_UNKEYED_STRATEGIES` (`secret_providers/_requirements.py:191`), `column_is_keyed` (`secret_providers/_requirements.py:210`), `_walk_keyed_columns` (`secret_providers/_requirements.py:243`, skip at line 247).

### Output surfaces

- Engine: the raised exception (`code`, message, `__cause__`, `__context__`) and log records; no file is written.
- CLI: stderr text, exit code, `--json` output of `decoy run`; the `MaskSecretConfigError` from `decoy.mask()`; `decoy explain` text; `decoy validate` human output (Q1).

## 6c. Reuse inventory

- `ALWAYS_KEYED_STRATEGIES`, `column_is_keyed`, `secret_requirements_for_config` (the keyed-ness registry): extended by a walk fix, not copied.
- `admit_mask_key`, `require_mask_key`, `KEY_REQUIRED_GUIDANCE`: reused as is; no new refusal path.
- `tests/secret_providers/_helpers.py::keyed_config`, `TouchedSource`, `profile_spy` fixtures in `test_admission_before_read.py`: reused by AT-E1 to AT-E3.
- `test_strategy_universe_is_fully_classified`: AT-E9 sits beside it and derives from the same `SCALAR_HANDLERS`.
- `tests/sentry/test_source_hygiene.py`: AT-E8 joins it instead of a new sentry module.
- CLI `_mask_secret_guidance.py` texts (`RUN`, `API`, `INIT_HINT`): reused, never copied.
- Reason registry (`reasons/plan/_part*.py`): E2's one reason only.

## 6d. Frozen contracts

- Reason codes: `runtime.keyed_strategy_requires_secret` reused, unchanged. E2 adds `plan.date_shift_range_degenerate` (additive, `since=` set).
- Public engine surface (`docs/compatibility-contract.md` section 4.1): untouched; the deleted class is not exported from `decoy_engine` or `decoy_engine.transforms`.
- Keyed `date_shift` output and KATs: unchanged (AT-E10).
- CLI exit codes and `--json` schema: unchanged (AT-C7 checks `--json` byte-equal).

## 6e. Pre-mortem

- A gate reviewer finds a route that builds `StrategyContext` without `require_mask_key`: AT-E9 (c) walks every construction, so the build fails first.
- The class deletion breaks a hidden importer: `grep` at planning found only `_detect_format` and `_COMMON_FORMATS` importers; the builder reruns it on the branch head and AT-E7 imports both.
- A sentry baseline or the draw-site inventory still names a deleted symbol: F8 and F9 list every known file; the T1 selection includes `tests/sentry/` and `tests/native/`.
- AT-E9 (a) flags `faker` or `categorical`: they are on the shrink-only allowlist with a reason, and part (a) checks they are keyed when `deterministic=True`.
- E2 rejects a real customer config: a one-day range is a constant shift a config reader can reverse; Q3 asks the owner before E2 is built.

## 7. Migration impact

- Configs: no behavior change. Every config with `date_shift` and no secret has been refused
  since the F13 admission work (before 0.22.0, per the Mac proof). Keyed output is unchanged.
- Python API: `decoy_engine.transforms.date_shift.DateShiftStrategy` and three private helpers
  are removed. They are not exported from `decoy_engine` or `decoy_engine.transforms` (its
  `__all__` holds `BaseMaskingStrategy` only), so the additive-only public surface in
  `docs/compatibility-contract.md` section 4.1 is not touched. The CHANGELOG gets a "Removed" line.
- CLI: no code imports the class. C1's tests pass on 0.27.0, so C1 needs no pin change.
- Examples: no engine example or doc YAML block uses `date_shift`. The `mask.date_shift` entry in
  `docs/proof-manifest.json` is generated with a throwaway 32-byte secret
  (`scripts/gen_proof_manifest.py` `_PROOF_SECRET`) and does not change. CLI templates already
  carry the keyed comment block (`_mask_secret_guidance.YAML_COMMENT`); the shape-and-privacy
  guide 02 already says keyed.
- If Q3 = yes, a config with a one-day range starts failing compile. That is intended; the
  CHANGELOG and `docs/strategies.md` say so.

## 8. Docs and checklists (in E1 unless noted)

- `docs/strategies.md` `date_shift` section: the offset is `derive(mask_key, namespace, value)`, a
  mask secret is required, and the refusal code. If Q2 = yes, replace "Null and unparseable values
  are left as-is" with the `format_error` behavior.
- `docs/determinism.md`: if Q2 = yes, replace the "falls back to `job_seed`" paragraph with the
  no-fallback rule, matching `docs/security/key-derivation.md`.
- `docs/native/draw-site-inventory.md` `mask.date_shift`: point at the live handler; drop the
  MD5 sentence.
- `docs/methodology-registry.yaml`: move the `transforms/date_shift.py` HMAC entry to
  `execution/_strategies/_date_shift.py` (HKDF then HMAC through `determinism.derive`);
  `test_methodology_citations` stays green.
- `docs/quality/tq-findings.md` #11 and `docs/quality/mutation-ledgers/transforms_date_shift.md`:
  mark the dead class removed; the ledger scope is `_detect_format` only.
- `docs/security/key-derivation.md`: remove the line about `transforms/date_shift.py` calling
  `derive_key("mask")`.
- Engine QA `docs/qa/07-mask-dates-and-numbers.md`: say every check runs with a mask secret; add
  DATE-13 "`date_shift` with no secret: refused with `runtime.keyed_strategy_requires_secret`
  before any source read, on `run_pipeline` and both chunked entries"; close the first open point
  if Q2 = yes. `docs/qa/05-keys-determinism-namespaces.md`: KEY-05 also names `date_shift`; close
  the `job_seed` open point if Q2 = yes. `test_qa_checklist_reasons` stays green.
- Engine CHANGELOG: Removed (legacy class), Changed (pre-read walk), Added (sentries).
- C1 (CLI repo): `docs/qa/cli-v1-checklist.md` RUN-14 and KEY-05 keep their wording and gain the
  test ids; `docs/ROADMAP.md` row 24zb moves to DONE with PR numbers, plus the shipped-log entry.
  Proportionality item C9 and duplication-census E24 (`transforms/date_shift.py:123`) are records;
  C1 does not edit them, and the roadmap row notes E1 closed them.

## 9. Placement

No new files in either repo. Every change lands in an existing module. Design notes: none, no new
structure.

| Change | File | Map line that places it | Beside |
|---|---|---|---|
| Delete the V1 class and three helpers; keep `_detect_format`, `_COMMON_FORMATS`, rewrite the docstring (about 100 of 285 lines left) | `src/decoy_engine/transforms/date_shift.py` | `transforms/` leaf package of reused helpers (`transforms/__init__.py` docstring) | `bucket_perturb.py`, `text_mask.py` (its importers) |
| Walk `columns` whatever `generate_columns` holds | `src/decoy_engine/secret_providers/_requirements.py` | the keyed-ness registry ("one authority", module docstring) | `_preflight.py` |
| Repoint `mask.date_shift` `call_site`, `seed_derivation`, notes | `src/decoy_engine/execution/native/_draw_sites_mask.py` | draw-site inventory | `_draw_site_providers.py` |
| Docstring: `derive(mask_key, ...)`, not `job_seed` | `src/decoy_engine/execution/_strategies/_date_shift.py` | strategy handlers | n/a |
| Comment and docstring references to the deleted class | `profiling/recommendations.py`, `transforms/fpe.py`, `transforms/__init__.py`, `reference_tables/_types.py` | unchanged homes | n/a |
| AT-E4, AT-E5, AT-E9 | `tests/secret_providers/test_classifier_equivalence.py` (126 lines now) | `tests/` layout; it extends the completeness check already there | `test_keyed_columns.py` |
| AT-E1 to AT-E3, AT-E6, AT-E12 | `tests/secret_providers/test_admission_before_read.py` (174 lines) | same | `_helpers.py` gains a `keyed_config(strategy=...)` parameter |
| AT-E8 | `tests/sentry/test_source_hygiene.py` (229 lines) | `tests/sentry/` is flat and over the fan-out limit (75 modules), so the check joins an existing file | n/a |
| AT-E7 | `tests/unit/transforms/test_date_shift_key_failure.py` (shrinks from 243) | existing | n/a |
| Dead-class tests removed | `tests/unit/execution/test_expression_log_redaction.py` (two tests that call `DateShiftStrategy`; the live handler's value-free row errors are covered in `tests/unit/execution/test_row_error_producers.py`) | existing | n/a |
| E2 check (if Q3) | `src/decoy_engine/plan/_checks_date_shift.py` and one entry in a `reasons/plan/_part*.py` with `since=` | plan checks; reason registry | `check_date_shift_group_by_refs` |
| C1 | `src/decoy/cli/explain.py`; `src/decoy/cli/validate.py` (Q1); tests in `tests/e2e/` | CLI command modules | `_mask_secret_guidance.py` (text reused, not copied) |

Choke points: keyed-ness lives in `_requirements.py` only; the refusal lives in `admit_mask_key`
and `require_mask_key` only; CLI wording lives in `_mask_secret_guidance.py` only. This row adds no
second copy of any of them. The guard for the keyed-ness rule is AT-E9; its red mutations are M1
for part (a) and "drop `mask_key=` from `_sequential.py`'s `StrategyContext`" for part (c).

Test deletions are explicit and limited to tests whose only subject is the deleted class (AT-E7's
file and the two tests in `test_expression_log_redaction.py`). No other test is weakened, skipped
or deleted.

## 10. Established solutions

Search run: a web search for date-shifting de-identification with a secret per-individual offset
(NIST SP 800-188; Google Cloud Sensitive Data Protection), and the in-repo design notes
(`docs/discussions/2026-07-14-de02-keyprovider-design.md`, `docs/security/key-derivation.md`).

Found: Google's date-shift transform shifts each entity's dates by an amount derived from a
`crypto_key`, and its docs say the key is what keeps shifts consistent across runs. That is the
pattern the live handler already follows: a keyed PRF over the value or the entity anchor
(HKDF-SHA256, RFC 5869, then HMAC-SHA256, RFC 2104, both through PyCA and the stdlib). SP 800-188
covers de-identification governance in general; the search did not surface a date-shift passage
in it, so it is cited for context only. No custom code is added: the change deletes the
hand-rolled unkeyed path and adds guards around the existing keyed one.

Sources: https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-date-shifting and
https://csrc.nist.gov/pubs/sp/800/188/final

## 11. Slices

| Slice | Repo | Scope | Production files | Lines (est.) | Risk | Review |
|---|---|---|---|---|---|---|
| E1 | engine | Delete the MD5 class; walk fix; draw-site repoint; docstrings; AT-E1 to AT-E12; baseline shrinks; docs and QA sections 05 and 07; CHANGELOG | 8 `src/` files (section 9) | about 650 to 750 changed, about two thirds deletions | R2 | Dennis then Codex; M1, the AT-E9 (c) mutation and the `_load_legacy` short-key mutation rerun on the final head and recorded |
| E2 (only if Q3 = yes) | engine | One-day range refused at compile, reason `plan.date_shift_range_degenerate`, AT-E13, docs line | 2 | about 80 | R2 | Dennis then Codex |
| release | engine | Rides the daily engine release train (owner D4). No separate release work. | n/a | n/a | n/a | n/a |
| C1 | CLI | AT-C1 to AT-C6 (AT-C7 if Q1, AT-E14 if E2 is released), explain text, validate hint (Q1), checklist ids, roadmap row and shipped log | 1 or 2 | about 150 to 200 | R1 | Codex |

Test depth: T0 per edit; T1 impact selection per commit (secret_providers, transforms, native
inventory, sentry, physical shadow date_shift, the golden suites). The gate runs T1 plus all of
`tests/secret_providers/` and `tests/sentry/` on the exact head. E1 changes the secret-admission
walk, which sits on the same trust boundary as authorization checks, so treat it as an escalation
trigger: one full suite on the merge head (or its merge-train batch head), diffed against the
stored main baseline. C1 needs no full suite.

Build timing: the row says build at the section-07 group's QA pass (owner rule 2026-11-11). See Q4.

## 12. Owner questions (with recommended answers)

1. **`decoy validate` on a keyed config with no `mask_secret_ref`.** Options: (a) nothing;
   (b) a fixed hint line on human output only, with exits and `--json` unchanged; (c) a new
   warning finding. Recommended: (b). It tells the user before a long job, without breaking
   GATE-08 or making every keyed config fail `--fail-on-warning`.
2. **Fold the `date_shift` parts of row 24za into E1**: the "unparseable values left as-is"
   sentence in the same `docs/strategies.md` section, and the `job_seed` fallback paragraph in
   `docs/determinism.md` that contradicts this row? Recommended: yes. 24za keeps the strategy
   catalog count and the `bucketize`, `bucket_perturb` and `text_mask` wording.
3. **Degenerate range.** With `min_days == max_days` the offset is written in the config, so
   anyone who reads the config can reverse the output, keyed or not. Refuse it at compile in V1
   (slice E2, new plan reason), or record it as a known issue for V2? Recommended: refuse in V1.
   It is the same leak class as this row, the fix is one check, and no masking config needs a
   constant shift.
4. **Build timing.** E1 changes no behavior a QA pass would observe. Build now, or wait for the
   section-07 QA pass as the row says? Recommended: build now, so the dead algorithm is gone and
   the guard is in place before other date work lands; QA then runs DATE-13 against the guarded
   code. C1 may land before the engine release that carries E1, since its tests pass on 0.27.0.
5. **Delete or keep the legacy helpers.** Hard-delete the class and its three helpers, and keep
   `_detect_format` and `_COMMON_FORMATS` where they are (moving them is churn across four
   importers)? Recommended: yes, as written.

## 13. Not verified

- No test was run (devbox rule). Each "passes today" claim comes from reading the code and the
  existing tests, plus the 2026-11-11 Mac proof on 0.22.0. The builder confirms each fail-before
  claim on the branch before changing source.
- Whether `run_pipeline` hands `admit_mask_key` the raw dict or a validated dump, and so whether a
  both-kinds table can reach the walk through `run_pipeline` at all. AT-E5 tests the classifier
  directly either way.
- The exact line numbers for the repointed draw-site `call_site`; the builder takes them from the
  branch head.
- That `inspect.getsourcefile` resolves each `SCALAR_HANDLERS` class to its own module (true for
  the 25 handlers read; `_composite.py` is not in `SCALAR_HANDLERS`).
- That no native `_ext` module adds a keyed draw for a strategy classified unkeyed. AT-E9 (a)
  reads handler modules only; the native modules are reached from those handlers and from
  `require_mask_key` callers.
