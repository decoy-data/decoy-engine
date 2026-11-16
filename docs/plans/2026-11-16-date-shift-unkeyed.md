# Plan: unkeyed date_shift is refused in V1 (roadmap row 24zb, DATE-SHIFT-UNKEYED)

Status: plan

Date: 2026-11-16. Planned from engine `origin/main` at `13c95c7de` (release 0.27.0) and CLI
`origin/main` at `60cac6783` (pins `decoy-engine==0.27.0`).

Supersedes: `docs/plans/2026-11-11-date-shift-unkeyed.md` and its section-07 build timing.

Rules consulted: `README.md` (routing), `00-universal.md`, `development-loop.md`,
`profiles/local-operations.md`, `risk-and-exceptions.md`, `catalogs/recurring-defects.md`
(classes 1 to 11 checked; 3, 5, 9 and 11 apply directly), `testing.md`, `security.md`,
`workspace-and-vcs.md`, `reuse-first.md`, `exploration.md`, `scope-discipline.md`, `verification.md`,
`code-review.md`, `config-secrets-and-supply-chain.md`,
`cross-cutting-concerns.md`,
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
  `_detect_format` (imported by the handler and `transforms/bucket_perturb.py`) and
  `_COMMON_FORMATS` (imported by `transforms/text_mask.py`). TQ finding #11
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
- One gap in the public raw-config classifier: `_walk_keyed_columns` skips any table whose dict has
  a truthy `generate_columns`, even when the same dict also has mask `columns`. The shape is
  unreachable from `run_pipeline` under its validated-dump contract: callers must pass
  `PipelineConfig.model_validate(...).model_dump()`, and `TableConfig` refuses both kinds. E1 still
  hardens the public `keyed_columns_for_config` and `secret_requirements_for_config` walk so direct
  callers of those public classifiers cannot suppress a keyed mask column with invalid structure.

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
2. The engine contains no MD5-based date shift. AT-E8 guards the MD5 spellings; Guarantee 1 and
   AT-E9's keyed-classification sentry cover handlers that use any other digest or key derivation.
3. The refusal text is fixed text. It names no cell value and no secret material.

Non-goals:

- Keyed `date_shift` output does not change. No golden, KAT or native parity value moves.
- No refusal at plan compile and no new reason code for the unkeyed case. E2 separately refuses a
  degenerate range at compile under the owner decision in section 12.
- Naming the offending columns in the refusal. `keyed_columns_for_config` exists if a later row
  wants it.
- The rest of row 24za: strategy catalog count, `bucketize` pass-through text, and unrelated
  `bucket_perturb` wording. E1 does fold in the two stale `date_shift` sentences and the stale
  `docs/determinism.md` paragraph selected in decision Q2.
- Weak but keyed shifts with non-degenerate ranges. E2 refuses only `min_days == max_days`.
- Per-strategy pins for `hash`, `fpe` and the other keyed strategies. The sentry in section 6
  covers the class.
- Platform job routes and preview. The platform is parked; when it resumes, those surfaces enter
  through the same engine admission and route gates pinned here.
- `src/decoy_engine/internal/crypto.py::deterministic_hash`, a dead deprecated unkeyed helper,
  remains the separate V2 cleanup recorded in section 8.

## 3. V1 behavior: where the refusal happens

| Surface | Refused? | When | Code | Message |
|---|---|---|---|---|
| Engine `compile_plan` | No | n/a | n/a | Compile is config plus profile. The secret is a run input (`key_provider=` or `mask_secret_ref`), and `--explain-plan`, `decoy explain` and most tests compile without one. A refusal here would break those and add nothing the run gate does not already enforce. |
| Engine `run_pipeline`, every `execution_mode` (`auto`, `stream`, `sequential`, `full_frame`, `out_of_core`) | Yes (exists) | `admit_mask_key` in `build_run_context`, before profiling and before any source read | `runtime.keyed_strategy_requires_secret` | `KEY_REQUIRED_GUIDANCE` (constant) |
| Engine `run_mask_pipeline_chunked`, `run_mask_chunked` | Yes (exists) | `admit_mask_key` in the chunked oracle, before the iterator is touched | same | same |
| Engine adapters and routes called directly (`PandasExecutionAdapter`, sequential, out-of-core preflight, native chunked entry) | Yes (exists) | `require_mask_key` before the first strategy runs | same | same |
| CLI `decoy run`, `decoy run --chunked` | Yes (exists) | engine admission | same, exit 1 | `_mask_secret_guidance.RUN` (fixed text, names `--mask-secret`) |
| CLI `decoy.mask()` | Yes (exists) | engine admission | same, `MaskSecretConfigError` | `_mask_secret_guidance.API` |
| CLI `decoy validate` | No refusal | n/a | n/a | `validate` takes no secret option and the secret may come from `--mask-secret` at run time, so a refusal would fail valid configs and break GATE-08 (run and validate agree on exit). Per Q1, print one fixed `_mask_secret_guidance.INIT_HINT` line on human output only, using the existing keyed check once; no new finding, `--json` unchanged, exits unchanged. |

The unkeyed refusal reuses `runtime.keyed_strategy_requires_secret`, the same family row 24d
(QA-SHUFFLE-DET) relied on: 24d made unkeyed `shuffle` draw from the mask key, which put it under
the same refusal. E1 adds no reason. E2 separately adds `plan.date_shift_range_degenerate` and its
required frozen-fixture row.

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
| Raw table dict with both `columns` (holding `date_shift`) and `generate_columns` | unreachable through `run_pipeline` under the validated-dump contract; reachable only through the public raw-config classifiers | today: skipped by the classifier walk; after E1: walked | AT-E5 (red today) |
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
| F5 | A direct caller passes a malformed raw dict with both table kinds to the public classifiers | mask `columns` are skipped | E1 walks `columns` whatever `generate_columns` holds; AT-E5. Validated `run_pipeline` input cannot have this shape |
| F6 | The refusal reads a source first (subset stage, profiling) | admission precedes profiling; `resolve_subset` only splits the config before admission | AT-E1 asserts no `profile_source` call; AT-E2 asserts the source is untouched |
| F7 | Deleting the class breaks a live import (`_detect_format`, `_COMMON_FORMATS`) | n/a | the two helpers stay in place; AT-E7 imports them |
| F8 | The draw-site inventory points at the deleted line (`mask.date_shift` `call_site="transforms/date_shift.py:120"`), so the frozen catalogue pin moves | n/a | E1 repoints `call_site`, `seed_derivation` and notes to the live handler and updates only the `mask.date_shift` element of `_ENTRY_DIGESTS` plus `_CATALOGUE_DIGEST` in `tests/native/test_draw_sites_catalogue_pinned.py`. This is a metadata-only class-10 re-pin. `_MAP_DIGESTS` and `tests/native/test_draw_site_providers_golden.py` remain byte-identical |
| F9 | Ratchet baselines name the deleted symbols (`tests/sentry/baselines/secret-material-census.json`, `tests/sentry/secret_material_census.json`, `tests/sentry/baselines/gcs-call-kwargs.json`) and fail on a missing entry | n/a | E1 removes those entries; a shrink only (catalog class 11) |
| F10 | A one-day range (`min_days == max_days`) makes the offset a constant written in the config, so a reader of the config reverses every date, secret or not | accepted silently | Q3 decided: E2 refuses it at compile |
| F11 | A builder treats the metadata re-pin as permission to regenerate behavior goldens | n/a | AT-E10 permits only the two catalogue digest edits named in F8. Coverage-map digests, provider goldens and KAT files remain byte-identical |

## 6. Acceptance tests (written first)

Most engine behavior already holds, so most tests below pass on today's code. For those, the
fail-before proof is a named mutation, rerun on the final head and recorded (catalog class 9).

Named mutations, each rerun against the final head (catalog class 9):

- M1: move `"date_shift"` from `ALWAYS_KEYED_STRATEGIES` to
  `KNOWN_UNKEYED_STRATEGIES`. Removing it only from the first set is not enough because the
  conservative default is keyed.
- M2: delete the `isinstance(key_provider, SeedKeyProvider)` check in
  `secret_providers/_preflight.py::_load_legacy` (line 275 at `13c95c7de`).
- M3: delete the `isinstance(key_provider, SeedKeyProvider)` check in
  `keyprovider.py::require_mask_key` (line 244 at `13c95c7de`).
- M4: in CLI `cli/run/_prepare.py`, derive 32 bytes only from the visible config seed, wrap them
  in `SecretKeyProvider`, and pass that admitted provider when no secret is set. This bypasses
  both engine gates and must turn the C1 refusal parametrization red.
- M5: drop `mask_key=` from the `_sequential.py` `StrategyContext` construction.

Engine (E1):

| Id | Test (file) | Asserts | Fail-before |
|---|---|---|---|
| AT-E1 | `tests/secret_providers/test_admission_before_read.py`: `run_pipeline` on a `date_shift` config with no secret, pre-GA and GA, parametrized over every `execution_mode` value | raises `KeyedStrategyRequiresSecret` with `code == "keyed_strategy_requires_secret"`; `profile_spy == []`; target path absent | passes today; red under M1 |
| AT-E2 | same file: `run_mask_pipeline_chunked` and `run_mask_chunked` with the `date_shift` config and a `TouchedSource` | same code; `source.touched == 0`; `SeedKeyProvider.mask_key` patched to raise, so no seed fallback ran | passes today; red under M1 |
| AT-E3 | same file: `run_pipeline(..., key_provider=SeedKeyProvider(...))` with both 8-byte and 32-byte seeds, plus a duck-typed provider returning 8 bytes | every case is refused with the same code before profiling; provider type is rejected independently of length | passes today; the 32-byte seed case is red under M2 and the short duck-typed case is red if the `MIN_SECRET_BYTES` check is removed |
| AT-E4 | `tests/secret_providers/test_classifier_equivalence.py`: parametrized raw configs for each keyed row of section 4 (`group_by`, `preserve_values`, `deterministic: false`, `when:`, `nested` child, `text_mask` with a `date_shift` detector) | `secret_requirements_for_config(cfg) == (MASK_ROOT,)` and `admit_mask_key(cfg)` raises the code | passes today; the plain, `group_by`, `preserve_values`, `deterministic: false`, `when:` and `nested` rows are red under M1 |
| AT-E5 | same file: a raw table dict with `columns: [date_shift]` and a non-empty `generate_columns` | `secret_requirements_for_config` returns `(MASK_ROOT,)` | red today (returns `()`); green after E1 |
| AT-E6 | `tests/secret_providers/test_admission_before_read.py`: `PandasExecutionAdapter` and the sequential route on a compiled `date_shift` plan, with `key_provider=None` and with a 32-byte `SeedKeyProvider` | refused by `require_mask_key` with the code before the handler runs | passes today; the missing-provider cells are red under M1 and the 32-byte seed cells are red under M3 |
| AT-E7 | `tests/unit/transforms/test_date_shift_key_failure.py` (shrunk in place) | `DateShiftStrategy`, `_shift_for_value_md5`, `_shift_for_value_keyed` and `_parse_date` are absent from `decoy_engine.transforms.date_shift`; `_detect_format` and `_COMMON_FORMATS` import and keep their existing oracles | red today (the names exist) |
| AT-E8 | `tests/sentry/test_source_hygiene.py`: AST check that resolves import aliases | no MD5 call or `noqa: S324` under `src/decoy_engine/`. Seed one failing case for each normal spelling: `hashlib.md5(...)`; `import hashlib as h` then `h.md5(...)`; `from hashlib import md5` then `md5(...)`; `from hashlib import md5 as m` then `m(...)`; `hashlib.new("md5", ...)`; and `hashlib.new('md5', ...)` | red today at the legacy site; deleting support for any spelling makes its seeded case fail |
| AT-E9 | `tests/secret_providers/test_classifier_equivalence.py`: the keyed-strategy sentry, three parts. (a) For each `SCALAR_HANDLERS` entry, parse the handler class's module (`inspect.getsourcefile`, then `ast`); if it reads `mask_key` (attribute `.mask_key`, a `mask_key=` keyword, or a `mask_key` name passed to `derive` or `DeriveContext`), query `column_is_keyed` for the same strategy with three shapes: default (`deterministic=False, vault=False`), deterministic (`True, False`) and vault (`False, True`). A default-keyed result passes. A default-unkeyed result passes only when the handler's live `wizard_options` advertises the `deterministic` column option and both the deterministic and vault shapes classify keyed. Derive the option name from the handler descriptor and every keyed result from `column_is_keyed`; keep no test-local strategy set or keyedness table. Under M1, `date_shift` still reads `ctx.mask_key`, its default shape changes to unkeyed, and its handler advertises no `deterministic` option, so part (a) goes red. (b) For every member of `ALWAYS_KEYED_STRATEGIES` that is a handler name, a minimal raw config `{"tables": [{"name": "t", "columns": [{"name": "c", "strategy": s}]}]}` makes `admit_mask_key` raise the code; the list comes from the frozenset, never a hand list. (c) An `ast` walk of `src/decoy_engine/` finds every `StrategyContext(` call and requires a `mask_key=` keyword whose value calls `require_mask_key`. Wire this sentry outside `tests/sentry/` exactly like `tests/secret_providers/test_leak_sentry.py`: add its path to `SENTRY_PATHS` and `DOC_WALK_GUARDS` in `scripts/dev/gates.sh`, and to `SENTRIES` in `tests/sentry/test_sentry_manifest.py`. | (a) red under M1 and under "add a handler that reads `ctx.mask_key` to `KNOWN_UNKEYED_STRATEGIES` without a classifier-backed conditional shape"; (c) red under M5; (b) red if the walk drops a member; removing the path from any gate/manifest registry makes the existing manifest guards red |
| AT-E10 | existing `tests/native/test_draw_sites_catalogue_pinned.py`, `tests/native/test_draw_site_providers_golden.py`, `tests/unit/execution/test_date_shift_oracle_identity.py`, `tests/native/test_determinism_goldens.py` and `tests/physical/test_shadow_date_shift.py` | only the `mask.date_shift` `_ENTRY_DIGESTS` element and `_CATALOGUE_DIGEST` move for metadata. `_MAP_DIGESTS`, `test_draw_site_providers_golden.py`, oracle identity, determinism goldens and KATs are byte-identical and green | regression guard plus the class-10 metadata-only re-pin |
| AT-E11 | existing `test_unkeyed_work_needs_no_secret` | an all-unkeyed config still runs with no secret (engine QA KEY-09) | regression guard |
| AT-E12 | AT-E1 extended | the message contains the constant guidance; a marker placed in the source cells appears in no message or log record; the raised exception has `__cause__ is None` and `__context__ is None` (catalog class 3) | passes today; pin |

Scanner scope for AT-E8 and AT-E9 (catalog class 5): the AST-normalized spellings listed above
only. Deliberate evasion (`getattr(ctx, "mask" + "_key")`, `importlib`) is V2-LOG. AT-E8 resolves
the imported binding before matching the call and has one seeded case per listed spelling. AT-E9
derives its handler list from `SCALAR_HANDLERS`, the conditional capability from each handler's
`wizard_options`, and all three keyed results from `column_is_keyed`, so it keeps no strategy-name
or keyedness table.

CLI (C1):

| Id | Test (file) | Asserts | Fail-before |
|---|---|---|---|
| AT-C1 | Extend the existing strategy parametrization in `tests/e2e/test_keyed_secret_guidance.py` for `test_run_refusal_is_usage_and_names_the_cli_remedy` and `_keyed_pipeline(strategy=...)` with `date_shift`, including a marker source date | exit 1; stderr carries `_mask_secret_guidance.RUN`; no run folder, target or scratch; the marker appears in no output | passes on 0.27.0; red under CLI M4 |
| AT-C2 | Extend the existing JSON and chunked tests in the same file with `date_shift` instead of adding another test module | JSON has the same fixed text; plain and chunked agree; no marker or path appears | passes today; red under M4 |
| AT-C3 | Extend the existing `decoy.mask()` test in the same file with `date_shift` | `MaskSecretConfigError` has the `API` text and no output is written | passes today; red under M4 |
| AT-C4 | Extend `_keyed_pipeline(strategy=...)` to construct `nested` with child `date_shift` and `text_mask` with date detectors; add both shapes to the existing run and every-route fixed-text parametrizations | every shape has the same refusal, no output and no marker value | passes today; red under M4 |
| AT-C5 | New positive-control test only, in `tests/e2e/test_keyed_secret_guidance.py`: run the top-level `date_shift` shape with `--mask-secret env:...` | exit 0; each non-null output date differs from its source by an offset in `[min_days, max_days]` | positive control |
| AT-C6 | `tests/e2e/test_explain_command.py` | the `date_shift` one-liner says the offset is keyed and needs a mask secret | red today ("Move dates by a random number of days") |
| AT-C7 | Existing validate tests in `tests/e2e/`: use `_mask_secret_guidance.config_is_keyed` as the one classifier call and carry its boolean into rendering. A keyed config with no `mask_secret_ref` gets `_mask_secret_guidance.INIT_HINT` once on human output only | exit 0; `--json` byte-equal to before; `--quiet` unchanged; `--fail-on-warning` still exits 0; no warning/finding is created and rendering does not call the classifier again | red today (no hint) |
| AT-E14 | C1, unconditionally, after E2 is present in the CLI's engine dependency: extend the existing `decoy validate` compile-error parametrization with the same degenerate-range config as AT-E13 | exit 1 with `plan.date_shift_range_degenerate` | red before E2 |

E2:

| Id | Test | Asserts | Fail-before |
|---|---|---|---|
| AT-E13 | beside the existing `date_shift` compile tests | `min_days == max_days` is refused at compile with `plan.date_shift_range_degenerate`, whether written in normal or reversed-bound test shapes; the value-free message names table and column only; `min_days: 0, max_days: 1` compiles | red today |

## 6a. Class table

Classes from the plan contract (`docs/handoffs/DEFECT-CATALOG.md`, section 3).

| # | Class | Closing structure | Proving test | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Value-bearing output | The refusal raises `KeyedStrategyRequiresSecret` with the fixed `KEY_REQUIRED_GUIDANCE` text (`keyprovider.py:224`); E2's message names table and column only | AT-E12 seeded marker in source cells, checked in the message, log records, `__cause__` and `__context__`; AT-C1 checks stdout, stderr and `--json` | Format the first source cell into the refusal message: AT-E12 fails |
| 2 | Cleanup missing on an exit path | The refusal fires in `admit_mask_key` before any target or scratch is opened, so no exit path owns a file yet | AT-E1 target path absent; AT-C1 no run folder, target or scratch | Move `admit_mask_key` after the target writer opens in `build_run_context`: AT-E1 and AT-C1 fail |
| 3 | State machine and concurrency | N/A: the refusal is a pure check on config and provider at entry; no state, lock or cache is added | | |
| 4 | Route parity and silent fallback | One registry (`ALWAYS_KEYED_STRATEGIES`) and two choke points (`admit_mask_key`, `require_mask_key`) serve every route; `StrategyContext` is built only with `mask_key=require_mask_key(...)` | AT-E1 over every `execution_mode`, AT-E2 both chunked entries, AT-E6 adapters, AT-E9 (c) AST walk of every `StrategyContext(` | M1 and M5 |
| 5 | Referential integrity | N/A: no FK handling changes; `group_by` anchors keep their keyed derivation and only gain a pinned refusal | | |
| 6 | Untrusted producer | `_load_legacy` and `require_mask_key` refuse a `SeedKeyProvider` independently of byte length; both also refuse any resolved key under 32 bytes | AT-E3 and AT-E6 include 32-byte `SeedKeyProvider` cases plus the 8-byte duck-typed case | M2 turns AT-E3 red; M3 turns AT-E6 red; deleting the length check turns the short-key cell red |
| 7 | TOCTOU on a path | N/A: no path is checked or used by this change | | |
| 8 | Weak tests and overclaimed evidence | Each test is labelled FAIL-BEFORE (red on main) or PIN (green on main, red under a named mutation); mutations rerun on the final head (catalog class 9) | AT-E5, AT-E7, AT-E8, AT-C6 recorded red on main; AT-E1 to AT-E4, AT-E6 recorded red under M1 | Revert the `_walk_keyed_columns` fix: AT-E5 fails, proving the label is honest |
| 9 | Behavior-preserving refactor drift | Deleting the dead class keeps `_detect_format` and `_COMMON_FORMATS` in place; keyed output is byte-identical | AT-E10 goldens and KATs unchanged; AT-E7 imports both helpers with their oracles | Change `_COMMON_FORMATS` order: AT-E7 or the bucket_perturb oracle fails |
| 10 | Frozen contract drift | No reason code is added in E1; `DateShiftStrategy` was never in a public `__all__`; the draw-site edit is metadata-only; E2 adds one reason with `since=UNRELEASED` | Existing reason sentries, `test_public_import_boundary.py`, and AT-E10. E1 updates only the `mask.date_shift` entry digest and catalogue digest; coverage-map and provider-golden bytes stay fixed | Change the provider mapping or regenerate a provider golden: AT-E10 fails |

## 6b. Enumerations from the code

Read at engine `origin/main` `13c95c7de`.

### Exit paths

- Refusal in `admit_mask_key` (`secret_providers/_preflight.py:389`), reached from `build_run_context` (`execution/_pipeline_context.py:314`) and the chunked oracle (`execution/_chunked_oracle.py:122`): raises before profiling and before any source or target is opened.
- Refusal in `require_mask_key` (`keyprovider.py:232`) at an adapter or route: raises before the first strategy runs, after compile; no target is open at that point on any route.
- Success: the run continues with the admitted key; unchanged by this row.

### Routes

- `run_pipeline` (`execution/_pipeline.py:115`) for `auto`, `stream`, `sequential`, `full_frame`, `out_of_core`.
- `run_mask_pipeline_chunked` (`execution/_chunked.py:382`) and `run_mask_chunked` (`execution/_pipeline_route_exec.py:565`, `execution/native/_chunked_entry.py:589`).
- Adapter sites calling `require_mask_key`: `execution/_pandas_adapter.py:245`, `execution/_sequential.py:350`, `execution/_chunked_oracle.py:265`, `execution/native/_chunked_entry.py:262`, `execution/out_of_core/_preflight.py:65`.
- Other `admit_mask_key` callers that do not run `date_shift` but share the walk: `unmask.py:264`, `vault.py:461`.

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
- `column_is_keyed` and each handler's `wizard_options`: AT-E9 derives the default,
  deterministic and vault classification and the conditional capability from these owners; it
  adds no strategy-name exception table.
- `tests/sentry/test_source_hygiene.py`: AT-E8 joins it instead of a new sentry module.
- `scripts/dev/gates.sh` `SENTRY_PATHS` and `DOC_WALK_GUARDS`, plus
  `tests/sentry/test_sentry_manifest.py` `SENTRIES`: AT-E9 reuses the exact named-sentry wiring
  already used for `tests/secret_providers/test_leak_sentry.py`.
- CLI `_mask_secret_guidance.py` texts (`RUN`, `API`, `INIT_HINT`): reused, never copied.
- Reason registry (`reasons/plan/_part*.py`): E2's one reason only.

## 6d. Frozen contracts

- Reason codes: `runtime.keyed_strategy_requires_secret` reused, unchanged. E2 adds `plan.date_shift_range_degenerate` (additive, `since=` set).
- Public engine surface: the deleted class is not exported from `decoy_engine` or
  `decoy_engine.transforms`. `keyed_columns_for_config` is public; E1 changes its output only for
  an invalid both-kinds raw dict that `PipelineConfig.model_validate(...).model_dump()` cannot
  produce. Schema-valid inputs and ordering stay unchanged. Record that narrow hardening in
  `docs/compatibility-contract.md`.
- Keyed `date_shift` output and KATs: unchanged (AT-E10).
- CLI exit codes and `--json` schema: unchanged (AT-C7 checks `--json` byte-equal).
- Draw-site catalogue: the `mask.date_shift` entry metadata and whole-catalogue digest move;
  coverage maps, provider identifier data and provider goldens stay byte-identical.

## 6e. Pre-mortem

- A gate reviewer finds a route that builds `StrategyContext` without `require_mask_key`: AT-E9 (c) walks every construction, so the build fails first.
- The class deletion breaks a hidden importer: `grep` at planning found only `_detect_format` and `_COMMON_FORMATS` importers; the builder reruns it on the branch head and AT-E7 imports both.
- A sentry baseline or the draw-site inventory still names a deleted symbol: F8 and F9 list every known file; the T1 selection includes `tests/sentry/` and `tests/native/`.
- AT-E9 (a) sees default-unkeyed `faker` and `categorical`: their live handler descriptors
  advertise the `deterministic` column option, and `column_is_keyed` classifies both the
  deterministic and vault shapes keyed. No exception names are copied into the test.
- E2 rejects a real customer config: Q3 explicitly accepts that break because a one-day range is
  a constant shift a config reader can reverse.

## 7. Migration impact

- Configs: no behavior change. Every config with `date_shift` and no secret has been refused
  since the F13 admission work (before 0.22.0, per the Mac proof). Keyed output is unchanged.
- Python API: `decoy_engine.transforms.date_shift.DateShiftStrategy` and three private helpers
  are removed. They are not exported from `decoy_engine` or `decoy_engine.transforms` (its
  `__all__` holds `BaseMaskingStrategy` only). Public `keyed_columns_for_config` changes only for
  invalid both-kinds raw table dicts, which it now classifies conservatively instead of skipping.
  Schema-valid inputs do not change. `changelog.d/date-shift-unkeyed.md` records the removal and
  the public-classifier hardening; E1 does not edit `CHANGELOG.md` directly.
- CLI: no code imports the class. C1's run-refusal tests pass on 0.27.0. C1 starts only after E2
  is present in the CLI's engine dependency so its unconditional AT-E14 validate cell can pass.
- Examples: no engine example or doc YAML block uses `date_shift`. The `mask.date_shift` entry in
  `docs/proof-manifest.json` is generated with a throwaway 32-byte secret
  (`scripts/gen_proof_manifest.py` `_PROOF_SECRET`) and does not change. CLI templates already
  carry the keyed comment block (`_mask_secret_guidance.YAML_COMMENT`); the shape-and-privacy
  guide 02 already says keyed.
- E2 makes a config with a one-day range fail compile. That is intended;
  `changelog.d/date-shift-range.md` and `docs/strategies.md` say so.

## 8. Docs and checklists (in E1 unless noted)

- `docs/strategies.md`: fix both row-24za `date_shift` sentences in E1. The main strategy section
  says offsets derive from `mask_key`, a mask secret is required, and non-null unparseable values
  produce `format_error` rather than pass through. The `text_mask` cross-cell determinism section
  says date spans use the admitted mask key, not `HMAC-SHA256(job_seed, matched_text)`.
- `docs/determinism.md`: replace the stale paragraph that says `mask_key` falls back to `job_seed`
  before GA with the no-fallback rule in every release phase, matching
  `docs/security/key-derivation.md`.
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
  under Q2. `docs/qa/05-keys-determinism-namespaces.md`: KEY-05 also names `date_shift`; close
  the stale `job_seed` open point under Q2. `test_qa_checklist_reasons` stays green.
- Engine changelog fragments: `changelog.d/date-shift-unkeyed.md` for E1 and
  `changelog.d/date-shift-range.md` for E2. Do not edit `CHANGELOG.md` in either slice.
- C1 (CLI repo): `docs/qa/cli-v1-checklist.md` RUN-14 and KEY-05 keep their wording and gain the
  test ids; `docs/ROADMAP.md` row 24zb moves to DONE with PR numbers, plus the shipped-log entry.
  Proportionality item C9 and duplication-census E24 (`transforms/date_shift.py:123`) are records;
  C1 does not edit them, and the roadmap row notes E1 closed them.

Related V2-LOG cleanup: `src/decoy_engine/internal/crypto.py::deterministic_hash` is the deprecated
`SHA256(value + seed)` helper noted by the 11-11 plan. It has no live caller in `src/`, is outside
the public API, and already has a deprecation sentry. Its deletion remains a separate V2 item with
its own unit-contract review; it does not affect this verdict or these slices.

## 9. Placement

No new Python or test module is added. The only new engine files are the two required changelog
fragments in the directory assigned by `CODEMAP.md:276`. Design notes: none, no new structure.

| Change | File | Map line that places it | Beside |
|---|---|---|---|
| Delete the V1 class and three helpers; keep `_detect_format`, `_COMMON_FORMATS`, rewrite the docstring (about 100 of 285 lines left) | `src/decoy_engine/transforms/date_shift.py` | `transforms/` leaf package of reused helpers (`transforms/__init__.py` docstring) | `bucket_perturb.py`, `text_mask.py` (its importers) |
| Walk `columns` whatever `generate_columns` holds | `src/decoy_engine/secret_providers/_requirements.py` | the keyed-ness registry ("one authority", module docstring) | `_preflight.py` |
| Repoint `mask.date_shift` `call_site`, `seed_derivation`, notes | `src/decoy_engine/execution/native/_draw_sites_mask.py` | draw-site inventory | `_draw_site_providers.py` |
| Docstring: `derive(mask_key, ...)`, not `job_seed` | `src/decoy_engine/execution/_strategies/_date_shift.py` | strategy handlers | n/a |
| Comment and docstring references to the deleted class | `profiling/recommendations.py`, `transforms/fpe.py`, `transforms/__init__.py`, `reference_tables/_types.py` | unchanged homes | n/a |
| AT-E4, AT-E5, AT-E9 and gate wiring | `tests/secret_providers/test_classifier_equivalence.py` (126 lines now), `scripts/dev/gates.sh`, `tests/sentry/test_sentry_manifest.py` | owning package tests (`CODEMAP.md:267`); dev tooling (`CODEMAP.md:272`); sentry manifest (`CODEMAP.md:270`) | the existing `test_leak_sentry.py` wiring |
| AT-E1 to AT-E3, AT-E6, AT-E12 | `tests/secret_providers/test_admission_before_read.py` (174 lines) | same | `_helpers.py` gains a `keyed_config(strategy=...)` parameter |
| AT-E8 | `tests/sentry/test_source_hygiene.py` (229 lines) | `tests/sentry/` is flat and over the fan-out limit (75 modules), so the check joins an existing file | n/a |
| AT-E7 | `tests/unit/transforms/test_date_shift_key_failure.py` (shrinks from 243) | existing | n/a |
| Dead-class redaction tests | Remove the dead-class key-failure case from `tests/unit/execution/test_expression_log_redaction.py`; port its security-relevant caplog assertion for unparseable cell values into the live-handler case in `tests/unit/execution/test_row_error_producers.py` | existing handler and log-redaction tests | `TestDateShiftRowErrors` |
| E2 check and frozen fixture updates | `src/decoy_engine/plan/_checks_date_shift.py`, `src/decoy_engine/reasons/plan/_part1.py`, `tests/fixtures/f29/producer-inventory.json`, `tests/fixtures/f29/reason-baseline.json` | existing plan checks, central reason registry and its frozen fixtures | `check_date_shift_group_by_refs` |
| Changelog fragments | `changelog.d/date-shift-unkeyed.md`, `changelog.d/date-shift-range.md` | `CODEMAP.md:276` | other slice fragments |
| C1 | `src/decoy/cli/explain.py`; `src/decoy/cli/validate.py`; `tests/e2e/test_keyed_secret_guidance.py` and existing validate tests | CLI command modules and existing E2E tests | `_mask_secret_guidance.py` (classifier and text reused, not copied) |

Choke points: keyed-ness lives in `_requirements.py` only; the refusal lives in `admit_mask_key`
and `require_mask_key` only; CLI wording lives in `_mask_secret_guidance.py` only. This row adds no
second copy of any of them. The guard for the keyed-ness rule is AT-E9; its red mutations are M1
for part (a) and "drop `mask_key=` from `_sequential.py`'s `StrategyContext`" for part (c).

Test deletions are explicit and limited to assertions whose only subject is the deleted class.
AT-E7 shrinks the legacy-class test file. In `test_expression_log_redaction.py`, the legacy
key-derivation logging case goes with the implementation it alone exercised; the caplog assertion
that a bad date cell never reaches logs is ported to the live `DateShiftStrategyHandler` row-error
test. No security assertion is silently dropped, and no other test is weakened, skipped or deleted.

E2 frozen-fixture accounting at `13c95c7de`:

- `tests/fixtures/f29/reason-baseline.json` gains the additive sorted row
  `plan/date_shift_range_degenerate`, owned by `PlanCompileError`, with source
  `plan/_checks_date_shift.py#kw:PlanCompileError`. The following baseline rows shift down by one.
- `tests/fixtures/f29/producer-inventory.json` gains the new `PlanCompileError` producer in
  `check_date_shift_group_by_refs`. Regeneration updates the exact `line` fields for the existing
  entries in that function: `date_shift_group_by_unsupported_in_nested`, both
  `date_shift_missing_group_by_ref` sites, `date_shift_group_by_on_fk_column_unsupported` and
  `date_shift_group_by_with_when_unsupported`. If the check is inserted above the preserve-values
  section, its `_FK_SHAPE_CODE`, `date_shift_preserve_values_invalid`,
  `date_preserve_values_with_group_by_unsupported` and `_FK_SHAPE_CODE` use-site line fields shift
  too. No unrelated producer identity changes.

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
| E1 | engine | Delete the MD5 class; walk fix; draw-site metadata re-pin; AT-E1 to AT-E12; sentry wiring; baseline shrinks; docs and QA sections 05 and 07; changelog fragment | 8 `src/` files (section 9); no new code/test module | about 650 to 750 changed, about two thirds deletions | R2 | Dennis then Codex; M1, M2, M3 and M5 rerun on the final head and recorded |
| E2 | engine | One-day range refused at compile, reason `plan.date_shift_range_degenerate`, AT-E13, reason fixtures, docs and changelog fragment | 2 production files, 2 frozen fixtures | about 100 | R2 | Dennis then Codex; reason and producer sentries run on the final head |
| release | engine | Rides the daily engine release train (owner D4). No separate release work. | n/a | n/a | n/a | n/a |
| C1 | CLI | After E2 is present in the CLI's engine dependency, extend existing AT-C1 to AT-C4 parametrizations, add only the AT-C5 positive control, AT-C6, AT-C7 and AT-E14, explain text, validate human-only hint, checklist ids, roadmap row and shipped log | 2 production files, existing E2E tests only | about 150 to 200 | R1 | Codex; M4 on the final head |

Test depth: T0 per edit. E1 T1 includes `tests/secret_providers/`, `tests/sentry/`, transform and
handler tests, native inventory tests, `tests/unit/execution/test_date_shift_oracle_identity.py`,
`tests/native/test_draw_sites_catalogue_pinned.py`,
`tests/native/test_draw_site_providers_golden.py`, and the physical shadow date-shift tests. The
gate reruns T1 on the exact head. E1 changes a secret-admission walk and a frozen catalogue, so one
full suite runs on the merge head or merge-train batch head against the stored main baseline. E2
runs plan checks plus all reason/producer fixture sentries. C1 runs
`tests/e2e/test_keyed_secret_guidance.py`, AT-E14 and the affected validate/explain tests; it needs
no full suite.

Build timing: build E1 now. This supersedes the 2026-11-11 instruction to wait for the section-07
QA pass. That later pass runs DATE-13 against the already-guarded code. Build C1 only after E2 is
present in the CLI's engine dependency because C1 owns AT-E14 unconditionally.

## 12. Owner questions, decided 2026-11-16

1. **Q1, option (b): decided.** `decoy validate` prints one fixed
   `_mask_secret_guidance.INIT_HINT` line on human output only when
   `_mask_secret_guidance.config_is_keyed` says the validated config is keyed and it has no
   `mask_secret_ref`. Compute that boolean once and pass it to the renderer. Do not call a second
   classifier, create a finding, change `--json`, or change any exit.
2. **Q2: yes.** E1 folds in both stale row-24za `date_shift` sentences in
   `docs/strategies.md` (unparseable-value behavior and text-mask date-span keying) and the stale
   no-provider `job_seed` fallback paragraph in `docs/determinism.md`. The rest of 24za stays out.
3. **Q3: yes.** E2 refuses `min_days == max_days` at compile with
   `plan.date_shift_range_degenerate`, including when the written bounds are in reversed order.
4. **Q4: build E1 now.** This supersedes the 11-11 section-07 timing rule.
5. **Q5: yes.** Hard-delete the legacy class and its three private helpers. Keep `_detect_format`
   and `_COMMON_FORMATS` in place for their live importers.

## 13. Not verified

- No test was run (devbox rule). Each "passes today" claim comes from reading the code and the
  existing tests, plus the 2026-11-11 Mac proof on 0.22.0. The builder confirms each fail-before
  claim on the branch before changing source.
- Engine anchors and line references in this plan were re-read from `origin/main` at
  `13c95c7de`. The builder re-resolves the new live-handler `call_site` from its final branch head
  before writing the metadata and digests.
- That `inspect.getsourcefile` resolves each `SCALAR_HANDLERS` class to its own module (true for
  the 25 handlers read; `_composite.py` is not in `SCALAR_HANDLERS`).
- That no native `_ext` module adds a keyed draw for a strategy classified unkeyed. AT-E9 (a)
  reads handler modules only; the native modules are reached from those handlers and from
  `require_mask_key` callers.
