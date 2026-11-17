Status: plan

# F10: lock envelope remainder, synthetic probe, CLI environment report and fleet comparison (roadmap row 78)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-17. Revision 3 (Dennis r1 GO-WITH-FIXES H1 to
L12 in revision 2; Codex r1 NO-GO items 1 to 4 in revision 3; record in section 20; owner answers
OQ-1 to OQ-4 taken as recommended).
Scope: engine slice 78-E2, the engine release and CLI repin that carry it (a row 76 RD-n stop),
then CLI slice 78-C1.

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1
and R2 tiers), `development-loop.md` (PLAN: guarantee, size, design notes, choke point, Placement,
Established solutions), `feature-dev.md`, `api-and-compatibility.md` (versioned formats, additive
fields), `security.md`, `architecture.md` (Layout), `testing.md` (Test depth, full-suite triggers),
`release-and-rollback.md`, `documentation.md`, `workspace-and-vcs.md` (Commit messages),
`reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `catalogs/recurring-defects.md`
(classes 1 to 11); engine `CLAUDE.md`, `CODEMAP.md` "Where Things Go" (`CODEMAP.md:250`) and the
support row (`CODEMAP.md:125`), `.importlinter`, `docs/compatibility-contract.md` section 3.1,
`docs/frozen-surfaces.md`; CLI `CODEMAP.md` "Command module" row, `src/decoy/cli/exit_codes.py`;
the V1 bar (only a function break, data loss, a non-admin value leak or cascading design blocks
V1); the V1 threat model (accidental leaks only); owner rules: CLI V1 first, platform parked, no
new features beyond the row.

Bases: engine `origin/main` `b3206c042` (#619), CLI `origin/main` `f7deac1e3` (#293, pins engine
0.27.0; refreshed in revision 3, every CLI line cited below re-checked there). Line numbers below
are from those heads.

## 1. Source and what is already done

Source spec, found in this order:

1. MASTER F10 "Enforced version locks and fleet compatibility inventory" (wiki,
   `10-Projects/decoy/business/market-expansion-specs/MASTER-Decoy-Feature-Specification.md`,
   section F10). Gaps it names: no portable lock envelope, no synthetic probe, no CLI environment
   report, no fleet comparison before an upgrade.
2. Platform roadmap Phase 2 Track A F10 and the 2026-10-30 reconciliation: `lock/v1` has
   `key_version` from the first schema (F09 needs it); `runtime_identity` should include Faker and
   provider and pool digests; the platform gate should check the envelope; the envelope records
   the pinned dependency set (G12).
3. The CLI release-chain plan, `C:plan/release-chain` `7b91cf0`,
   `docs/plans/2026-11-16-release-chain.md` section 7 (review rounds 1 and 2 resolved). It replaced
   the parked platform source plan (`2026-10-24-upgrade-determinism-gate.md`) for the engine and
   CLI halves, split the row into 78-E1, 78-E2 and 78-C1, and recorded OQ-2 (no run-time refusal
   in V1), OQ-3 (`runtime_identity` unchanged) and OQ-9 (no `canon` or `generator_logic` field).

What has merged, and so is not planned again here:

- **78-E1, the lock envelope, MERGED** (engine #618, `17c50cb9f`, 2026-11-16, after the `v0.27.0`
  tag, so not yet in a release). `decoy_engine.support` exports `RuntimeLock`,
  `build_runtime_lock`, `read_runtime_lock`, `compare_runtime_locks` and `LockDifference`
  (`src/decoy_engine/support/_runtime_lock.py:290`, `:310`). `lock/v1` carries `engine`, `numpy`,
  `pandas`, `pyarrow`, `python`, `seed_protocol`, `tz`, `compat_phase`, `faker`,
  `providers_digest`, `data_digest`, `dependencies` and a nullable `key_version` label
  (`_runtime_lock.py:127`). The one label rule is `keyprovider.is_key_version_label`. The format
  is in contract 3.1 and the frozen-surface map, with a corpus sample
  (`tests/integration/compat_corpus/runtime-lock/lock-v1.json`).
- E1 divergences from the release-chain plan, recorded in PR #618: the names are exported from
  `decoy_engine.support` and `decoy_engine.keyprovider`, not the root facade (held at 600 lines);
  `lock/v1` has no `probe` field yet; the engine support row (`CODEMAP.md:125`) still says the
  package holds only the bundle types.

The real remainder, which this plan covers:

- **78-E2 (engine):** the synthetic probe, its golden, a `probe` field in `lock/v1`, and the
  dependency-matrix cell.
- **Release and repin:** an engine release that carries E1 and E2, and the CLI repin to it. This
  is a row 76 RD-n stop, not a new slice.
- **78-C1 (CLI):** `decoy env report` (the environment report) and `decoy env compare` (the fleet
  comparison, in file form).

This plan supersedes release-chain section 7 for 78-E2 and 78-C1 only. Deltas from it: the `probe`
field is optional on read (OQ-1); the engine exports `probe_status()` so the CLI holds no golden;
the report nests the engine lock whole (OQ-2); `env compare` refuses duplicate labels.

Roadmap note: row 78 still says NOT STARTED although E1 merged. The roadmap update that records E1
and points at this plan is a docs-only CLI change after this plan is gated.

## 2. Guarantee and non-goals

### The guarantee (pinned)

For one installed engine, `build_runtime_lock()` returns the same canonical bytes in every process
on hosts with the same installed versions and shipped data, and its `probe` field is a SHA-256 over
fixed public inputs run through the engine's Python reference code for the keyed hash, FF1 and the
seeded Faker pool. A host whose probe digest differs from the engine's golden for the current seed
protocol is reported as `mismatch`, never as `ok`. The probe does not cover the native companion
route; that route is covered by the companion's own known-answer vectors (`HASH_KAT`, `FPE_KAT`),
whose result the report carries as `native_selfcheck`, and `env compare` shows both. No lock, report, comparison line or error carries a key, a key check
value, a cell value, a host name or an absolute path. `decoy env compare` names every field that
differs between two or more reports and exits non-zero when any does.

### Non-goals

- A run-time refusal when the host differs from a saved lock (release-chain OQ-2: no for V1; the
  CLI has no project lock file and adding one is a new feature).
- Changing `runtime_identity()` (release-chain OQ-3), so no saved pinned plan changes fingerprint.
- `canon` and `generator_logic` fields (release-chain OQ-9). The probe covers both code paths.
- The platform fleet view, platform admission and worker inventory. The platform is parked; the
  fleet comparison in V1 is `decoy env compare` over report files the operator collects.
- Any network fetch or upload of a report. The operator copies files.
- Frozen synthetic pools that travel with the lock (MASTER F10 "where appropriate"). The
  `data_digest` and the probe name a changed pool; shipping pools is V2.
- Proof of output equivalence. A matching probe supplements the version fields; it does not prove
  that every config masks the same (MASTER F10 expectation).
- `decoy doctor` changes. `doctor` stays the dependency health check.
- Hostile tampering with a report file. A report is a diagnostic, not evidence; signing is F33.

## 3. Established solutions

Searches run 2026-11-17: web search "power-on self test known answer test cryptographic library
runtime self-check digest"; the codebase for `runtime_identity`, `lock/v1`, `FF1_KEY_LABEL`,
`derive(`, `PoolBuilder`, `seed_instance`, `native_companion_status`, `HASH_KAT`; qmd for "F10 lock
envelope" and "lock envelope key_version synthetic probe"; the release-chain plan section 4
(searched 2026-11-16).

| Problem | Established answer | Followed here |
|---|---|---|
| Record the resolved inputs of an environment | Lock files of resolved inputs (`uv.lock`, Nix `flake.lock`) | Yes, E1 (merged) |
| Show that a runtime reproduces known output | Known-answer tests run at load or on demand: Libgcrypt runtime self-tests (fixed inputs and keys, compare to expected digests), Mozilla NSS power-up self-tests, OpenSSL FIPS module KATs, FIPS 140 "independent known-answer test" per algorithm. The engine already does this for the native crypto ABI (`HASH_KAT` in `execution/native/_crypto_ext.py`) | Yes. The probe is one on-demand KAT over the shipped Python hash, FF1 and seeded pool paths, with one expected digest per seed protocol |
| Compare environments across hosts | Diff environment reports (`conda env export`, `pip freeze` diffs) rather than enforce them | Yes, `decoy env compare` |
| Additive field in a versioned document | Tolerant reader that ignores unknown fields and treats a newer optional field as absent | Yes, `probe` is optional on read (OQ-1) |

Custom code that remains: the probe inputs and the golden table, the CLI command wiring, and the
report model. Each is small and specific to Decoy.

## 4. Behavior

### 4.1 The probe (78-E2)

`src/decoy_engine/support/_probe.py`:

- `run_probe() -> str`: 64 lowercase hex characters. It runs three fixed parts and returns
  `sha256(canonical_json_bytes({"hash": [...], "fpe": [...], "pool": [...]}))`. Its engine imports
  are lazy, inside the function, so importing `decoy_engine.support` stays cheap.
  1. Keyed hash: for each of 8 fixed ASCII inputs, `derive(PROBE_KEY, "probe/hash",
     canonicalize_derive_source(value)).hex()` (`determinism/_derive.py:260`,
     `kernel/__init__.py:8`), the same core the `hash` strategy uses.
  2. FF1: for each of 4 fixed digit strings of 6 to 10 digits (FF1 needs at least 6 numerals at
     radix 10), `fpe_encrypt_value(value, derive(PROBE_KEY, "probe/fpe", FF1_KEY_LABEL),
     "0123456789", build_ff1_tweak(FF1_TWEAK_SCOPE_COLUMN, "probe.fpe"))`
     (`transforms/fpe.py:152`, `:155`, `:468`).
  3. Seeded Faker pool: `PoolBuilder(providers_v2.get_default_registry()).build("person_first_name", size=16,
     job_seed=PROBE_JOB_SEED, locale="en_US")` (`generation/pool/_builder.py:163`), then the pool
     values in order. The pool build seeds Faker with `seed_instance`
     (`providers_v2/_faker_adapter.py:214`); `person_first_name` maps to Faker's `first_name`
     (`providers_v2/_faker_adapter.py:50`).
- Custom providers: `_V2_CUSTOM_PROVIDERS` is process-global (`providers_v2/_faker_adapter.py:84`).
  A probe run in a process where a custom provider overrides `person_first_name` would digest the
  custom function, not the shipped one. `run_probe` refuses that case with `ProbeError` before any
  draw. It asks through a deliberately public accessor: the existing `_v2_custom_provider_names()`
  (`providers_v2/_faker_adapter.py:276`) is renamed to `custom_provider_names() -> frozenset[str]`,
  its one caller (`tests/unit/providers_v2/test_registry.py`) is updated, and it is exported from
  `providers_v2/__init__.py` `__all__`. One accessor for that state, no second copy.
  The probe imports it from `decoy_engine.providers_v2`, never from `_faker_adapter`. The registry
  offers no default-only view today, so refusal is the smaller change.
- `PROBE_KEY` is `sha256(b"decoy-probe/v1")`, a public constant. `PROBE_JOB_SEED` is its first 8
  bytes. The probe never reads a key provider, an environment variable or a file.
- Module contract: no NumPy or pandas distribution draw, no file, socket or subprocess.
- `PROBE_GOLDEN: Mapping[int, str]` maps `SEED_PROTOCOL_VERSION` to the expected digest. Today one
  row, for protocol 7. The golden changes only in a PR that bumps the seed protocol or repins
  Faker, and that PR's changelog fragment names the change (OQ-4). It complements, and does not
  replace, the Faker determinism digests in `scripts/faker-determinism/golden_digests.json`: those
  pin many providers in a script check, the probe pins one small answer every host can compute.
- `run_probe` raises `ProbeError` itself on any failure inside a part: new reason
  `runtime/probe_failed` (since=UNRELEASED), fixed text, raised outside the handler so `__cause__`
  and `__context__` are None.
- `probe_status(digest: str | None) -> Literal["ok", "mismatch"]`: a pure function of the digest.
  `mismatch` when the digest is `None`, the protocol has no golden row, or the digest differs. The
  probe runs once per report: the CLI calls `build_runtime_lock()` (which runs the probe) and
  derives `probe_status` from `lock.probe`.

### 4.2 The `probe` field in `lock/v1` (78-E2)

- `RuntimeLock` gains `probe: str | None = None`, spec `_DIGEST`, placed last in `_FIELDS`
  (`_runtime_lock.py:127`) with `required=False`. `build_runtime_lock()` always sets it from
  `run_probe()`.
- Optional-and-omitted is a property of the field, stated once. `_FIELDS` entries become a small
  frozen `_Field(name, spec, required=True)` descriptor; `probe` is the one entry with
  `required=False`. `to_dict`, `from_dict` and `compare_runtime_locks` all read the flag; none of
  them names `probe`. Read: a missing optional field reads as `None` (`from_dict`,
  `_runtime_lock.py:202`, fills it before `ObjectSpec.load`); a missing required field is still
  refused. Write: `to_dict` omits an optional field whose value is `None`. Compare: it compares the
  attribute values, so `None` against a digest is a difference. So a lock written by an engine
  with E1 but not E2 reads, and rewrites to the same bytes, whatever the release order (OQ-1).
- An optional field present as JSON `null` is refused, so there is one spelling of "no probe". The
  field spec is the plain `_DIGEST`, not `NullableSpec`, which gives this refusal for free.
- `compare_runtime_locks` names `probe` like any other field; `None` against a digest is a
  difference.
- The existing corpus sample `lock-v1.json` is not edited and still rewrites byte-identically. A
  second hand-written sample, `lock-v1-probe.json`, carries a `probe` digest.
- Contract 3.1 and the frozen-surface row for `lock/v1` change one sentence each: the reader
  "refuses a missing field, except `probe`, which is optional and omitted when absent".

### 4.3 CLI environment report (78-C1)

`decoy env report [--json] [--out FILE] [--label NAME] [--key-version LABEL]`:

- Builds `decoy-env-report/v1`: `{"schema": "decoy-env-report/v1", "label", "cli_version",
  "target", "native_selfcheck": {"present", "ok", "reason"}, "probe_status", "lock": <lock/v1
  object>}`. The engine lock is nested whole (OQ-2), so the CLI holds no second field list.
- `lock` comes from `build_runtime_lock(key_version=...)`; `probe_status` is
  `probe_status(lock.probe)`, so the probe runs once.
  `cli_version` from the installed `decoy-cli` metadata; `target` from
  `decoy.distribution.targets.detect_target()` (null when unknown); `native_selfcheck` from the
  existing safe reader `_companion_report()` (`src/decoy/cli/info.py:72`), keeping only `present`,
  `ok` and `reason`.
- `--label` full-matches `[A-Za-z0-9][A-Za-z0-9._-]{0,31}`, default `host`; anything else exits 1
  with fixed text that does not repeat the value.
- `--key-version` is checked with the engine's `is_key_version_label` before any work; a bad label
  exits 1 with fixed text.
- Human mode prints one line per field. `--json` prints the complete report. `--out FILE` writes
  the JSON through `decoy._atomic.write_local_target(path, data, WriteMode.REPLACE)`
  (`src/decoy/_atomic.py:199`), the writer for a path the user chose. `write_atomic` is for
  program-controlled portable names and would refuse names that are valid here (a leading dot, a
  space, non-ASCII).
- Exit 0 when `probe_status` is `ok`. A mismatch prints `probe: MISMATCH` in human mode, writes the
  complete report in either mode, and exits 3 (`EXIT_RUNTIME`, `src/decoy/cli/exit_codes.py:66`;
  OQ-3). A `ProbeError` prints `probe: failed (runtime/probe_failed)`, writes no report and exits
  3. `ProbeError` and an `AtomicWriteError` from the `--out` write go through the one
  exception-to-exit map, `exit_code_for` (`src/decoy/cli/exit_codes.py:163`). Both reach its final
  "everything else is 3" arm today: `ProbeError` is a `DecoyError` whose code is not a capacity
  code, and `AtomicWriteError` is matched by no earlier arm. No new arm is needed; AT-C1-9 pins
  both results so a later arm cannot move them. The refusal line prints `describe(exc)`
  (`src/decoy/_atomic.py:214`), which holds the code and OS reason, never the path. The env
  package holds no exit map of its own.

### 4.4 Fleet comparison (78-C1)

`decoy env compare A.json B.json [C.json ...] [--json]`:

- Reads 2 to 64 report files. Each is read once into memory with a 64 KiB cap, parsed by the strict
  `decoy-env-report/v1` reader, and its `lock` member by the engine's `RuntimeLock.from_dict`.
  Duplicate labels exit 1, so each line names one host. The parse boundary catches `ValueError`
  (the engine's `runtime_lock_refused:<check>` and the CLI reader's refusals) and `MaskSecretError`
  (a bad `key_version` inside a report) and exits `EXIT_USAGE` with fixed text naming the file's
  position, never its content.
- Prints one line per differing field: `<field>: <label>=<value>, <label>=<value>, ...`. Lock fields
  come from `compare_runtime_locks` and keep their engine names (`faker`, `probe`, `data_digest`);
  the CLI fields compared are `cli_version`, `target`, `native_selfcheck` and `probe_status`. So a
  host whose Python path matches but whose native companion fails its KATs shows up as a
  `native_selfcheck` difference.
  `label` is never compared.
- `--json` prints `{"reports": <n>, "differences": [{"field", "values": {<label>: <value>}}]}`.
- Exit 0 when all match, 4 (`EXIT_FINDINGS`, `exit_codes.py:74`) when any field differs, 1 when a
  file is missing, oversize, not JSON or not a valid report, or fewer than two files are given.

## 5. Failure modes

| Id | Failure | Cause | Guard | Test |
|---|---|---|---|---|
| FM-1 | Probe digest differs between two identical hosts | unordered input (dict order, set order, hash seed) | canonical JSON over lists in fixed order | AT-E2-2 |
| FM-2 | Probe reads the user's key | probe wired to a key provider | public `PROBE_KEY` constant; no provider import | AT-E2-5 |
| FM-3 | Probe passes on a host whose Faker draws changed | pool part dropped or not seeded | golden covers the pool part | AT-E2-3 |
| FM-4 | Probe slow or does I/O | file read, network, large pool | 16-value pool, I/O guard test | AT-E2-6 |
| FM-5 | A lock written before E2 cannot be read, or rewrites differently, after E2 | `probe` made required, or `None` written as `null` | absent reads as `None`, `None` omitted on write | AT-E2-7, AT-E2-10 |
| FM-13 | Probe digests a user's custom provider | process-global `_V2_CUSTOM_PROVIDERS` overrides `person_first_name` | refuse with `ProbeError` | AT-E2-13 |
| FM-14 | Probe says `ok` while the native route is broken | probe covers the Python reference path only | report carries `native_selfcheck` (companion KATs); compare shows both | AT-C1-5, AT-C1-2 |
| FM-15 | `--out` refuses a valid user file name or a failed write exits with the wrong code | `write_atomic` used for a user path; `AtomicWriteError` mapped by hand | `write_local_target`; exit through `exit_code_for` | AT-C1-9 |
| FM-6 | Probe exception text reaches the user | raw `str(exc)` | `ProbeError` with fixed text, no context | AT-E2-8, AT-C1-6 |
| FM-7 | Protocol bump with no golden row reports `ok` | default to ok | missing row is `mismatch` | AT-E2-4 |
| FM-8 | Report carries a path or host name | companion `cause` or `detail`, host name as default label | three companion fields only; default label `host` | AT-C1-4, AT-C1-5 |
| FM-9 | Report reader accepts a wrong type | loose JSON read | strict reader, engine reader for `lock` | AT-C1-8 |
| FM-10 | Compare hides a difference | CLI keeps its own lock field list | `compare_runtime_locks` for every lock field | AT-C1-2 |
| FM-11 | Compare exits 0 on one file | count not checked | at least two files, else exit 1 | AT-C1-3 |
| FM-12 | Golden edited to make a red test green | builder launders a divergence | golden change only with a protocol bump or Faker repin, named in the changelog; diffed at the gate | gate check |

## 6. Design notes and choke points

- New structure: one engine module in an existing package, one CLI command sub-package. Principles:
  one place per fact. Versions come from `runtime_identity()`, digests go through `_canonical`, the
  label rule is `keyprovider.is_key_version_label`, the lock field list is
  `_runtime_lock._FIELDS`, the probe answer is `PROBE_GOLDEN`, the ok-or-mismatch rule is
  `probe_status`. The CLI reads all of them through
  `decoy_engine.support` and `decoy_engine.keyprovider` and copies none.
- Choke point: the lock field list. The CLI compares lock fields only through
  `compare_runtime_locks`; AT-C1-2 turns red when a CLI-held list misses `probe`.
- Why `support/` for the probe: it imports `determinism`, `kernel`, `transforms`, `generation` and
  `providers_v2`, all below tier 1 in `.importlinter`; `support` is tier 1 and already holds the
  lock. No new top-level package (the engine root is at its fan-out cap), no new ignore line, and
  nothing in `execution/`. `support` grows from 4 to 5 modules.
- Public names only (defect class 6): `decoy_engine.determinism.derive`,
  `decoy_engine.kernel.canonicalize_derive_source`, `decoy_engine.transforms.fpe`
  (`FF1_KEY_LABEL`, `build_ff1_tweak`, `fpe_encrypt_value`, `FF1_TWEAK_SCOPE_COLUMN`),
  `decoy_engine.generation.pool.PoolBuilder` and `decoy_engine.providers_v2`
  (`get_default_registry`, the renamed `custom_provider_names`).
- Boundary sentry: new `tests/sentry/test_runtime_lock_public_imports.py` walks the AST of
  `support/_probe.py` and `support/_runtime_lock.py` and fails on any import whose dotted path has
  a segment starting with `_` below another engine package (for example
  `decoy_engine.providers_v2._faker_adapter`). Imports inside `decoy_engine.support` and the
  engine-root shared module `decoy_engine._canonical` are allowed. Scope is the two F10 modules:
  `support/__init__.py` already imports `execution.native._route_decline_codes` (F32), which is a
  V2-LOG item (section 19), not something this row widens or hides.
- Choke point for optional fields: the `_Field.required` flag. A second hand-written `probe`
  branch in `to_dict`, `from_dict` or compare is the bypass; AT-E2-15 flips the flag and expects
  the corpus cells to go red, which a hand branch would not do.
- The support no-network sentry (`tests/sentry/test_support_no_network.py`) already covers the new
  module.
- Platform coverage: the cross-Python probe check runs on Linux CI (`ci.yml` `import-smoke`,
  3.11.9 and 3.12.7, `.github/workflows/ci.yml:64`); macOS is covered by the two-host QA run
  (AT-C1-11); Windows is not checked by this row. Windows is in V1, so the Windows chain (rows 6
  and 89) adds the same step to its Windows CI job; recorded in section 19.
- CLI: new sub-package `src/decoy/cli/env/` (the flat `src/decoy/cli/` is pinned at 29 direct
  modules by `tests/sentry/layout/test_package_fanout.py`).
  Registered in `src/decoy/__main__.py` beside `doctor` (`__main__.py:288`), panel "Start".
- Size: engine 6 production files, about 360 lines, 4 public names (`run_probe`, `probe_status`,
  `ProbeError`, `providers_v2.custom_provider_names`); CLI 5 production files, about 520 lines, 2
  commands.

## 7. Value-free rules

- Allowed in a lock or report: library versions, digests, the seed protocol integer, the phase
  token, the target triple, the companion reason code, the operator's label, the key version label.
- Never: a key, a key check value (F09 KCV or the resume fingerprint `key_check`), a cell value, a
  host name, a user name, an absolute path, exception text.
- Every refusal (bad label, bad key version, bad report, probe failure) prints fixed text and a
  reason code, never the input.

## 8. Acceptance tests (red first)

Each test is written first and must fail on the base head for the reason given. Each names the
mutation that must turn it red. A builder may add tests; none of these may be weakened.

### 78-E2, engine (`tests/unit/support/test_probe.py`, new cells in `tests/unit/support/test_runtime_lock.py`)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-E2-1 | `run_probe()` returns 64 lowercase hex and equals `PROBE_GOLDEN[SEED_PROTOCOL_VERSION]`; `probe_status(run_probe()) == "ok"`; `probe_status(None) == "mismatch"` | module does not exist | return a constant digest |
| AT-E2-2 | `run_probe()` in two subprocesses with different `PYTHONHASHSEED` returns equal digests | module does not exist | build the digest from a `set` of outputs |
| AT-E2-3 | Changing one byte of the hash namespace, of the FF1 tweak identity, or of the pool `job_seed` each changes the digest (three cells) | module does not exist | drop the pool part from the digest input |
| AT-E2-4 | Patched `SEED_PROTOCOL_VERSION` with no golden row gives `status == "mismatch"`; a patched golden gives `mismatch` | module does not exist | treat a missing row as `ok` |
| AT-E2-5 | With a seeded mask secret in the environment and a configured key provider, `run_probe()` is unchanged and no key-provider function is called (spy) | module does not exist | derive `PROBE_KEY` from the resolved mask key |
| AT-E2-6 | `run_probe()` opens no file and no socket (patched `open` and `socket.socket` raise) | module does not exist | read a codesets parquet inside the probe |
| AT-E2-7 | `build_runtime_lock().probe == run_probe()`; the existing `lock-v1.json` sample (no `probe`) reads with `probe is None` and rewrites byte-identically; the new `lock-v1-probe.json` reads and rewrites byte-identically; a lock with `"probe": null` is refused; `compare_runtime_locks` names `probe` when one side is `None` | `probe` field does not exist | write `None` as `"probe": null` |
| AT-E2-8 | A probe part patched to raise `ValueError("/home/x/secret")` makes `run_probe()` raise `ProbeError` with code `runtime/probe_failed`, fixed message, `__cause__` and `__context__` None, and the marker absent from `str(err)` | `ProbeError` does not exist | `raise ProbeError(...) from exc` |
| AT-E2-9 | `probe` refuses `True`, an integer, 63 hex, uppercase hex and `"<64 hex>\n"` on write and on read | `probe` field does not exist | use `$` instead of `fullmatch` |
| AT-E2-10 | Edit list for the merged E1 cells in `tests/unit/support/test_runtime_lock.py`, each red before E2 lands its half and green after: `:71` (`test_lock_has_exactly_the_declared_fields_and_round_trips`) gains `probe` in the expected key set; `:398` (`test_an_added_field_under_lock_v1_is_ignored`) uses another added-field name (`added_later_2`) in place of `probe`; `:406` (`test_the_hand_written_corpus_sample_reads_and_rewrites`) stays unedited and must still pass (the symmetric write rule); a new cell pins that a `probe` key is read, not ignored. No other E1 cell is edited, including `test_each_source_changes_exactly_its_named_field` | E1 cells fail once `probe` is written; the new cell fails before | treat `probe` as an ignored added field |
| AT-E2-11 | `.github/workflows/ci.yml` job `import-smoke` (3.11.9 and 3.12.7) runs one step after the import, `python -c` that asserts `probe_status(run_probe()) == "ok"`; a sentry reads `ci.yml` and finds the step in that job | step does not exist | remove the step |
| AT-E2-12 | Import-layer sentry passes with no new ignore line; `runtime/probe_failed` is in the reason catalog with since=UNRELEASED | guard and catalog | add an ignore line |
| AT-E2-13 | With a custom provider registered for `person_first_name` through the public `register_faker_provider_v2` (fixture removes it after), `run_probe()` raises `ProbeError` before any draw; the custom function is never called (spy); `providers_v2.custom_provider_names()` returns the name while registered and not after | module and accessor do not exist | skip the custom-provider check |
| AT-E2-14 | `tests/sentry/test_runtime_lock_public_imports.py`: no import in `support/_probe.py` or `support/_runtime_lock.py` has a `_`-prefixed segment below another engine package; a planted fixture module with `from decoy_engine.providers_v2._faker_adapter import _v2_custom_provider_names` is flagged | sentry does not exist | import the test-only `_v2_custom_provider_names` from `_faker_adapter` |
| AT-E2-15 | Descriptor mutation: flipping `required` on the `probe` entry to `True` turns the `lock-v1.json` corpus read red; flipping `required=False` on `engine` makes the missing-field cell red; no function in `_runtime_lock.py` other than the `_FIELDS` table contains the string `"probe"` (AST cell) | descriptor does not exist | add `if name == "probe"` in `to_dict` |

### 78-C1, CLI (`tests/unit/cli/env/`, `tests/e2e/env/test_env_commands.py`)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-C1-1 | `decoy env report --json` validates against `docs/schemas/decoy-env-report-v1.schema.json`; `lock` reads with the engine `RuntimeLock.from_dict`; exit 0 | command does not exist | drop `lock.probe` from the report |
| AT-C1-2 | Two reports that differ only in `lock.faker`: `decoy env compare` prints exactly one line naming `faker` and both labels, exit 4; identical reports exit 0; three reports where one differs in `probe` name `probe` once | command does not exist | compare a CLI-held copy of the lock field list without `probe` |
| AT-C1-3 | `env compare` with one file, a missing file, a truncated file, a 65 KiB file, or a duplicate label: each exits 1 with fixed text that does not repeat file content | command does not exist | accept one file and exit 0 |
| AT-C1-4 | Report and compare output (stdout, stderr, `--json`, `--out` file) contain no `socket.gethostname()`, no `tmp_path` string and no home path | command does not exist | default `--label` to the host name |
| AT-C1-5 | A patched `native_companion_status()` carries a seeded path marker in `cause` and `abi_actual`: the report shows `ok: false` and a reason code, and the marker is absent from every output | command does not exist | copy `abi_actual` into the report |
| AT-C1-6 | Probe golden patched wrong: human mode prints `probe: MISMATCH`, `--json` prints the complete report with `probe_status: "mismatch"`, both exit 3; probe patched to raise: exit 3, fixed line, no report written | command does not exist | exit 0 on mismatch |
| AT-C1-7 | `--label` values `"a\n"`, `""`, 33 characters, `"a b"` and `--key-version` values `"v1\n"`, `""`, 65 characters, `"a/b"` exit 1 without echoing the value | command does not exist | `re.match` instead of `fullmatch` |
| AT-C1-8 | Strict `decoy-env-report/v1` reader matrix on write and read: `cli_version`, `target`, `label`, `probe_status` refuse wrong types; `native_selfcheck.present` and `.ok` refuse `0`, `1`, `"true"`, `null` and a list; `probe_status` refuses every token but `ok` and `mismatch`; an unknown top-level key and a wrong `schema` tag are refused; a report whose `lock.key_version` is `"a/b"` makes `env compare` exit 1 with fixed text (the engine's `MaskSecretError` is caught at the parse boundary) | command does not exist | accept `1` as `True` in `native_selfcheck.ok`; let `MaskSecretError` escape |
| AT-C1-9 | `--out FILE` writes through `write_local_target(..., WriteMode.REPLACE)` (spy); an existing file is replaced whole; names `.env-a.json`, `env report.json` and `rapport-hôte.json` write fine; a patched writer raising `AtomicWriteError` exits 3, prints the `describe` text without the path, and leaves no partial file; `exit_code_for(AtomicWriteError("x")) == 3` and `exit_code_for(ProbeError(...)) == 3` | command does not exist | write with `write_atomic` (the three names are refused); map `AtomicWriteError` to 1 |
| AT-C1-10 | `tests/unit/test_cli_surface.py` lists `env report` and `env compare`; the `--json` snapshot rows exist; the CLI fan-out sentry passes with the new CODEMAP row | guard | omit the CODEMAP row |
| AT-C1-11 | QA INST-18 on two hosts (a Linux VM and the Mac): reports from both compare and name each differing field | run at QA | none (QA) |

## 9. Goldens, pins and sentries that move

- New golden: `PROBE_GOLDEN[7]` in `support/_probe.py`, computed once on the build head from the
  locked environment and checked in both `ci.yml` `import-smoke` cells.
- New corpus sample: `tests/integration/compat_corpus/runtime-lock/lock-v1-probe.json`. The
  existing `lock-v1.json` is not edited.
- Three merged E1 test cells change, listed in AT-E2-10. Each change follows the new contract
  sentence; none loosens an assertion.
- No determinism golden, cap, ceiling, pin, sentry baseline or allowlist is raised. The CLI
  `src/decoy/cli/` fan-out pin stays at 29; `env/` is a sub-package.
- The CLI engine pin moves forward at the RD-n stop that carries E2 (row 76), with the repin
  checklist.

## 10. Placement (checked against engine `CODEMAP.md:250` and the CLI "Command module" row)

| Item | Goes in | Map line and neighbor |
|---|---|---|
| Probe and golden | engine `src/decoy_engine/support/_probe.py` (new) | "Support bundles", `src/decoy_engine/support/_<concern>.py`; tier 1 beside `_runtime_lock.py`; not `execution/` (frozen for new top-level files) |
| `probe` lock field and `_Field` descriptor | engine `src/decoy_engine/support/_runtime_lock.py` | existing module |
| `custom_provider_names` | engine `src/decoy_engine/providers_v2/_faker_adapter.py`, exported from `providers_v2/__init__.py` | the existing `_v2_custom_provider_names` renamed in place, beside `_V2_CUSTOM_PROVIDERS`, the owner of that state |
| Boundary sentry | engine `tests/sentry/test_runtime_lock_public_imports.py` | beside `tests/sentry/test_support_no_network.py`, the other support sentry |
| `ProbeError` reason | engine `src/decoy_engine/reasons/runtime/_part2.py` | beside `KEY_VERSION_INVALID` |
| Exports | engine `src/decoy_engine/support/__init__.py` | existing facade; not the root (held at 600 lines) |
| Support row text | engine `CODEMAP.md:125` | update to name `_runtime_lock.py` and `_probe.py` |
| Engine tests | `tests/unit/support/test_probe.py` | "Support bundles" tests |
| Workflow step | `.github/workflows/ci.yml`, job `import-smoke` (`ci.yml:64`) | existing job; not `dps-dependency-matrix.yml`, which runs on schedule and dispatch only and gates no merge |
| Env commands | CLI `src/decoy/cli/env/__init__.py` (Typer group), `_report.py`, `_compare.py`, `_model.py` (strict report writer and reader), all new | "Command module": new commands in a named sub-package, like `setup/` and `library/`; new CODEMAP row |
| Registration | CLI `src/decoy/__main__.py` | beside `doctor`, `__main__.py:288` |
| Report schema | CLI `docs/schemas/decoy-env-report-v1.schema.json` | beside `decoy-ci-v1.schema.json`; row in `docs/release/frozen-surfaces.md` |
| CLI tests | `tests/unit/cli/env/`, `tests/e2e/env/` | mirror `src/`; new folders, not the flat `tests/e2e/` |

## 11. Reuse inventory

| Need | Reused | Where |
|---|---|---|
| Versions and digests | `build_runtime_lock`, `runtime_identity` | `support/_runtime_lock.py:290` |
| Canonical bytes | `canonical_json_bytes` | `_canonical/_json.py:141` |
| Keyed hash core | `derive`, `canonicalize_derive_source` | `determinism/_derive.py:260`, `kernel/__init__.py:8` |
| FF1 | `fpe_encrypt_value`, `build_ff1_tweak`, `FF1_KEY_LABEL` | `transforms/fpe.py:152`, `:155`, `:468` |
| Seeded Faker pool | `PoolBuilder.build` | `generation/pool/_builder.py:163` |
| Strict field specs | `ObjectSpec`, `ShapedSpec`, `attempt` | `_canonical/_strict_spec.py:188` |
| Label rule | `is_key_version_label` | `keyprovider.py` (E1) |
| Lock comparison | `compare_runtime_locks` | `support/_runtime_lock.py:310` |
| Companion facts | `_companion_report` | CLI `src/decoy/cli/info.py:72` |
| Target | `detect_target` | CLI `src/decoy/distribution/targets.py:43` |
| User-path write | `write_local_target`, `WriteMode.REPLACE`, `describe` | CLI `src/decoy/_atomic.py:199`, `:214` |
| Custom-provider names | `_V2_CUSTOM_PROVIDERS` behind a new public accessor | `providers_v2/_faker_adapter.py:84`, `:277` |
| Exit codes | `EXIT_USAGE`, `EXIT_RUNTIME`, `EXIT_FINDINGS` | CLI `src/decoy/cli/exit_codes.py:49`, `:66`, `:74` |

## 12. Frozen contracts touched

All additive.

- Engine `lock/v1`: new `probe` field, optional on read and omitted on write when absent. Contract
  3.1 "refuses a missing field" gains "except `probe`"; the frozen-surface row matches; the new
  corpus sample pins the read rule.
- Engine public names: `run_probe`, `probe_status`, `ProbeError` in
  `decoy_engine.support.__all__`, and `custom_provider_names` in `decoy_engine.providers_v2.__all__`,
  each in one Public names row of `docs/frozen-surfaces.md`.
- Engine reason `runtime/probe_failed`, since=UNRELEASED.
- CLI command set: `decoy env report`, `decoy env compare`; `docs/cli-reference.md` and
  `tests/unit/test_cli_surface.py`.
- CLI `--json` shapes: `env report` (the schema file) and `env compare` (a snapshot row).
- CLI `docs/schemas/decoy-env-report-v1.schema.json` with its frozen-surface row.
- Exit codes: no new code. `env report` uses 0, 1, 3; `env compare` uses 0, 1, 4.

## 13. Class table

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Fixed refusal text; three companion fields only; label default `host`; `ProbeError` raised outside the handler | AT-E2-8, AT-C1-4, AT-C1-5, AT-C1-7 | copy `abi_actual` or `str(exc)` into output |
| 2 | Cleanup missing on an exit path | `--out` only through `write_local_target`, which stages and replaces in one step; a probe failure writes no report | AT-C1-9, AT-C1-6 | write with `open(..., "w")` |
| 3 | State and concurrency | Probe is a pure function of constants; no cache, no global state | AT-E2-2 | memoize the digest in a module global |
| 4 | Route parity and silent fallback | The probe checks the Python reference path only; the native route is checked by the companion's `HASH_KAT` and `FPE_KAT` and reported as `native_selfcheck`; compare shows both, so a broken native route is never hidden behind a probe `ok` | AT-E2-3, AT-C1-5, AT-C1-2 | drop `native_selfcheck` from the compared fields |
| 5 | Referential integrity | N/A: no table data or relationships are read or written | N/A | N/A |
| 6 | Untrusted producer | Report files from other hosts are untrusted: 64 KiB cap, strict report reader, engine strict lock reader | AT-C1-3, AT-C1-8, AT-E2-9 | accept `1` as `True` |
| 7 | Check then use on a path (TOCTOU) | Compare reads each file once into memory and parses those bytes; no re-open | AT-C1-3 | re-open the file after the size check |
| 8 | Weak tests and overclaimed evidence | Red-first cells with named mutations; golden checked in merge-gating CI; coverage stated per platform (Linux CI, macOS QA, Windows not checked); golden change only with a protocol bump or Faker repin | AT-E2-1, AT-E2-11 | return a constant digest |
| 9 | Behavior-preserving refactor drift | N/A: no refactor in this row; the three E1 cell edits are listed one by one and change no assertion's strength | AT-E2-10 | edit an E1 cell beyond the list |
| 10 | Frozen contract drift | One frozen-surface map; one engine field list, with the optional flag in its descriptor, read by the CLI | AT-E2-7, AT-C1-10, `tests/sentry/release/test_frozen_surface_map.py` | omit the map row |

Class 11 (no raised caps): nothing in this plan raises a cap, ceiling, pin, baseline or allowlist.

## 14. Enumerations

### Exit paths

- `run_probe` returns a digest or raises `ProbeError` (a failed part or a custom
  `person_first_name` provider); `probe_status` returns `ok` or `mismatch` and never raises
  (`src/decoy_engine/support/_probe.py`, new).
- `read_runtime_lock` and `RuntimeLock.from_dict` refuse with `runtime_lock_refused:<check>`
  (`src/decoy_engine/support/_runtime_lock.py:196`, `src/decoy_engine/support/_runtime_lock.py:217`).
- `env report`: 0 ok, 1 bad `--label` or `--key-version`, 3 probe mismatch, probe failure or write
  failure (`src/decoy/cli/exit_codes.py:66`).
- `env compare`: 0 all match, 1 bad input (including a caught `ValueError` or `MaskSecretError`),
  4 a difference (`src/decoy/cli/exit_codes.py:74`).
- `ProbeError` and an `--out` `AtomicWriteError` exit 3 through `exit_code_for`
  (`src/decoy/cli/exit_codes.py:163`), its final arm.

### Routes

- Python reference path: the probe calls `derive` (`src/decoy_engine/determinism/_derive.py:260`),
  `fpe_encrypt_value` (`src/decoy_engine/transforms/fpe.py:468`) and `PoolBuilder.build`
  (`src/decoy_engine/generation/pool/_builder.py:163`). No sequential, chunked or out-of-core
  masking run happens.
- Native companion path: not run by the probe; its own known-answer vectors (`HASH_KAT`,
  `FPE_KAT`, `src/decoy_engine/execution/native/_crypto_ext.py:245`) produce the
  `native_selfcheck` result the report carries.
- CLI: one route per command, in-process; no subprocess.

### FK shapes

N/A: no slice reads, writes or plans table data or relationships.

### Fields

- `lock/v1`: the 13 E1 fields (`src/decoy_engine/support/_runtime_lock.py:127`) plus `probe` (64
  hex; optional on read; omitted on write when absent; `null` refused).
- `decoy-env-report/v1`: `schema`, `label`, `cli_version`, `target` (string or null),
  `native_selfcheck` (`present` bool, `ok` bool, `reason` string or null), `probe_status` (`ok` or
  `mismatch`), `lock` (a `lock/v1` object).
- `env compare --json`: `reports` (int), `differences[]` (`field`, `values` map of label to value).
- `probe_status` return: `ok` or `mismatch`.

### Output surfaces

- Engine: return values and `ProbeError` text only; no log line.
- CLI: stdout (human and `--json`), stderr (refusal lines), the `--out` file. No log file, no
  network.

## 15. Slices, gates and risk

| Slice | Repo | Production files | Count | Lines | Depends on | Risk |
|---|---|---|---|---|---|---|
| 78-E2 | engine | `support/_probe.py` (new), `support/_runtime_lock.py`, `support/__init__.py`, `reasons/runtime/_part2.py`, `providers_v2/_faker_adapter.py`, `providers_v2/__init__.py`; plus the workflow step, the boundary sentry, `CODEMAP.md:125`, the contract 3.1 sentence, frozen-surface rows, the corpus sample and a `changelog.d/` fragment | 6 | about 360 | 78-E1 (merged) | R2 (new public names, a field in a versioned format, a golden) |
| RD-n | engine, CLI | the release and repin under row 76 | n/a | n/a | 78-E2 merged | R1 (row 76) |
| 78-C1 | CLI | `cli/env/__init__.py`, `cli/env/_report.py`, `cli/env/_compare.py`, `cli/env/_model.py` (all new), `__main__.py` (one line); plus the schema file, frozen-surface row, CODEMAP row, `docs/cli-reference.md` and QA INST-18 text | 5 | about 520 | an engine release with E1 and E2, pinned | R2 (new commands, a new versioned format) |

Gates: R2 is Dennis then Codex on the exact head. Tests: T0 per edit, T1 per commit, T2 at the gate,
on the Mac or a VM through `~/bin/vm-run`, never the devbox. Full-suite trigger: E2 changes a
frozen contract (`lock/v1`) and C1 adds a frozen `--json` shape and schema, so each gets one full
suite on its merge head against the saved main baseline. Commit rules: Conventional Commits subject,
no body unless it says why, final line `cam`.

## 16. Dependencies, release and repin points

1. 78-E2 builds now (E1 is merged).
2. The next RD-n engine release after E2 merges carries E1 and E2 (row 76 cadence is daily). If an
   RD-n stop ships E1 before E2 merges, nothing breaks: OQ-1 keeps that release's locks readable.
3. The CLI repin to that release follows the repin checklist (compat, fences, frozen map, doc,
   `PIN_PREFIX`, Dockerfile ARG, catalog).
4. 78-C1 builds on the repinned CLI main.
5. Row 88-P (upgrade preflight, release-chain plan) depends on 78-C1 and will read `probe_status`
   and `compare_runtime_locks` from the staged runtime; nothing here waits on it.
6. F09 (row 79) does not depend on this remainder: the `key_version` field it needs merged in E1.

## 17. Owner questions (answered 2026-11-17: OQ-1 to OQ-4 as recommended)

- **OQ-1. `probe` in `lock/v1`: optional on read (absent reads as null) rather than required?**
  Recommended: optional on read, always written. E1 is unreleased today, but the daily release
  train can ship it before E2 merges; a required field would then break reading those locks under
  the same tag. The existing corpus sample stays untouched.
- **OQ-2. The env report nests the engine lock as one `lock` member, not flat fields?**
  Recommended: nested. The CLI then reads and compares the lock with the engine's own reader and
  `compare_runtime_locks` and keeps no second field list. Field names in compare output stay the
  engine names (`faker`, `probe`).
- **OQ-3. A probe mismatch exits 3 (`EXIT_RUNTIME`), not 4?** Recommended: 3, as the release-chain
  plan says. A mismatch means this runtime does not reproduce the engine's own answer, which is a
  runtime fault, not a data finding. Compare keeps 4 for "hosts differ".
- **OQ-4. The probe golden may change on a Faker repin without a seed-protocol bump?** Recommended:
  yes, in the repin PR only, named in its changelog fragment. The prepared Faker 40.31 migration
  will move it; that is the probe doing its job.
- Carried from the release-chain plan and assumed here at their recommended answers unless the
  owner says otherwise: OQ-2 (no run-time refusal in V1), OQ-3 (`runtime_identity` unchanged),
  OQ-9 (no `canon` or `generator_logic`).

## 18. Pre-mortem

Assume it is 2026-12-04 and row 78 is not closed. Likely reasons, with the guard for each:

- The golden differed between Python 3.11 and 3.12. Guard: AT-E2-11 runs in both `ci.yml`
  `import-smoke` cells, which gate every merge, so the slice cannot land with a split golden.
- A test or notebook registered a custom `person_first_name` provider and the probe digested it.
  Guard: AT-E2-13 refusal.
- The golden was hand-edited to make a red cell green and hid a real drift. Guard: FM-12; the gate
  diffs `PROBE_GOLDEN` and refuses a change without a protocol bump or Faker repin.
- 78-C1 waited for a release. Guard: cut the RD-n stop the day E2 merges.
- C1 grew a second copy of the lock field list and missed `probe`. Guard: OQ-2 nesting and AT-C1-2.
- A path leaked through the companion reader. Guard: only three fields are copied; AT-C1-5.
- Review went to three rounds over the exit code. Guard: OQ-3 is asked up front.

## 19. Follow-ups (recorded, not in this row)

- V2-LOG: `support/_shape.py:252` `Versions` can be derived from `build_runtime_lock` instead of
  keeping a parallel shape (release-chain section 20).
- V2-LOG: frozen synthetic pools shipped with a lock; a project lock file and an opt-in run-time
  refusal (release-chain OQ-2).
- V2-LOG: the `support/` package now holds two concerns (support bundles and the runtime lock and
  probe); split into its own package if it grows a third.
- V2-LOG: an older CLI reading a newer report drops lock fields it does not know (the `lock/v1`
  reader ignores added fields), so compare across CLI versions can miss a new field. Compare
  reports from one CLI version for now.
- Windows chain (rows 6 and 89): add the AT-E2-11 probe step to the Windows CI job.
- V2-LOG: `support/__init__.py` imports `execution.native._route_decline_codes` (F32 E1); move
  `RouteDeclineCode` behind a public `execution.native` name and widen the AT-E2-14 sentry to the
  whole `support/` package.
- Platform V1: worker inventory and admission that compare `lock/v1` documents (parked).
- CLI roadmap row 78: record E1 merged and point at this plan. The release-chain plan section 7
  gains a one-line pointer to this plan for 78-E2 and 78-C1.

## 20. Review record

### Dennis r1 (GO-WITH-FIXES), resolved in revision 2

- H1: the E1 cells at `test_runtime_lock.py:71`, `:398`, `:406` would break. Read and write made
  symmetric (absent reads `None`, `None` omitted on write); AT-E2-10 is now an explicit edit list;
  contract 3.1 sentence names the `probe` exception.
- H2: `dps-dependency-matrix.yml` gates nothing. The check moved to `ci.yml` `import-smoke`; coverage
  stated per platform; Windows recorded for the Windows chain; pre-mortem fixed.
- M3: provider key is `person_first_name`; NumPy fallback removed (the pool build seeds Faker);
  custom-provider refusal and AT-E2-13 added.
- M4: one probe run; `run_probe` raises `ProbeError`; `probe_status(digest)` replaces
  `check_probe` and `ProbeResult`.
- M5: guarantee, Class 4 and Routes now say the probe covers the Python reference path and the
  native route is covered by the companion KATs through `native_selfcheck`.
- M6: compare catches `ValueError` and `MaskSecretError` at the parse boundary (exit 1);
  `ProbeError` and `OSError` go through `exit_code_for` (exit 3); cells added to AT-C1-8 and
  AT-C1-9.
- L7 FF1 inputs 6 to 10 digits. L8 CLI flat pin is 29. L9 wall-clock assertion dropped. L10
  `support/` drift V2-LOG and the Faker digest note. L11 older-CLI V2-LOG. L12 lazy imports.

### Codex r1 (NO-GO), resolved in revision 3

- 1 (V1): `--out` uses `write_local_target(path, data, WriteMode.REPLACE)`; `AtomicWriteError`
  exits 3 through the existing final arm of `exit_code_for`; AT-C1-9 covers it and the three
  valid names (leading dot, space, non-ASCII).
- 2 (DESIGN): public `providers_v2.custom_provider_names()`; boundary sentry
  `tests/sentry/test_runtime_lock_public_imports.py` (AT-E2-14); 78-E2 counts 6 production files.
- 3 (DESIGN): `_Field(name, spec, required)` descriptor read by `to_dict`, `from_dict` and compare;
  no `probe` branch; AT-E2-15 flips the flag; corpus and null-refusal cells kept.
- 4 (V2-LOG): CLI base refreshed to `f7deac1e3`; every cited CLI line re-checked, none moved.
- Codex r2 (orchestrator fix at the round cap path): DESIGN, rename the existing `_v2_custom_provider_names` to the public `custom_provider_names` instead of adding a second accessor; V2-LOG, CLI base refreshed to `f7deac1e3`.
