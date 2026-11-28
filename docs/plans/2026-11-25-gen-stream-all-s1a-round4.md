# GEN-STREAM-ALL S1a, round 4: one Faker footprint rule

Status: plan

Rules consulted: 00-universal, development-loop, bugfix, cross-cutting-concerns, testing,
architecture (README routing table).

PR #813, base head `752ce7a65`. Codex round 3 returned NO-GO with three V1 findings, one DESIGN
item and one V2-LOG item. The three V1 findings are one class: the generation ledger estimates
some allocations and misses others, so a run under a ceiling can allocate past it. This plan
fixes the rule that decides what a run reserves, not the three symptoms.

## Guarantee

Under a bounded ledger, `run_generation` reserves, before it first opens a Faker locale, the
measured cold-import worst case of every locale any step of the run opens (in-run validation,
admission, bounds, pool build, per-row streams, provider columns). A pool's Arrow form is
counted by the root buffers it keeps alive. Non-goals are listed under "Out of scope".

## The rule

1. **One locale rule.** `internal/faker_locale.py` (split from `internal/faker_setup.py`, the Faker choke point, and the lowest layer
   that validation, budgeting and generation all import) owns:
   - `DEFAULT_GENERATE_LOCALE` (moved from `generators/derivation.py`; every user imports it
     from `faker_setup`, no re-export);
   - `effective_locale(column_locale, default_locale)`: the column's locale, else the run
     default, else `en_US`;
   - `locale_entries(locale)`: the distinct locales Faker opens for it, in order (one for a
     string, each list entry, `-` read as `_`, a falsy entry is `en_US`).

   The validator (`plan/checks/_generate_columns.py`), the provider kind
   (`generation/kinds/_provider.py`) and the run budget (`run_faker_footprint` in
   `pool/_resident.py`) call these. The copy in
   `pool/_resident.py` (`pool_locales`, `_DEFAULT_LOCALE`) is deleted. Generation keeps its
   instance-caching branches; a test holds the Faker each stream opens to
   `locale_entries(effective_locale(...))`.

2. **One reservation for every Faker open of the run, taken before the first open.**
   `run_generation` reserves `faker_provider_init` before the default-locale check, for the
   locales of every column that opens Faker: every `faker` column (pooled or per-row, any row
   count) and every `provider` column whose backend is Faker, plus `en_US` whenever any such
   column exists (admission, bounds and the per-row path probe the default Faker). The
   pool-eligibility filter is removed from the walk.

3. **A measured provider-init bound.** Per locale `l`, a retained bound `R(l)` (bytes kept after
   the locale is open) and a transient bound `T(l)` (peak minus retained). For a set `S` of
   locales opened in any order, and `n` Faker-opening columns:

   `provider_init_bytes(S, n) = sum(R(l) for l in S) + max(T(l) for l in S) + n * INSTANCE`

   This holds whatever the order: opening `l` after others peaks at most at the retained bytes
   of the others plus `l`'s own solo peak, and a locale opened later retains no more than when
   opened alone (its shared modules may already be loaded).

   **Method.** One fresh interpreter per locale. Import the engine with its cached bytecode,
   then set `sys.pycache_prefix` to an empty directory and `sys.dont_write_bytecode`, so every
   Faker locale module compiles from source (the cold case Codex hit). Under `tracemalloc`,
   run `make_faker(l)` and `get_faker_providers` (what the validator does), `gc.collect()`,
   then read the retained and peak bytes. A second, warm instance gives `INSTANCE`.

   **Measurement** (Mac, Faker 40.23.0, all 102 `AVAILABLE_LOCALES`):

   | locale | retained | peak | transient |
   |---|---|---|---|
   | it_IT | 9.52 MB | 59.43 MB | 49.91 MB |
   | de_AT | 1.43 MB | 14.02 MB | 12.59 MB |
   | any other (max) | 1.06 MB | 5.85 MB | 4.90 MB |
   | extra instance (max) | 0.14 MB | 0.32 MB | |

   Codex's pair (`de_AT` then `it_IT`, cold) peaked at 60.86 MB in the same probe; the formula
   gives 74.9 MB before headroom.

   **Bounds, at least 25% over the measure, rounded up to a MiB:** `it_IT` R 12 MiB, T 64 MiB;
   `de_AT` R 2 MiB, T 16 MiB; every other locale R 2 MiB, T 8 MiB; `INSTANCE` 512 KiB per
   Faker instance. The instance count is the sum of `len(locale_entries(...))` over every
   column that opens Faker, plus one for the default-locale check. A one-column `en_US` run
   (two instances) is charged 11 MiB (16 MiB in round 3); a one-column `it_IT` run 79 MiB.

   **Guard.** A test runs the same probe for every `AVAILABLE_LOCALES` entry (four subprocesses
   at a time) and fails if any locale's retained or transient bytes exceed its bound. A Faker
   upgrade or a Python version that makes a locale heavier turns it red; the fix is a table
   entry. It runs on every CI Python.

4. **Arrow retained size by root buffer.** `measured_pool_bytes` counts each distinct root
   buffer the Arrow form keeps alive (walk `Buffer.parent` to the root, dedupe by address and
   size), not `get_total_buffer_size`. An IPC-read array is a zero-copy view of its message
   body and keeps the whole body alive.

5. **Import-cycle test that can fail.** The subprocess import-order test passes with the eager
   import restored, because the `decoy_engine.generation` package `__init__` fixes the real
   order. It is replaced by a static check: the module-level imports (outside functions and
   `TYPE_CHECKING`) of `generation.stream`, `stream._batches` and `generation._column_streams`
   form no cycle.

## Choke points, guards, mutations

| Rule | Choke point | Guard test | Mutation that turns it red |
|---|---|---|---|
| locales a run opens | `pool/_resident.run_faker_footprint` walk over `locale_entries(effective_locale(...))` | spy on `Faker.__init__` during `run_generation`: every opened locale is in the reserved set, and the reservation precedes the first open | restore the pool-eligibility filter in the walk |
| locale resolution | `faker_locale.effective_locale` / `locale_entries` | stream Faker `.locales` equals the rule for each case | drop the `-` normalization or the default fallback |
| provider-init bound | `_resident.provider_init_bytes` table | cold sweep of every locale | set the `it_IT` T bound to 16 MiB |
| Arrow retained bytes | `_value_pool.measured_pool_bytes` | IPC-backed pool test | go back to `get_total_buffer_size` |

## Acceptance tests (written first, red on `752ce7a65`)

| Case | Test | Red on 752ce7a65 because |
|---|---|---|
| V1-1 | One-row `prefix` job, runtime default `it_IT`, 6 MiB ceiling: refused with `GenerationBudgetExceeded`, and no Faker opened before the refusal | below the pool threshold nothing is reserved; the run completes |
| V1-1 class | For each probe config (default-locale per-row, locale list, explicit per-row, provider column), every locale Faker opens during `run_generation` is in the reserved set | the per-row and default-locale opens are not in the set |
| V1-2 | `[de_AT, it_IT]` 50,000-row `prefix` job, 32 MiB ceiling: refused before any Faker open | round 3 charges 18 MiB and admits it |
| V1-2 bound | Every locale's cold retained and transient bytes are within its bound | the it_IT cold peak of 59 MB exceeds the 16 MiB first-locale charge |
| V1-3 | A one-string array read from an IPC stream whose body holds a 1 MB sibling column: `measured_pool_bytes` is at least the body size and a 1 KiB `PoolCache` refuses it | the old measure counts the slice only |
| DESIGN | For each (column locale, default) case the stream's `Faker.locales` equals `locale_entries(effective_locale(...))` | refactor guard; passes before and after |
| V2-LOG | The static import-cycle test fails with the eager `_batches` import restored | the subprocess test passes with it restored |

Red evidence is assertion failures: new names are first stubbed with round-3 behaviour.

## Failure modes

- Ceiling below the charge: `GenerationBudgetExceeded` before any Faker open; the message
  names the stage only, never a locale or a value.
- Unknown or malformed locale: charged at the default tier; the validator then refuses it with
  its own code. A malformed config charges nothing and the plan check refuses it.
- Unbounded ledger (`budget_bytes=None`): the reservation is recorded, nothing refuses.
- Warm bytecode: the charge is the cold worst case, so warm runs are over-charged (safe).
- Faker or Python makes a locale heavier: the sweep test fails.

## Out of scope

- Plan-time validation (`compile_plan`, `decoy validate`) opens explicit locales before any run
  ledger exists. The ceiling is a run contract; logged for V2.
- Mimesis-backed provider columns open no Faker locale and are not charged here.

## Size and placement

Source: `internal/faker_locale.py` (new; locale rule), `generators/derivation.py`,
`plan/checks/_generate_columns.py`, `generation/kinds/_provider.py`, `generation/_streamed.py`,
`generation/pool/_resident.py` (`provider_init_bytes` signature changes, `pool_locales` goes),
`generation/pool/_value_pool.py`. No new source file. New tests go beside the existing ones in
`tests/unit/generation/stream/` and `tests/unit/generation/pool/`. Tests that call
`provider_init_bytes(count)` or `pool_locales` move to the new signature with the same or
stronger assertions. No ceiling in an existing test is raised. The run walk goes in
`pool/_resident.py` beside the bound table, so `_streamed.py` shrinks from 608 to 589 lines.

## Design notes

No new structure. One place per fact: locale rule in `faker_locale`, bound table in
`_resident`, retained Arrow bytes in `_value_pool`.

## Established solutions

Searched the codebase for every Faker open site and every locale copy (listed above), and the
web for Arrow buffer retention. Sources followed: `tracemalloc` (stdlib) for Python allocation
peaks, as the existing A14 tests do; `sys.pycache_prefix` (Python 3.8+) to force a cold
compile without touching the install; Arrow's memory model, where a sliced or IPC-read buffer
holds a reference to its parent ([pyarrow.Buffer](https://arrow.apache.org/docs/python/generated/pyarrow.Buffer.html),
[Memory and IO](https://arrow.apache.org/docs/python/memory.html)). The bound table is custom
because Faker publishes no memory figures.

## Defect classes

From the plan contract's class list (classes 1 to 10, checked by `~/bin/plan-lint`).

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | The refusal names the stage and byte counts only; no locale, path or config value | Existing budget-message test | Put the locale list in the message: the test fails |
| 2 | Cleanup on an exit path | The reservation is a `run_scope` ExitStack callback, released on every exit, refused runs included | A refused run leaves the ledger at zero | Drop the callback: the zero-ledger check fails |
| 3 | State and concurrency | The bound table is a frozen module constant; no new module state. Test spies are patched per test and the validator cache is cleared | Spy tests clear `_builtin` and the thread default Faker | N/A: no shared state added |
| 4 | Route parity and silent fallback | Pooled, per-row, provider and default-locale routes feed one walk; an unknown locale falls to the default tier and the validator still refuses it | Spy test over all four probe configs | Restore the pool filter: the spy test fails |
| 5 | Referential integrity | N/A: no keys or foreign references | | N/A |
| 6 | Untrusted producer | N/A for V1 (accidental-leak threat model): config is the user's own, and malformed locale values are refused by the plan check | | N/A |
| 7 | Check then use on a path | The reservation is taken in the same scope, before the first open, for the same column list the run then uses | Spy test checks reserve-before-open order | Move the reserve after the default check: the order check fails |
| 8 | Weak tests and overclaimed evidence | Each acceptance test is shown red on `752ce7a65` with stubbed names; the import-cycle test is shown red with the eager import restored; the bound is measured, not guessed | Builder report lists each red result | Return the old values from the stubs: the tests stay red |
| 9 | Refactor drift | Locale rule moves to `faker_locale`; every caller updated in this slice; no re-export | DESIGN guard test; existing validator tests pass unchanged | Leave the copy in `_resident`: grep for `pool_locales` finds it |
| 10 | Frozen contract drift | N/A: `pool_locales` and `provider_init_bytes` are internal to `generation.pool`; no public name changes | Public import boundary sentry stays green | N/A |

## Enumerations

### Exit paths

- Refused before any open: the reservation raises, the ExitStack unwinds, nothing to release.
- Refused later in the run, or any exception: the `run_scope` callback releases the charge.
- Normal end: the same callback releases it.

### Routes that open Faker

- Pooled `faker` column (pool build, `_faker_pool.build_pool_values`).
- Per-row `faker` column with an explicit locale or the run default (`_column_streams.py:176`).
- Locale-less per-row column, admission and bounds probes (`_get_default_faker`, en_US).
- `provider` column with a Faker backend (`kinds/_provider.py:64`).
- In-run validation (`check_faker_default_locale`, `_generate_columns.py:538`).

### FK shapes

N/A: the change touches locale budgeting and pool sizing, not keys or references.

### Fields

- Column `locale` (string, list, empty, missing).
- Run `instance_default_locale` (string or missing).
- Column `kind` / `type` (`faker`, `provider` with backend type).

### Output surfaces

- `GenerationBudgetExceeded` message: stage name and byte counts only.
- `PoolCapacityError` message: unchanged, byte counts only.

## Reuse inventory

- `GenerationBudgetLedger.reserve` and the run `ExitStack` (existing).
- `make_faker`, `AVAILABLE_LOCALES` in `internal/faker_setup.py` (existing).
- `pyarrow.Buffer.parent` and `Array.buffers()` (library).
- `tracemalloc`, `ast` (stdlib).

## Frozen contracts

N/A: every name touched is internal (`generation.pool`, `internal.faker_setup`);
`DEFAULT_GENERATE_LOCALE` moves to `internal.faker_locale`; it had no public import path.

## Slices

One slice on PR #813: tests first (red on `752ce7a65`), then the fix, then the merge of
`origin/main`.

## Pre-mortem

- The bound is too tight on another OS or Python: the sweep test fails in CI and names the
  locale; raise that table row.
- The new charge refuses small runs that passed before: the en_US charge drops from 16 MiB
  to 11 MiB, so no existing ceiling test should start failing; an `it_IT` run needs about
  79 MiB of headroom, which is the measured cost.
- A new Faker-opening route is added later and skips the walk: the spy test fails when that
  route is covered by a probe config; a route with no probe is the known gap.
