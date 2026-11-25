Status: plan

# PREFLIGHT-ARROW-PROFILE S2 and S3: pandas floor, engine release, CLI repin and the flipped CLI cells

Owner: Cam. Author: Opus. Date: 2026-11-25. Revision 1. Row: PREFLIGHT-ARROW-PROFILE (CLI `docs/ROADMAP.md`, 1.0, function break). Parent plan: revision 6 on branch `plan/preflight-arrow-profile` ("rev 6" below). S1a is merged (#796). S1b is engine PR #805, still in gate at head `079fdc90a`. This plan treats that head as its predecessor and re-anchors when #805 merges.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `profiles/local-operations.md`, `feature-dev.md`, `testing.md` (test depth and escalation triggers), `api-and-compatibility.md`, `config-secrets-and-supply-chain.md` (dependency floors and lockfiles), `release-and-rollback.md`, `workspace-and-vcs.md` (commit messages), `reuse-first.md`, `proportionality.md`, `cross-cutting-concerns.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` "Where Things Go"; CLI `CLAUDE.md`.

Anchors: a path with no prefix is in decoy-engine at `origin/main` `2b8a47fbe`. `#805:` is engine PR #805 at `079fdc90a`. `CLI:` is the decoy CLI repo at `origin/main` on 2026-11-25. Read with `git show`, not from a local checkout.

Risk: R2. S2a changes a dependency floor and the lock (full-suite trigger). S2b is the release path. S3 repins the CLI (version pin trigger) and changes user-visible exit codes. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S2a and S3; Codex for S2b.

## 1. Frame

After S1b, the engine's bounded profile no longer fails on a Parquet sample whose time has a fractional microsecond or whose date is outside Python's year range (rev 6 sections 3 to 5). The CLI cannot use the fix until three more things happen:

1. The engine declares a pandas floor it supports. `pyproject.toml:61` says `pandas>=1.5.0,<3`. No CI job runs pandas 1.5 or 2.0. In the S1b review, Dennis found that pandas 1.5 returns second-unit durations in nanoseconds, so the S1b recovery profile and the base profile disagree on a version the package claims to support (owner question Q-PAP-D7, vault `OWNER-QUESTIONS.md:264`, update at `:268`). Owner default A: raise the floor to 2.0.3 in S2, and add a CI floor job as a follow-up row.
2. A release with #805 and the floor. The latest tag is `v0.28.4`.
3. A CLI pin of that release, and CLI tests that stop characterizing the old refusal. Today `CLI:tests/e2e/test_run_chunked_parquet.py:539` asserts that `decoy run --chunked` exits 1 with "source not parsed" for the two fixture files, and `_direct` (`:527`) bypasses the CLI preflight to reach the engine at all. `CLI:CHANGELOG.md:32` documents the refusal as a known limit "tracked as row PREFLIGHT-ARROW-PROFILE".

V1 bar: a valid Parquet file with these values cannot be masked through `decoy run` today, on any route. That is a function break.

## 2. Guarantee and non-goals

S2a guarantees:

1. The wheel metadata requires `pandas>=2.0.3,<3`. `uv.lock` changes only in the pandas specifier line (`uv.lock:668`). The resolved pandas stays 2.3.3.
2. The floor is proven for the environment it names, not only claimed. A floor environment (Python 3.10 and 3.11, pandas 2.0.3, numpy 1.26.4, pyarrow 16.1.0) passes the #805 profile and capacity tests, including its eligible recovery fixtures, as floor characterization. (#805's selection has no second-unit duration cell, and its recovery excludes duration companions, so the pandas 1.5 duration finding is the reason for the floor, not a before cell this run can show; Codex R1.) An evidence file records the versions, commands, pass counts and every failure with its base reproduction, as `docs/plans/evidence/2026-10-30-f06-r2-evidence.md:85` did for F06.
3. Every engine doc or source comment that states a pandas lower bound states the pyproject floor, and a sentry keeps it so.

S2b guarantees: engine 0.28.5 is stamped by the normal process (`scripts/release/stamp_release.py:559`), with the version bump the stamp does not do (Codex R1 P1-7; release #782 did the same): `pyproject.toml:10`, `src/decoy_engine/release.py:50` `__version__`, and the engine entry in `uv.lock`. Before the tag, the built wheel's metadata version, the installed `decoy_engine.__version__` and the stamped registry agree. Then it is tagged and built. Its changelog lists #805 and S2a, with a `Breaking:` line for the floor.

S3 guarantees, through real CLI commands on the repinned CLI:

1. Three eligible fixtures (time64[ns] with a fractional microsecond, date32 below year 1, date32 past year 9999), each with an email column, pass `decoy validate preflight` with no `capacity.source_unreadable` check.
2. `decoy run --chunked` on the native default publishes the original `t` values exactly and exits 0. The bad row may be at row 0, row 9,999 (the last row of the 10,000-row capacity sample) or row 10,000.
3. `decoy run --chunked --no-native` exits 3 with `chunked_passthrough_value_unrepresentable`, prints no value, and writes no output file.
4. A plain `decoy run` (full frame) exits 3 with `full_frame_value_unrepresentable`, prints no value, and writes no output file.
5. A truncated Parquet file still exits 1 at preflight with `capacity.source_unreadable`.
6. The CLI changelog and the `decoy run --chunked` docs state exactly the supported schema from rev 6 section 4.

Non-goals: the CI floor job (follow-up row, owner default A); the pyarrow floor (section 16); decimal and nested companions (Q-PAP-D8 default A: widen in 1.x, decimal first); G-1 plain-route passthrough, G-4 scan, init and first chunk, G-5 capacity exception plumbing, and Arrow acceleration (all separate, rev 6 section 8); removing pandas 1.5 compatibility code (section 16); any engine source change in S2b or S3.

Size:

- S2a: about 15 changed lines (pyproject, lock specifier, two comments, one doc sentence, a changelog fragment), two new test functions in an existing sentry file (about 40 lines), and one evidence file. No new public names.
- S2b: the stamp output plus the three version lines.
- S3: about 30 changed pin and config lines along #408's file set, about 150 changed test lines, and about 20 doc and changelog lines. No new public names.

## 3. Established solutions

Search run on 2026-11-25:

- Online: pandas 2.0.0 and 2.0.3 release notes, the pandas install page (minimum dependency table), PyPI file lists for pandas 2.0.3, numpy 1.26.4 and pyarrow 16.1.0, the PyPA guide on declaring dependencies, and scientific Python SPEC 0 (minimum supported dependencies).
- Codebase: `docs/plans/evidence/2026-10-30-f06-r2-evidence.md`, `tests/sentry/dependencies/test_dependency_floors.py`, `.github/workflows/dps-dependency-matrix.yml`, engine release PR #782, CLI repin PR #408.

Findings:

- pandas 2.0 keeps non-nanosecond resolutions for datetime and timedelta. pandas 1.5 coerces them to nanoseconds, which is the Dennis finding. 2.0.3 is the last 2.0 patch release.
- pandas 2.0.3 has wheels for CPython 3.8 to 3.11 only. The engine supports 3.10 to 3.12 (`pyproject.toml:13`). On 3.12 a resolver that prefers wheels picks pandas 2.1.1 or newer; pandas 2.0.3 on 3.12 would need an sdist build, which the floor does not promise. So the floor is exercised on 3.10 and 3.11 only, and the docs say the 3.12 floor is in practice the first pandas with a 3.12 wheel.
- pandas 2.0.3 needs numpy below 2, but its PyPI metadata declares only `numpy>=1.21.0` / `>=1.23.2` with no upper bound (Dennis R1 P1-2). So `pip install decoy-engine pandas==2.0.3` into a clean venv can pull numpy 2.x, and pandas then fails to import. The engine declares no direct numpy pin (`pyproject.toml:61` area). This is a pandas packaging gap that any floor below 2.2.2 inherits: `pip install pandas==2.0.3` alone fails the same way with no engine present, so the engine floor does not create the break, but it does advertise a version where the user must add `numpy<2`. The floor environment pins numpy 1.26.4, as the F06 floor run did, and the `Breaking:` line and quickstart state the numpy limit (section 14 OWNER CALL).
- PyPA guidance: declare the lowest version you test. SPEC 0 says projects may drop dependency versions older than two years; pandas 2.0.3 (June 2023) is outside that window by November 2026, so SPEC 0 would also support the 2.2.2 option (section 14). It does not require dropping 2.0.3.
- The engine already has a floor sentry, `tests/sentry/dependencies/test_dependency_floors.py`. It reads the floor with `packaging.requirements` and checks the lock against it (the `uv lock --check` idea as a test). S2a adds pandas cells to it.

The design follows PyPA (declare the tested floor), the F06 evidence pattern and the existing floor sentry. The only new check is "docs state the same floor", because no tool compares prose with package metadata.

## 4. Reuse inventory

- `tests/sentry/dependencies/test_dependency_floors.py`: `_floor(name)` and `_locked(name)`. The pandas cells reuse both.
- `scripts/release/stamp_release.py` (`--version`, `--date`, `--cli-pins-base`, `--cli-pins`, `--cli-version`, lines 559 to 566) and the #782 file set, for S2b.
- CLI PR #408 (`chore(deps): pin decoy-engine 0.28.4`, open at `53d7c925d`) as the S3 file set: `pyproject.toml:153`, `requirements-certified.txt`, `requirements-dev.lock`, `.github/workflows/ci.yml:322` (engine git ref), the release smoke workflow, the bootstrap and lock scripts, the certification smoke, and the docs and tests it touches. The vault "engine repin checklist" lists the same set.
- `uv lock` and `uv pip install --python <ver>` for the lock and the floor environment.
- CLI test helpers in `CLI:tests/e2e/test_run_chunked_parquet.py`: `_typed_config` (`:253`), `_run_chunked` (`:288`), `_out` (`:292`), `_late_source` (`:601`), `_late_run` (`:611`).

## 5. Design notes

None: no new structure. No new module, abstraction or variant. One place per fact:

- The pandas floor lives in `pyproject.toml:61`. Docs quote it and the sentry checks the quote. There is no second constant in source.
- The supported recovery schema lives in rev 6 section 4 and in #805's recovery predicate (`#805:src/decoy_engine/profile/arrow/_recovery.py`). CLI docs describe it in user words and link the engine changelog. The CLI adds no schema check of its own.
- The fixtures live once, in `CLI:tests/e2e/test_run_chunked_parquet.py:511` (`_REFUSED_SOURCES`, renamed `_UNREPRESENTABLE_SOURCES` and extended with the third fixture).

House style applies to the touched tests only.

## 6. Choke point

The cross-cutting fact in S2a is "the pandas floor". Its one owner is `[project].dependencies` in `pyproject.toml`. The guard is two new cells in `tests/sentry/dependencies/test_dependency_floors.py`:

- `test_pandas_floor_keeps_unit_resolution`: `_floor("pandas") >= Version("2.0.3")`, with a comment that names the Dennis finding. Fail-before on `2b8a47fbe` (floor 1.5.0).
- `test_pandas_floor_statements_match`: walks `docs/**/*.md` (minus `docs/plans/`, `docs/records/`, `docs/quality/` and `docs/evidence/`, which hold history and measured versions), `README.md` and `src/**/*.py` for a pandas lower-bound statement and asserts each matched version equals `_floor("pandas")`, or is listed in an allowlist with a reason. A statement needs a bound marker, so plain version mentions ("pandas 2.3.3 used", "pandas 2.53 s") do not match. The patterns, each prefixed by `(?<![\w-])` so `geopandas>=` and `dask-pandas` do not match, are `pandas\s*>=\s*(\d+\.\d+(?:\.\d+)?)`, `pandas\s+(\d+\.\d+(?:\.\d+)?)\s+(?:or newer|or later|minimum)`, and the range spelling `pandas\s+(\d+\.\d+)\s*-\s*\d` (as in `internal/pandas_compat.py:6`, "pandas 1.5-2.x"), where the first number is the floor (Dennis R1 P1-1: an optional marker matched 15 files on main; Codex R1 added the range and prefix cases). `CHANGELOG.md` is excluded by path. Allowlist rows, each with a reason: `src/decoy_engine/quality/snapshot.py:349` ("only exists from pandas 1.5", a feature note, not a floor) and the quickstart parenthetical "on Python 3.12, pandas 2.1 or newer" (a wheel fact, section 3).

The walk is checked the way `cross-cutting-concerns.md` asks: the builder seeds "pandas 1.5 or newer" into a scratch copy of `docs/quickstart.md` and shows the cell fails, then removes the sentence and shows it passes. A committed matcher cell checks seeded cases: positives "pandas>=1.5", "pandas 1.5 or newer", "pandas 1.5-2.x"; negatives "pandas 2.3.3 used", "pandas 2.53 s", "geopandas>=0.14".

Mutation M-1: change the new `docs/quickstart.md` sentence back to 1.5. The statements cell turns red.

S3 adds no rule with more than one site. The CLI keeps its one preflight-to-check mapping (`CLI:src/decoy/cli/preflight.py:436-439`) and does not change it.

## 7. Placement

| New file | Directory | CODEMAP "Where Things Go" row | Beside |
|---|---|---|---|
| `2026-11-2x-pandas-floor-evidence.md` | `docs/plans/evidence/` | "Plans, decisions, records": `docs/plans/` | `docs/plans/evidence/2026-10-30-f06-r2-evidence.md` |
| `pandas-floor.md` | `changelog.d/` | "Changelog fragments" (`CODEMAP.md:302`): `changelog.d/<slice-slug>.md` | `changelog.d/preflight-arrow-profile.md` (from #805) |

The sentry cells go in an existing file, `tests/sentry/dependencies/`, which the "Sentry test" row names for "dependency floor rules". S2b and S3 add no file.

## 8. Behavior and failure modes

| Case | Before | After |
|---|---|---|
| install with pandas 1.5 to 2.0.2 already present | installs; S1b recovery can disagree with the base profile on durations | the resolver upgrades pandas to 2.0.3 or newer, or reports a conflict |
| install on Python 3.12 | resolver picks pandas 2.1 or newer | same |
| `decoy validate preflight` on the three fixtures | `capacity.source_unreadable`, exit 1 | no capacity failure |
| `decoy run --chunked`, bad row at 0 or 9,999 | exit 1 "source not parsed" | exit 0, `t` exact |
| `decoy run --chunked`, bad row at 10,000 or later | exit 0, `t` exact | same |
| `decoy run --chunked --no-native` | exit 1 at preflight (row 0), or exit 3 coded (late row) | exit 3, `chunked_passthrough_value_unrepresentable`, no value, no file |
| `decoy run` (full frame) | exit 1 at preflight | exit 3, `full_frame_value_unrepresentable`, no value, no file |
| truncated Parquet | exit 1, `capacity.source_unreadable` | same |
| decimal or nested column beside the bad time | exit 1 at preflight | same, with the sanitized engine message from rev 6 section 5 |

Failure modes the plan checks for:

- F1: a floor-environment failure in a test #805 did not touch. The builder runs the same test on the S2a base in the same environment. If it fails on base, it is recorded in the evidence file as pre-existing (as F06 did for `test_phase_f_f2_mixed_admission.py`) and not fixed in S2a. If it is new with the floor, S2a stops and reports.
- F2: `uv lock` rewrites more than the specifier line. The builder uses the uv version of the last lock change, and AT-S2-2 fails on any other changed line.
- F3: the release stamp picks up a fragment from a PR that is not on main. The stamp runs on a fresh `origin/main` worktree only.
- F4: the CLI default route on a CI leg without the companion. The chunked carry is chosen by the stock adapter (`execution/_chunked_carry.py:274-287`), not by the companion, so the exit-0 cells run on every leg, companion-free legs included, with no companion marker (Codex R1). The `--no-native` and plain-run cells also run on every leg.
- F5: a value leaks through a CLI output surface. The S3 cells check stdout and stderr under `--json` and `--verbose`.
- F6: a user pins pandas below 2.0.3 for another package. They get a resolver conflict at install, not a wrong answer at run time. This is the intended behavior and the `Breaking:` line says so.

## 9. Acceptance tests

Fail-before is recorded on the parent commit of each slice.

| ID | Slice | Test | Fail-before |
|---|---|---|---|
| AT-S2-1 | S2a | `uv pip install --dry-run` of the built wheel into a venv with pandas 2.0.2 reports an upgrade or a conflict. A clean resolver install of the built wheel with `pandas==<floor>` plus the documented companion constraint (`numpy<2` for 2.0.3) on each Python that has a floor wheel, then `python -c "import pandas, decoy_engine"`, passes. A recorded probe (evidence file) installs pandas 2.0.3 with no numpy constraint and records whether numpy 2 is resolved and the import fails, so the documented limit is shown, not assumed | 2.0.2 accepted (metadata says 1.5.0) |
| AT-S2-2 | S2a | `git diff` of `uv.lock` against the parent changes only the pandas specifier line | guards F2 |
| AT-S2-3 | S2a | floor run on Python 3.10 and 3.11 with pandas 2.0.3, numpy 1.26.4, pyarrow 16.1.0: `tests/unit/profile/`, `tests/unit/execution/test_capacity_arrow_profile.py`, `tests/unit/execution/test_full_frame_value_unrepresentable.py` (all from #805), and T1 on the S2a diff; pass counts and every failure with its base reproduction in the evidence file | characterization only: the before cell is AT-S2-1's metadata acceptance of 2.0.2 |
| AT-S2-4 | S2a | the two sentry cells in section 6 pass, and M-1 turns the statements cell red | floor cell fails on 1.5.0 |
| AT-S2-5 | S2b | before tagging: the 0.28.5 wheel metadata has `Version: 0.28.5` and `Requires-Dist: pandas<3,>=2.0.3`; installed `decoy_engine.__version__` is `0.28.5`; `CHANGELOG.md` has the `Breaking:` floor line and the #805 entry | 0.28.4 metadata says 1.5.0 |
| AT-S3-1 | S3 | `decoy validate preflight` on the three fixtures: no `capacity.source_unreadable` in text or `--json`; a truncated Parquet still has it, exit 1 | exit 1 on the three fixtures |
| AT-S3-2 | S3 | `decoy run --chunked`, default route, bad row at 0, 9,999 and 10,000, each fixture: exit 0, `t` equals the source column | rows 0 and 9,999 exit 1 |
| AT-S3-3 | S3 | `decoy run --chunked --no-native`, with `--json` and with `--verbose`: exit 3, code `chunked_passthrough_value_unrepresentable`, none of the fixture markers (the raw cell digits, `out of range`, `nanosecond`, `year`), no output file | row 0 exits 1 at preflight |
| AT-S3-4 | S3 | plain `decoy run`, with `--json` and with `--verbose`: exit 3, code `full_frame_value_unrepresentable`, no markers, no output file | exit 1 at preflight |
| AT-S3-5 | S3 | a `when:` gate that reads `t` on the default chunked route: exit 3, `chunked_passthrough_value_unrepresentable`, value-free; the existing `test_a_read_column_is_coded_and_value_free` cells, now also at row 0 | row 0 exits 1 at preflight |
| AT-S3-6 | S3 | `_direct` is deleted; no CLI test imports `_run_chunked_mask` for these fixtures | `_direct` exists |
| AT-S3-7 | S3 | the CLI's repin checks pass on 0.28.5: the pin, `requirements-certified.txt`, the CI engine ref, the release smoke and the compatibility fences that #408 moves | pin is 0.28.3 or 0.28.4 |

The S3 edits to `TestValuesPandasRefuses` replace a characterization of a known defect. They do not weaken an assertion: each old exit 1 becomes a stronger assertion on values, codes and leaks.

## 10. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M-1 | the `docs/quickstart.md` floor sentence says 1.5 | AT-S2-4 statements cell |
| M-2 | `pyproject.toml:61` stays at 1.5.0 | AT-S2-1, AT-S2-4 floor cell |
| M-3 | S3 pins the CLI to 0.28.4 (no #805) | AT-S3-1, AT-S3-2 |
| M-4 | in a scratch engine build, #805's recovery rejects every date32 recovery | AT-S3-1 and the in-sample AT-S3-2 cells (bad row 0 and 9,999) for the two date32 fixtures |
| M-5 | the CLI error renderer appends a known sentinel built from the source cell (the engine exception's `__context__` is already empty at `#805:execution/_pipeline_full_frame.py:222-236`, so printing it shows nothing) | AT-S3-3, AT-S3-4 |

M-4 runs against a local editable engine in the CLI venv. It is a gate probe, not a committed test.

## 11. Frozen contracts and byte changes

- Wheel metadata: the pandas floor moves from 1.5.0 to 2.0.3. Named in the 0.28.5 `Breaking:` line and in `docs/compatibility-contract.md` section 1 as a pre-GA correction.
- No output bytes change in S2a or S2b. #805's own contract notes ship in 0.28.5 unchanged.
- CLI exit codes: for the eligible sources, preflight exit 1 becomes exit 0 (default chunked) or exit 3 (`--no-native`, plain run). One CLI changelog entry under `[Unreleased]`, with a `Breaking:` prefix as in the house style at `CLI:CHANGELOG.md:30`, replaces the limit text at `CLI:CHANGELOG.md:32`. No reason code is added or renamed. `capacity.source_unreadable` keeps its meaning for unreadable files.
- `CLI:requirements-certified.txt` keeps `pandas==2.3.3`, so the CLI's own install does not move.

## 12. Class tables

### 12.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the engine sanitizes at the profile boundary (#805); S3 checks every CLI surface (`--json`, `--verbose`, stderr) for fixture markers | AT-S3-3, AT-S3-4, AT-S3-5 | M-5 |
| 2 | Cleanup missing on an exit path | every failing CLI cell asserts no output file; the engine's publish abort owns cleanup | AT-S3-3, AT-S3-4 | M-5 on a failing route still leaves no file |
| 3 | State machine and concurrency | N/A no shared state or new transition; release and repin are ordered by slice dependency, not runtime state | section 14 order | N/A nothing to mutate |
| 4 | Route parity and silent fallback | the CLI cells cover default chunked, `--no-native` chunked and plain; each route has one stated outcome in section 8 | AT-S3-2, AT-S3-3, AT-S3-4 | M-3, M-4 |
| 5 | Referential integrity | N/A the CLI fixtures have no relationships; the FK pricing cell is an #805 engine test | #805 tests | N/A no FK code changes |
| 6 | Untrusted producer | the Parquet file is the untrusted producer; a truncated file is still refused at preflight | AT-S3-1 truncated cell | M-3 |
| 7 | Check then use (TOCTOU) on a path | N/A no new path check; the CLI reads the source once per stage as today | existing preflight tests | N/A no check-then-open added |
| 8 | Weak tests and overclaimed evidence | the floor claim rests on a recorded run; old characterization cells become stronger assertions; every floor failure has a base reproduction | AT-S2-3 evidence, AT-S3-6 | M-2, M-4 |
| 9 | Behavior-preserving refactor drift | S2a and S2b change no engine source except two comments; S3 changes no CLI source except pins and docs | `git diff --stat` limited to sections 7 and 13.4 | M-3 |
| 10 | Frozen contract drift | the floor and the exit-code change are named in both changelogs and the compatibility contract | AT-S2-5, section 11 | M-1 |

### 12.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| Anchored validation | yes | the statements regex is anchored on `pandas` plus a version; the seeded-bypass check in section 6 |
| Strict wire and stored types | no | no wire type changes |
| No exception context in output | yes | AT-S3-3, AT-S3-4 and M-5 |
| Versioned read models | no | no read model |
| Normalized guard scanners | yes | the statements cell walks `docs/`, `README.md` and `src/` by pattern, not a fixed list |
| No reaching into private modules | yes | AT-S3-6 removes the test import of `decoy.cli.run._execute._run_chunked_mask` |
| No hidden CI failures | yes | the floor run is recorded evidence; the CI floor job is a named follow-up, not implied |
| One input, one trust class | no | no new entry point |
| Mutations on the final head | yes | section 10 on each slice's final head |
| Allowlisted helpers still checked | yes | each statements-allowlist row carries a reason |
| No raised caps | yes | no cap moves |

## 13. Enumerations

### 13.1 Exit paths

`decoy run` on an eligible source after S3:

- Preflight passes; the capacity profile succeeds through the #805 recovery (`#805:src/decoy_engine/profile/arrow/_recovery.py`). Before, `CLI:src/decoy/cli/preflight.py:436` mapped `capacity_source_unprofilable` to `capacity.source_unreadable`, exit 1.
- Chunked native publishes, exit 0.
- Chunked `--no-native` raises `chunked_passthrough_value_unrepresentable`, exit 3, publish aborted.
- Plain run raises `full_frame_value_unrepresentable` (`#805:src/decoy_engine/execution/_pipeline_full_frame.py`), exit 3, publish aborted.
- A `when:` gate that reads the column raises the chunked code, exit 3.

Install: resolves pandas 2.0.3 or newer, or reports a resolver conflict. No run-time exit is added.

### 13.2 Routes

| Route | Reached by | Outcome after S3 |
|---|---|---|
| chunked native (`--chunked`) | `CLI:src/decoy/cli/run/_execute.py` `_run_chunked_mask` | exact publish |
| chunked pandas (`--no-native`) | same, `pandas_only` | coded refusal |
| full frame (plain `decoy run`) | engine `run_pipeline` | coded refusal |
| `decoy validate preflight` | `CLI:src/decoy/cli/validate.py:77` | passes |
| `decoy scan`, `decoy init` | their own profile contracts | unchanged (G-4) |

### 13.3 FK shapes

- N/A for S2: no engine source change.
- N/A for S3: the CLI fixtures are single tables with no relationships. The FK pricing fixture is an #805 engine cell and is not repeated in the CLI.

### 13.4 Fields

- `[project].dependencies` pandas entry (`pyproject.toml:61`): `>=1.5.0,<3` becomes `>=2.0.3,<3`.
- `uv.lock` pandas specifier (`uv.lock:668`): the same change; the resolved version does not move.
- `src/decoy_engine/internal/pandas_compat.py:6` and `:25`: "pandas 1.5-2.x" comments become "pandas 2.0.3-2.x".
- `docs/quickstart.md:15`: one floor sentence after the Python line.
- CLI `pyproject.toml:153`: `decoy-engine==0.28.3` (or 0.28.4 after #408) becomes `==0.28.5`, with the other #408 files.
- CLI preflight report: the `capacity.source_unreadable` check is absent for eligible sources. No field is added.

### 13.5 Output surfaces

- Wheel metadata (`Requires-Dist`).
- Engine `CHANGELOG.md` (from fragments), `docs/quickstart.md:15`, and the `docs/compatibility-contract.md` section 1 note.
- CLI stdout, stderr, `--json` and `--verbose` for `decoy run` and `decoy validate preflight`, checked value-free by AT-S3-3 to AT-S3-5.
- `CLI:CHANGELOG.md:32` and the `decoy run --chunked` section of `CLI:docs/cli-reference.md`.
- Output files: published only on exit 0.
- Logs, audit and evidence files: N/A no new log site; #805 already sanitizes the engine error text.

## 14. Slices

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S2a | engine | floor in `pyproject.toml:61`, `uv lock`, the two `pandas_compat.py` comments, the quickstart sentence, the two sentry cells, `changelog.d/pandas-floor.md` with a `Breaking:` line, the evidence file; AT-S2-1 to AT-S2-4 | #805 merged (the floor run covers its tests) | R2 | T1, then the full engine suite (dependency floor and lock trigger) diffed against the saved main baseline; gate Codex then Dennis |
| S2b | engine | `chore(release): 0.28.5` from `stamp_release.py` on fresh main, plus the version in `pyproject.toml:10`, `release.py:50` and `uv.lock`; the AT-S2-5 agreement check before the tag; tag `v0.28.5`, the release workflow | #805 and S2a merged | R2 (release path) | the release workflow's own checks; gate Codex. Engine releases are pre-authorized before GA |
| S3 | CLI | repin to 0.28.5 along #408's file set; flip `TestValuesPandasRefuses`, delete `_direct`, add a `date32_late` fixture (+3,000,000 days), parametrize the bad row over 0, 9,999 and 10,000, add the plain-run and validate-preflight cells, docs and changelog; AT-S3-1 to AT-S3-7 | S2b tagged and CLI #408 merged | R2 (version pin, exit codes) | T1, then the CLI full suite with `gates.sh --full` (version pin trigger); gate Codex then Dennis |

OWNER CALL (recommended non-breaking option taken): S3 waits for CLI #408 to merge to main and rebases on it. It does not stack on #408's branch, because a PR merged into a non-main base does not ship, and #408 already moves every repin file.

OWNER CALL (recommended non-breaking option taken): S2a and S2b are separate PRs. The floor needs the full suite and its own review. The release PR stays a mechanical stamp.

Order: #805, S2a, S2b, S3. The S2a branch may be prepared on top of #805's head while #805 is in gate, but the S2a PR targets `main` and is opened only after #805 merges, rebased on that main. A PR merged into a non-main base never ships. Its floor run is repeated on the merged #805.

OWNER CALL (recommended non-breaking option taken; open for the owner): the floor stays at 2.0.3, the owner default A for Q-PAP-D7. It drops the fewest existing installs. Its cost is the numpy limit in section 3: pandas releases below 2.2.2 (2.0.x, 2.1.x, 2.2.0 and 2.2.1) import only with numpy below 2, and pandas metadata does not enforce that. S2a states it in the `Breaking:` line ("pandas 2.0.3 or newer; pandas below 2.2.2 needs numpy below 2") and in the quickstart sentence. The alternative is a 2.2.2 floor: it supports numpy 2, has wheels for CPython 3.10 to 3.12 (so the floor is testable on every supported Python), and drops the 3.12 parenthetical. It removes more installs. If the owner picks 2.2.2, S2a changes only the floor value, the evidence environment and the doc sentence. Codex R1 asked that this choice be settled before a release: S2a may be built on the default, but the S2b tag waits for the owner to confirm 2.0.3-with-note or 2.2.2. The orchestrator relays this as an open item.

Rollback (`release-and-rollback.md`):

- S2a: revert the commit. The floor is metadata only; no stored data depends on it.
- S2b: if 0.28.5 breaks a user, cut 0.28.6 with the fix. Do not delete the tag. The CLI stays on its old pin until S3, so S2b alone does not change any CLI user.
- S3: revert the CLI PR. That restores the old pin and the old tests together.

Post-release check for S2b: install 0.28.5 from the built wheel in a clean venv on Python 3.12 and 3.10, run `decoy_engine` import and the #805 profile tests. Stop criterion: any failure. Then S3 waits.

## 15. Pre-mortem

- The floor run fails on something unrelated to #805, as F06 did. F1 covers it: reproduce on base, record it, do not fix it in S2a.
- A reader on Python 3.12 expects 2.0.3 to be tested there. It cannot be, with no wheel. The quickstart sentence says "pandas 2.0.3 or newer (on Python 3.12, pandas 2.1 or newer; pandas below 2.2.2 needs numpy below 2)".
- A user installs pandas 2.0.3 and numpy 2 together and the import fails. The `Breaking:` line and quickstart state the limit; the owner can move the floor to 2.2.2 (section 14).
- #805 changes again in gate. S2a only cites its test paths, and the floor run is repeated on the merged head.
- #408 is replaced by a 0.28.5 pin PR before S3 starts. S3 then edits only the flipped tests, docs and changelog. AT-S3-7 checks the pin wherever it came from.
- The CLI preflight split (row CLI-SPLIT) moves `preflight.py` before S3. S3 cites the mapping by function, not line, and changes no preflight code.
- The default chunked route falls back to pandas on a CI leg without the companion, so the exit-0 cells fail. F4 covers it with the existing marker rules.
- The release stamp's certified-stack step needs CLI pin files for 0.28.5 that do not exist yet. The stamp runs with `--cli-pins-base` at the 0.28.4 file, as #782 did; the CLI pins are certified in S3.
- A pandas 1.5 compatibility branch in `pandas_compat.py` becomes dead. It is left in place: removing it is a refactor with its own risk and is a follow-up.

## 16. Follow-ups (not in this row)

- CI floor job (owner default A for Q-PAP-D7): a leg that runs T1 on Python 3.11, pandas 2.0.3, numpy 1.26.4, pyarrow 16.1.0. New row.
- G-PYARROW-FLOOR: `pyproject.toml:76` declares `pyarrow>=14.0.0`, but `src/decoy_engine/execution/_mem_estimate_arrow.py:118` uses `pa.types.is_string_view`, which needs pyarrow 16 (F06 evidence, line 87). OWNER CALL (recommended non-breaking option taken): record it as a follow-up row with the CI floor job. Not in S2a. No doc in S2a states a pyarrow floor.
- Remove pandas 1.5 compatibility branches that the new floor makes dead (`proportionality.md`: do not probe for a version the pin guarantees). Separate refactor row.
- Q-PAP-D8: decimal first, in 1.x.
- G-1, G-4, G-5 as in rev 6 section 8.
