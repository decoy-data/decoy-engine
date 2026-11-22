Status: plan

# SIGNATURE-SENTRY: a public signature break needs a Breaking line that names it

Owner: Cam. Author: Opus plan agent. Date: 2026-11-22. Roadmap row: SIGNATURE-SENTRY (`C:docs/roadmap/groups/health.md:21`). Anchors are in this repository (decoy-engine) unless marked `C:` (decoy CLI). Read at engine `origin/main` `8c2a194a3` and CLI `origin/main`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN section), `api-and-compatibility.md`, `cross-cutting-concerns.md` (choke point, guard test, mutation), `testing.md` (test depth, full-suite triggers), `reuse-first.md`, `proportionality.md`, `config-secrets-and-supply-chain.md` (new dev dependency), `release-and-rollback.md`, `documentation.md`, `profiles/local-operations.md`, `workspace-and-vcs.md`. Engine `CODEMAP.md` "Where Things Go", `docs/compatibility-contract.md` sections 3.4, 5, 6 and 9, `docs/frozen-surfaces.md`.

Risk: R2 (CI gate, a new dev dependency in the lock, and the frozen public-name contract). Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes, the slice hits two escalation triggers (dependency lock, frozen contract).

## 1. Frame

### 1.1 What happened

Engine 0.28.3 made `compile_plan(..., sources: SourceFacts)` a required keyword-only argument. The CLI repin branch (`C:origin/chore/pin-engine-0.28.3`) broke on every `compile_plan` call and now imports `NO_SOURCES` from `decoy_engine.contracts.column_shape` in three files (`compile_explain.py`, `demo.py`, `cli/gate/_layers.py`).

Correction to the row text: the signature change landed in engine #750 (COLUMN-SHAPE E1a, `035543388`), not #751. #751 only changed the call sites inside `_compile.py`. Both shipped in 0.28.3.

A second frozen break shipped in the same release with no Breaking line that names it: `VaultWriter.__init__` lost `mask_key` and gained a required `prepared`. The vault v3 Breaking bullet speaks of the file format, not the constructor. Griffe found both (section 6.2).

### 1.2 Why each existing gate missed it

| Gate | What it checks | Why it passed #750 |
|---|---|---|
| Public census (`tests/sentry/release/test_public_census.py`, `_census.py`) | Every exported name has exactly one stability tier | It pins names and tiers, never signatures. `compile_plan` is a root export (FROZEN) and its tier did not move. `docs/frozen-surfaces.md` records this as known limit `RGF1-KL-4`: "Signatures and fields are not pinned except where a row names a signature or shape test." The row for `compile_plan` names only `tests/unit/test_public_api.py`, which checks importability. |
| Frozen path list (`docs/frozen-surfaces.md`, read by `scripts/release/frozen_map.py`) | Paths that count as frozen | `src/decoy_engine/plan/` IS on the list (row "Config helpers, plan, validation..."). So the path list was not the gap. |
| Compat preflight (`compat-preflight.yml`, `scripts/check_compat_preflight.py`) | A PR that touches a frozen path ticks the section-9 checklist | It fired, and the author ticked every box. The "additive" box carried the note "New keywords are additive". The check reads ticks, not code, so a wrong claim passes. |
| Breaking ratchet (`tests/unit/test_changelog_breaking_ratchet.py`) | In a released section, an entry outside the Breaking list that says "now fails", "refuses", "raises" or "rejected" must be triaged | The #750 entry said "`compile_plan` gains `source_schemas`". No break word, so nothing to triage. The name was also wrong (the merged parameter is `sources`). |
| Fragment check (`scripts/dev/check_fragment.py`) | A `src/` change carries a parseable fragment | #750 had a fragment, and it even had a `Breaking:` line, about stored plans and profile hashes. Nothing ties a Breaking line to the names it must cover. |

Root cause: no gate reads the code to find a signature break, and no gate ties a Breaking line to the broken name. Each gate trusts the author's words. The fix reads the code (two trees) and checks the words against it.

## 2. Pinned guarantee and non-goals

### 2.1 Guarantee

G1. Between the newest release tag reachable from HEAD and the HEAD tree, every API break that griffe reports on an object in scope must be announced by a pending Breaking line. Scope is every name that is FROZEN or EXPERIMENTAL at the base tag or at HEAD (H4). A break is announced when one Breaking line names, in backticks, a public name of the object and, for a parameter break, the parameter (B5). If a break is not announced and has no live exemption row (B8), the sentry `tests/sentry/release/test_public_signatures.py` fails and lists each break as `<public name>: <griffe breakage kind> (<parameter>)`.

"API break" means these griffe kinds: parameter removed, parameter moved, parameter kind changed (for example positional to keyword-only), parameter default changed, required parameter added, parameter changed to required, public object removed, object kind changed, class base removed.

"Pending Breaking line" means the `Breaking:` first line of a fragment in `changelog.d/` at HEAD, or a bullet in the `### Breaking for consumers` list of a CHANGELOG release section that is newer than the base tag. The second source covers the release PR, which compiles the fragments into CHANGELOG and deletes them. A Breaking list under `## [Unreleased]` is not read and is refused (L3): `stamp_release` never writes one there, and fragments are the one place for pending notes. The sentry fails when `[Unreleased]` holds a `### Breaking for consumers` heading.

G2. `decoy_engine.plan` exports `NO_SOURCES` (FROZEN) and `SourceFacts` (EXPERIMENTAL), each by a `TIER_EXCEPTIONS` or `EXPERIMENTAL_OBJECTS` row and named in contract 3.4, so a caller of the frozen `compile_plan` can build its required argument from a public path. `SourceFacts` is EXPERIMENTAL because COLUMN-SHAPE is still moving its fields (L7); `NO_SOURCES` is the value callers pass today and stays FROZEN.

G3. The 0.28.3 CHANGELOG section is corrected in this slice (owner answer to Q2, section 11).

### 2.2 Non-goals (findings here become follow-ups, not blockers)

- N1. Type compatibility. Griffe's `ReturnChangedTypeBreakage` and `AttributeChangedTypeBreakage` compare annotation text. They are excluded. Deep type analysis (is `X | None` the same as `Optional[X]`, is a narrower return a break) is out of scope.
- N2. Constant values. `AttributeChangedValueBreakage` is excluded. It fires on `__version__`, `REGISTRY_VERSION` and registry tables at each release. Output-affecting values are pinned by the golden and determinism tests (contract section 6).
- N3. INTERNAL-tier names. Not covered (owner answer to Q1).
- N4. Behaviour changes with an unchanged signature (a new refusal, a changed output). The breaking ratchet and the goldens own those.
- N5. Shapes griffe cannot see or does not compare. Each is listed as a known limit in `docs/frozen-surfaces.md` with the gate that owns it:
  - Pydantic model fields made required: `tests/snapshots/test_frozen_schemas.py` (the frozen JSON schemas).
  - A member added to a Protocol or ABC that a caller implements (the `sdk` `FileSource` and `FileSink` bases): no gate today; known limit, review owns it.
  - A removed `@overload` variant: no gate; known limit.
  - A keyword-only parameter swallowed by `**kwargs` (made required inside the body): no gate; known limit.
  - Signatures made at run time (`functools.wraps`, a `__signature__` set by code) and classes created at run time: no gate; known limit.
  - An alias griffe cannot resolve: not a silent skip for the FROZEN or EXPERIMENTAL names in scope at the base or HEAD. B3 counts each such name it cannot map to the corresponding griffe tree, and the sentry fails when that count is above zero, listing the names (fail closed). It does not check unresolved names that are INTERNAL at both ends. Current main has 27 expected unresolved INTERNAL lazy PEP 562 exports: 26 in `decoy_engine.quality` through `_LAZY_EXPORTS` and `__getattr__`, plus `decoy_engine.execution.native.MAX_NATIVE_THREADS`. They are out of scope under N3 and do not fail the run.
- N6. Whether the Breaking sentence is accurate. The sentry checks that the names are there in backticks, not that the sentence is right. Review owns the sentence.
- N7. A default for `compile_plan(sources=)`. Requiring it was a deliberate E1a choice ("no route can forget"). This slice does not reopen it.
- N8. Exporting `build_source_facts`. The CLI uses only `NO_SOURCES`. Export it when a caller needs it.
- N9. A PR-description check. The sentry runs in the gate on code; the compat preflight checklist stays as it is.

## 3. Behaviour

### 3.0 Precondition (H2): the test nodes must hold the release tags

The Dell and Mac bare repos (`~/decoy/engine.git`) each held 0 tags on 2026-11-22, because `~/bin/vm-run` (near line 124) and `~/bin/decoy-vm-t3` (near line 121) pushed only the snapshot ref and `main`. Without tags every node run of the sentry fails (B1), and a red main baseline would hide real failures. Before the slice merges:

1. The orchestrator changes both scripts to also push `refs/tags/v*` (edit a copy, then `mv` over the live script; the scripts are live).
2. On the node used for the required green run, `git tag | wc -l` reports a number greater than 0. That node run (vm-run on the Dell or Mac) then shows `test_public_signatures.py` green on the slice head, and the main baseline used for the merge-head diff is refreshed after the tag push.

The builder does not start the merge step until both hold. There is no skip and no fallback when tags are missing.

### 3.1 Steps

B1. The sentry finds the base: `git describe --tags --abbrev=0 --match "v[0-9]*.[0-9]*.[0-9]*" HEAD`. The glob also matches an rc tag such as `v1.0.0rc1` (L6); a reachable rc tag is a valid base, because a release candidate is something a consumer can pin. If no tag is reachable (a shallow clone, a tagless node repo), the test fails with "signature sentry needs the release tags: fetch with tags" and never skips. The CI jobs that run `tests/sentry` already check out with `fetch-depth: 0` (`ci.yml` regression-gate, `gate-selfhosted.yml` gate job), which brings the tags; the test nodes get them by 3.0.

B2. It extracts the base source with `git archive <tag> src | tar -x -C <tmp>` into a pytest `tmp_path_factory` directory (H1). It does not use `griffe.load_git`: that makes a temporary branch and worktree named after the ref in the shared `.git`, removes them only on a clean exit, and parallel worktrees race on the name. `git archive` writes nothing to the repository. It then loads both trees with `griffe.load("decoy_engine", search_paths=[<dir>/src], resolve_aliases=True, resolve_external=False)`: the base from the extract and HEAD from the working tree (so an uncommitted local edit counts). It calls `griffe.find_breaking_changes(base, head)` once on the whole package.

B3. Scope paths come from griffe, not from runtime attributes (H3). Runtime `__module__` is rewritten on FROZEN errors (`_error_base.py:35` sets `DecoyError.__module__ = "decoy_engine.errors"`; `_execution_error.py:25` does the same for `ExecutionError`), while griffe reports a break at the static defining path, for example `decoy_engine._execution_error.ExecutionError.__init__`. So for each in-scope census name `(module, name)` the helper looks up `head_tree[<module>.<name>]` and records its alias `final_target.path` (or its own `path` when it is not an alias), plus the public spelling `<module>.<name>`, each mapped to the bare public name. An in-scope census name that griffe cannot resolve is counted and fails the run (N5, fail closed). Names that are INTERNAL at both base and HEAD are not checked for resolution; this intentionally excludes the 27 current lazy PEP 562 exports named in N5. A breakage is in scope when its `obj.path` equals a scope path, or starts with a scope path plus `.` (a method or parameter of a class in scope). Removals: an object removed by HEAD is mapped through the base tree the same way (B3a).

B3a. Tiers are the union of the base and HEAD (H4). HEAD tiers come from the live census (`_census.load()`, `_census.classify()`). Base tiers come from the base extract and the base tree's `__all__` lists from griffe. The helper parses the base `contracts/stability.py` with `ast`, first builds a name map from that file's own literal tier assignments (`FROZEN`, `EXPERIMENTAL` and `INTERNAL`), and then evaluates the `PACKAGE_TIERS`, `TIER_EXCEPTIONS` and `EXPERIMENTAL_OBJECTS` assignments with that map. The evaluator accepts literal constants and literal list, tuple and dict containers; it accepts an `ast.Name` only when that name is in the tier map. `EXPERIMENTAL_MODULE` is read as a literal assignment. An unknown name or any other node fails closed. This handles the real file's bare tier names such as `"decoy_engine": FROZEN` without importing base code. A name is in scope when either side gives it FROZEN or EXPERIMENTAL. So a PR that deletes a FROZEN `TIER_EXCEPTIONS` row and breaks the name in the same diff is still caught. The removal rule follows from this: a removed root or `sdk` export is in scope through the base tiers, and because `decoy_engine` and `decoy_engine.sdk` are FROZEN packages, every removed name they exported, EXPERIMENTAL ones included, is covered (L2).

B4. It collects the pending Breaking lines (definition in G1), one entry per line or bullet, never one joined text. Fragments are read through `stamp_release.parse_fragment`. CHANGELOG sections are read through `stamp_release.release_sections` and the Breaking-list split that `stamp_release.py` already has: promote `_split_breaking` to a public `breaking_lists`. One grammar, no second parser.

B5. Matching is per line (M1). A break is announced when one single Breaking line contains, as backticked identifiers:
- one of the object's public names (`` `compile_plan` `` or `` `decoy_engine.compile_plan` ``; the last dotted part must equal the name), and
- for a parameter kind, the parameter name taken from griffe's `old_value` or `new_value` (`` `sources` ``; for a rename, either the old or the new name).
Removal, kind-change and base-removal breaks need only the public name. A plain-text mention does not count. So an earlier, unrelated Breaking line that happens to mention `compile_plan` does not announce a later `sources` break: the #750 failure.

B6. Output on failure: one line per unannounced break, for example `compile_plan: Parameter was added as required (sources)`, then "add a `Breaking:` line naming `compile_plan` and `sources` in backticks to your changelog.d fragment". It prints names and griffe kinds only, never file content or Breaking text.

B7. `decoy_engine.plan.NO_SOURCES is decoy_engine.contracts.column_shape.NO_SOURCES`, and the same holds for `SourceFacts`. The census gives `NO_SOURCES` FROZEN and `SourceFacts` EXPERIMENTAL on every path.

B8. Exemptions (M2). `PARAMETER_CHANGED_DEFAULT` compares default text, so a cosmetic rename of the default constant (`DEFAULT` to `_DEFAULT`, same value) reports a break. A false Breaking bullet would mislead readers, so the helper holds a small reviewed table `SIGNATURE_EXEMPTIONS` in `_signatures.py`, keyed `(base_tag, defining path, kind, parameter)`, with a reason per row. A row matches only while the current base tag equals its `base_tag`. After a newer tag is cut, the stale row is inert: matching ignores it and its presence never fails the sentry. It is removed in the first PR after the tag is cut, not in the release PR. A non-blocking report may list stale rows for that cleanup. The table starts empty. Each row is a reviewed diff in the PR that adds it.

## 4. Failure modes

| # | Failure | Handling |
|---|---|---|
| F1 | No tag reachable | Fail with the fetch message (B1). Never skip. Test nodes get tags by the 3.0 precondition. |
| F2 | Griffe cannot parse a module or resolve an in-scope census alias | A parse failure fails the run. The unresolved-name count covers only names that are FROZEN or EXPERIMENTAL at base or HEAD and fails the run when one cannot be mapped (B3, N5). It does not count the 27 known INTERNAL lazy exports. The floor check in AT-9 also fails when fewer in-scope objects than the measured count are mapped. |
| F3 | A break reported under a path the scope does not map | Scope paths come from griffe's own HEAD and base trees (B3), so the spelling matches what griffe reports. AT-2, AT-7 and AT-12 prove root alias, class method, removal and a rewritten `__module__`. |
| F4 | An unrelated Breaking line that contains the name | Not enough on its own for a parameter break: the same line must also name the parameter in backticks (B5). For a removal, accepted (N6). |
| F5 | A break added and then reverted before the release | No net break against the tag, so nothing to announce. Correct. |
| F6 | Release PR: fragments deleted, text moved into CHANGELOG | B4 reads the new release section's Breaking list. AT-6. |
| F7 | Run time | Dennis measured about 6 s for both loads with griffelib 2.3.1; the planning run measured 16 to 19 s with `load_git` on a busy box. No time assertion in the test (L5); the builder reports the measured time. Loads are module-scoped fixtures. |
| F8 | griffelib drops Python 3.10 | It did at 2.3.2. Pin `griffelib>=2.3.1,<3`. The lock resolves at the engine floor (`requires-python >=3.10`), so uv picks 2.3.1, the last release that supports 3.10. Revisit when 3.10 leaves the matrix. |
| F9 | `griffe` not installed in a venv | The ImportError fails collection (no `importorskip`). The skip guard for the gate is the `gates.sh` skip-count ratchet (a run may not skip more tests than its baseline), not `scripts/ci/pytest_must_not_skip.py`, which only certain companion CI steps use (L1). |
| F10 | A killed run leaves temp state | `git archive` writes nothing to `.git`; the extract lives under pytest's tmp directory. AT-13 proves a leftover `griffe-*` branch does not matter. |
| F11 | A PR drops a FROZEN tier and breaks the name in one diff | Union of base and HEAD tiers (B3a). AT-14. |

## 5. Acceptance tests

All in `tests/sentry/release/test_public_signatures.py`. AT-1 to AT-7, AT-10 and AT-12 to AT-15 build a small package in a temporary git repo (tag `v0.0.1`, then an edit) and call the helper with an explicit stability module, so they do not depend on the real census. AT-9 uses the real base `stability.py` and also feeds its parser a non-literal registry expression to prove the closed evaluator rejects it.

| ID | Case | Expected | Turns red on |
|---|---|---|---|
| AT-1 | Add a required keyword-only parameter `sources` to scoped `f`. One fragment's `Breaking:` line names something else, another line names `` `f` `` but not `` `sources` `` (the #750 shape) | 1 unannounced break: `f ... (sources)` | a mutant that joins all Breaking lines into one text, or that ignores the parameter |
| AT-2 | Same change; one line names `` `pkg.f` `` (root alias spelling) and `` `sources` `` | 0 unannounced | a mutant that matches only the defining path |
| AT-2b | Same change; the line names `f` and `sources` without backticks | 1 unannounced | a mutant that accepts plain text |
| AT-3 | Add an optional keyword parameter | 0 breaks | a mutant that treats every signature diff as a break (a snapshot diff) |
| AT-4 | Parameter removed; positional made keyword-only; default changed; parameter renamed (`a` to `b`, L8) | 4 cases reported with their kinds; the rename is announced by a line naming the function and either `` `a` `` or `` `b` `` | dropping a kind from the allowed set |
| AT-5 | Required parameter added to a function outside the scope (INTERNAL at base and HEAD) | 0 unannounced | a mutant that ignores the tier filter |
| AT-6 | Release-PR shape: no fragments; CHANGELOG has a new `## [0.0.2]` section whose Breaking list names the function and parameter | 0 unannounced | a mutant that reads only `changelog.d/` |
| AT-6b | `## [Unreleased]` holds a `### Breaking for consumers` list | fails with the "use a fragment" message (L3) | a mutant that reads or ignores that list |
| AT-7 | The constructor of a scoped class gains a required parameter; a scoped root name is removed | 2 breaks (the class with the parameter, the removed name) | a mutant without the class-member prefix rule or the removal rule |
| AT-8 | Real history: base `v0.28.2` extract, head `v0.28.3` extract, scope from both trees, Breaking lines = the 0.28.3 Breaking list as released (copied into the test, before the G3 correction) | Unannounced includes `compile_plan (sources)` and `VaultWriter (prepared)`, `VaultWriter (mask_key)` | the regression this row exists for |
| AT-9 | The guard: a live run on HEAD, including base-tier extraction from the real `stability.py` with bare `FROZEN`, `EXPERIMENTAL` and `INTERNAL` names; a parser subcase changes one registry value to a call expression | Green on current main (the pending `freeze-e-dead.md` Breaking line names all five removed names in backticks; checked in section 6.2). Zero unresolved in-scope census names; the 27 INTERNAL lazy PEP 562 exports are excluded. Scope floor: at least the measured count of mapped in-scope objects. The call expression fails closed. | a census walk that returns nothing, a base evaluator that rejects the real bare tier names, or one that accepts a node outside the closed evaluator |
| AT-10 | No reachable tag (temp repo with no tags) | Fails with the fetch message | a mutant that returns "no breaks" when the base is missing |
| AT-11 | `decoy_engine.plan.NO_SOURCES` is FROZEN and `SourceFacts` EXPERIMENTAL in the census; both are the `contracts.column_shape` objects and are named in contract 3.4 | pass | removing either registry row (the existing contract 3.4 census test also goes red) |
| AT-12 | A scoped class whose module sets `Cls.__module__ = "pkg.errors"` (the `_error_base.py` pattern) gains a required `__init__` parameter (H3) | 1 unannounced break naming `Cls` | M5 |
| AT-13 | Load the base while a leftover branch `griffe-v0-0-1` and a stale worktree entry exist in the temp repo (H1) | Runs and reports normally; `git branch --list 'griffe-*'` and `git worktree list` are unchanged after the run | a mutant that uses `load_git` |
| AT-14 | In one diff, delete the FROZEN `TIER_EXCEPTIONS` row for `pkg.sub.g` and add a required parameter to `g` (H4) | 1 unannounced break naming `g` | M6 |
| AT-15 | `SIGNATURE_EXEMPTIONS` row for a cosmetic default rename at the current base tag silences that break; the same row with an older `base_tag` is inert, so the break is reported as unannounced and the stale row itself does not cause a failure (M2) | as stated | a mutant that drops the `base_tag` equality and lets the stale row silence the break |
| AT-16 | The in-scope and excluded kind sets together equal `set(griffe.BreakageKind)` | pass | a griffe upgrade that adds a kind |

Mutations the builder runs on the final head and records in the PR (each red, then restored):

- M1 (the choke-point mutation): match the public name against all Breaking lines joined together and drop the parameter check. AT-1 goes red (and AT-4). AT-8 cannot: the released 0.28.3 list names neither `compile_plan` nor `VaultWriter`.
- M2: drop the class-member prefix rule. AT-7 goes red.
- M3: read Breaking text from `changelog.d/` only. AT-6 goes red.
- M4: take the scope from griffe's own public walk instead of the census tiers. AT-5 goes red.
- M5: build scope paths from runtime `__module__` and `__qualname__`. AT-12 goes red.
- M6: take tiers from HEAD only. AT-14 goes red.

## 6. Established solutions

### 6.1 Search run

Searched for: griffe `check` and `find_breaking_changes`; `cargo-semver-checks`; `pyright --verifytypes`; the Kotlin binary-compatibility-validator and API dump files; API snapshot tests. Also read griffe's `_internal/diff.py` (griffelib 2.3.1) to see what it walks.

| Source | What it does | Fit |
|---|---|---|
| Griffe `griffe check` and `find_breaking_changes()` ([docs](https://mkdocstrings.github.io/griffe/checking/), [guide copy](https://sources.debian.org/src/python-griffe/1.7.3-1/docs/guide/users/checking.md)) | Loads two versions of a package statically (one from a git ref) and yields typed `Breakage` objects: parameter added as required, moved, kind changed, default changed, removed; object removed; kind changed. Its docs say there is no agreed definition of "public", so a project must define it. CI needs the tags. | Chosen. It tells a break from an additive change, which a snapshot diff cannot do. We supply "public" from our census. |
| OpenTelemetry Python `scripts/griffe_check.py` ([source](https://sources.debian.org/src/python-opentelemetry/1.39.1-2/scripts/griffe_check.py)) and other projects' CI checks ([example PR](https://github.com/bagowix/interlock/pull/118)) | A small wrapper around griffe, run in CI against the last release | The pattern followed: a thin wrapper, base = last release. |
| `cargo-semver-checks` ([repo](https://github.com/obi1kenobi/cargo-semver-checks), [Rust project goal](https://rust-lang.github.io/rust-project-goals/2025h1/cargo-semver-checks.html)) | Compares the public API with a baseline release through rustdoc JSON, one declarative lint per break kind; it does not examine type information | Rust only. Confirms the design: baseline = previous release, one rule per break kind, types out of scope. |
| `pyright --verifytypes` ([typing docs](https://typing.python.org/en/latest/reference/quality.html)) | Lists a py.typed package's public symbols and reports how complete their types are | Not a diff tool: it answers "is it typed", not "did it break". Rejected. |
| Kotlin binary-compatibility-validator, now ABI dumps in the Kotlin Gradle plugin ([Kotlin docs](https://kotlinlang.org/docs/gradle-binary-compatibility-validation.html)) | Commits a reference API dump; the check fails when the dump differs; updating it is a deliberate step | The snapshot pattern. Rejected as the primary: it fails on additive changes too, and a builder can refresh the dump in the same diff. Griffe against the release tag has no file to refresh. |

### 6.2 Proof run during planning

Scratch venv, `griffelib==2.3.1` on Python 3.11, against this repository:

- `v0.28.2` to `v0.28.3`: 21 breakages; both loads took 16 to 18 s, the diff 0.2 s. They include `decoy_engine.plan._compile.compile_plan: Parameter was added as required (sources)` and, on `decoy_engine.vault._writer.VaultWriter.__init__`, `mask_key` removed and `prepared` added as required. The rest are INTERNAL (`StrategyContext.__init__`, native protocol providers) or constant values (N2).
- `v0.28.3` to `origin/main`: only the five removals of FREEZE-SURFACE E-DEAD, all named in the pending `changelog.d/freeze-e-dead.md` Breaking line. The sentry lands green.
- The planning run used `load_git`; the build uses a `git archive` extract instead (B2, H1). Dennis measured about 6 s for both loads with griffelib 2.3.1.
- `find_breaking_changes(obj, obj)` on a single function returns nothing (it walks members only). So the sentry diffs the whole package once and filters by path (B3), rather than calling griffe per name.

### 6.3 License and dependency

griffelib is ISC, which is on the allowed list in `scripts/dev/license_policy.json`, and has no runtime dependencies. `griffe` 2.x is a meta package (`griffecli` plus `griffelib`, which pulls colorama). We need only the library, so add `griffelib` to the `dev` extra, not `griffe`. It is dev-only: it does not ship in the wheel or the SBOM. The license inventory does not cover it: `scripts/dev/licenses.py` walks runtime dependencies and the optional runtime extras named in the policy, and excludes the `dev`, `docs` and `lint` extras (its docstring, lines 15 to 17). So no inventory regeneration (L4).

### 6.4 Why some custom code remains

About 160 lines: map our census tiers (base and HEAD) onto griffe paths (griffe cannot know our tiers), extract the base with `git archive`, read the Breaking lines through the existing `stamp_release` grammar, and the exemption table. The AST work parses base `stability.py`, builds a map from its literal tier assignments, and evaluates the three tier registries with literal containers plus names from that map, failing closed on every other node (B3a). No signature formatting.

## 7. Design notes

- Principles: one place per fact. Which names are public and at what tier stays in `contracts/stability.py` plus the census. What a Breaking line is stays in `stamp_release.py`. What a break is belongs to griffe. The new helper only joins them. No new structure that will grow variants.
- Pattern: a fitness-function sentry in `tests/sentry/release/`, beside the census it reads, like `test_frozen_surface_map.py`.
- House style: the helper exposes `extract_base(repo, tag, dest) -> Path`, `scope(base_tree, head_tree, base_tiers, head_tiers) -> Scope`, `signature_breaks(base_tree, head_tree, scope) -> list[Break]`, `unannounced(breaks, breaking_lines, exemptions, base_tag) -> list[Break]` and `pending_breaking_lines(root, base_version) -> list[str]`. `Break` is a small frozen dataclass (`public_names`, `kind`, `parameters`, `path`). `Scope` holds the path map and the unresolved-name list. No flag arguments.
- No baseline file, so no row in `scripts/dev/sentry_registry.toml` (that registry binds baselines only).

## 8. Placement

| New or changed file | Directory | CODEMAP "Where Things Go" row | Sits beside |
|---|---|---|---|
| `tests/sentry/release/test_public_signatures.py` (new) | `tests/sentry/release/` | "Sentry test": release rules in `tests/sentry/release/`, `test_<rule>.py` | `test_public_census.py` |
| `tests/sentry/release/_signatures.py` (new helper) | `tests/sentry/release/` | same row, helper `_<name>.py` | `_census.py`, `_tags.py` |
| `scripts/release/stamp_release.py` (`_split_breaking` becomes public `breaking_lists`) | `scripts/release/` | "Changelog fragments": grammar `parse_fragment` in `scripts/release/stamp_release.py` | existing |
| `src/decoy_engine/plan/__init__.py` (2 re-exports) | `src/decoy_engine/plan/` | "Plan compile and checks" (fan-out freeze at 30; no new module) | existing |
| `src/decoy_engine/contracts/stability.py` (a FROZEN `TIER_EXCEPTIONS` row for `NO_SOURCES`, an `EXPERIMENTAL_OBJECTS` row for `SourceFacts`; `SourceFacts` gets the `Experimental:` docstring marker that `test_experimental_marker.py` checks) | `src/decoy_engine/contracts/` | "Versioned contracts" | existing |
| `changelog.d/signature-sentry.md` (new fragment) | `changelog.d/` | "Changelog fragments" | other fragments |
| `CHANGELOG.md` 0.28.3 section (correction, G3) | repo root | "Changelog fragments" | existing |

`tests/sentry/release/` holds 9 files; 2 more stays well under the fan-out limit.

## 9. Choke point, guard test, mutation

- Choke point: every public signature break passes one comparison, the HEAD tree against the last release tag. It runs in the sentry step that `scripts/dev/gates.sh` runs on every gate (`SENTRY_PATHS=(tests/sentry ...)`) and in the `ci.yml` regression-gate. It also runs on the Dell and Mac test nodes through `vm-run` and `decoy-vm-t3` once they push tags (3.0). A contributor cannot route around it by editing some other file: the inputs are the code itself, the release tag and the tiers at both ends, and there is no snapshot to refresh.
- Guard test: `test_public_signatures.py::test_head_breaks_are_announced` (AT-9), with AT-8 as the fail-before proof on real history.
- The mutation that must turn it red: M1 (match the name against all Breaking lines joined, without the parameter). AT-1 goes red. This is the exact bypass #750 took.

## 9a. Defect classes

From `catalogs/recurring-defects.md` and the plan contract's class list.

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | The failure text holds public names and griffe kind names only (B6), never file content or the Breaking sentence | AT-1 asserts the exact message lines | Print the matched fragment text in the message: the AT-1 message check fails |
| 2 | Cleanup on an exit path | No `load_git`: the base is a `git archive` extract under pytest's tmp directory, so a killed run leaves nothing in `.git` (H1) | AT-13: leftover `griffe-*` branch and worktree entry, run succeeds and leaves both lists unchanged | Swap in `load_git`: AT-13 fails |
| 3 | State and concurrency | The helper keeps no state; module-scoped fixtures hold read-only griffe trees; under xdist each worker extracts into its own tmp directory; nothing is written to the shared `.git`, so parallel worktrees cannot race | AT-13 | Swap in `load_git` |
| 4 | Route parity and silent fallback | One comparison for every route into the gate (gates.sh sentry step, ci.yml regression-gate); a missing tag fails, it never falls back to "no breaks" | AT-10 | M on B1: return no breaks when the base is missing; AT-10 fails |
| 5 | Referential integrity | N/A: no data rows are handled | | |
| 6 | Untrusted producer | N/A: inputs are the repository's own source, tags and changelog; the Breaking text is matched with an escaped name, never compiled as a pattern | AT-2 uses a name with `_` | |
| 7 | Check then use on a path | The base tag is read once and the same ref is passed to `extract_base`, to the base tier read and to `pending_breaking_lines` | Code review on the helper; one `git describe` call | Call `git describe` twice: review finding |
| 8 | Weak tests and overclaimed evidence | AT-8 is the fail-before proof on real history; AT-9 has a scope floor so an empty walk cannot pass; M1 to M6 recorded red; unresolved in-scope census names fail the run | Builder reports the floor count and each mutation result | Empty the scope: the AT-9 floor fails |
| 9 | Refactor drift | One rename: `stamp_release._split_breaking` becomes `breaking_lists`; every caller moves in the same commit, behaviour unchanged | `tests/unit/scripts/test_stamp_release_compile.py` passes unchanged on the renamed function | Leave the old private name as an alias: review finding (pre-GA hard delete) |
| 10 | Frozen contract drift | Additive only: `NO_SOURCES` (FROZEN) and `SourceFacts` (EXPERIMENTAL) on `decoy_engine.plan`, named in contract 3.4 and in `docs/frozen-surfaces.md`. No existing signature changes. A tier dropped in the same diff as a break is still checked (H4) | Existing census and frozen-map sentries; AT-11; AT-14; the new sentry stays green on HEAD | Remove the `NO_SOURCES` row: AT-11 and the contract 3.4 census test fail |

## 9b. Enumerations

### Break kinds (griffe 2.3.1 `BreakageKind`)

| Kind | In scope |
|---|---|
| `PARAMETER_MOVED` | yes |
| `PARAMETER_REMOVED` | yes |
| `PARAMETER_CHANGED_KIND` | yes |
| `PARAMETER_CHANGED_DEFAULT` | yes |
| `PARAMETER_CHANGED_REQUIRED` | yes |
| `PARAMETER_ADDED_REQUIRED` | yes |
| `RETURN_CHANGED_TYPE` | no (N1) |
| `OBJECT_REMOVED` | yes |
| `OBJECT_CHANGED_KIND` | yes |
| `ATTRIBUTE_CHANGED_TYPE` | no (N1) |
| `ATTRIBUTE_CHANGED_VALUE` | no (N2) |
| `CLASS_REMOVED_BASE` | yes |

The allowed set is one frozenset in `_signatures.py`; a griffe upgrade that adds a kind fails a test that compares our two sets (in scope plus excluded) with `set(griffe.BreakageKind)`, so a new kind is a decision, not a silent skip.

### Where the sentry runs

- `scripts/dev/gates.sh` sentry step (`SENTRY_PATHS` holds `tests/sentry`).
- `ci.yml` regression-gate (`tests/sentry`, `fetch-depth: 0`).
- `gate-selfhosted.yml` gate job runs `gates.sh` (`fetch-depth: 0`).
- Dell and Mac test nodes via `~/bin/vm-run` and `~/bin/decoy-vm-t3`, after both push `refs/tags/v*` (3.0).

### Sources of Breaking text

- `changelog.d/*.md` at HEAD, the `Breaking:` first line.
- `CHANGELOG.md` release sections newer than the base tag, the `### Breaking for consumers` bullets.
- Not read: a Breaking list under `## [Unreleased]`; its presence fails the run (L3).

### Public spellings per object

- `<module>.<name>` for each census export (root, `sdk`, subpackages with `__all__`), at the base and at HEAD.
- The griffe `final_target.path` of that name in the HEAD tree, and in the base tree for removals. Never runtime `__module__` (H3).
- Tiers: union of the base `stability.py` and the HEAD census. The base AST evaluator resolves only that file's literal tier names inside literal registry containers and fails closed on every other node (B3a).

## 9c. Reuse inventory

- `tests/sentry/release/_census.py` (`load`, `classify`) and `contracts/stability.py` for the scope.
- `scripts/release/stamp_release.py` (`parse_fragment`, `release_sections`, the Breaking split, `FRAGMENT_DIR`, `CHANGELOG`) for the Breaking text.
- griffelib (`load`, `find_breaking_changes`, `BreakageKind`) for the comparison; `git archive` for the base tree.
- The `gates.sh` skip-count ratchet, so the sentry cannot quietly skip (L1).

## 9d. Frozen contracts touched

| Surface | Owning code | Pinning test |
|---|---|---|
| `decoy_engine.plan.NO_SOURCES` (new FROZEN name), `decoy_engine.plan.SourceFacts` (new EXPERIMENTAL name) | `src/decoy_engine/plan/__init__.py`, `src/decoy_engine/contracts/stability.py` | `tests/sentry/release/test_public_census.py`, `tests/sentry/release/test_frozen_surface_map.py`, AT-11 |
| Signatures of every FROZEN and EXPERIMENTAL name (now checked) | the owning modules | `tests/sentry/release/test_public_signatures.py` |
| Released CHANGELOG 0.28.3 section (corrected, G3) | `CHANGELOG.md` | None yet: `test_released_sections_match_their_pins` pins `releases[1:]`, so the newest section (0.28.3) has no pin and the edit moves none. Its digest is pinned when 0.28.4 is stamped. The breaking ratchet's triage keys for 0.28.3 must still match after the edit (M3). |

## 9e. Pre-mortem

- The sentry is too slow and someone moves it out of the sentry step. About 6 s measured; module-scoped loads; the builder reports the time.
- Test nodes have no tags, every node run is red and the red main baseline hides real failures. Closed by the 3.0 precondition and the required green node run before merge.
- Every release adds noise, so builders learn to paste a Breaking line listing many names. Closed by scope: only FROZEN plus EXPERIMENTAL, constant values excluded. On current main the sentry has zero findings besides the five announced removals.
- A gate runs in a clone without tags and the sentry fails for everyone. Closed by the clear F1 message and the existing `fetch-depth: 0` in every CI job that runs it.
- Griffe reports a false break (a cosmetic default rename, a decorated function). A reviewed `SIGNATURE_EXEMPTIONS` row keyed to the current base tag (B8) silences it until the next release; after the tag changes it is inert and is removed in the first following PR. No false Breaking bullet is written, and neither the release PR nor main is made red by a stale row.
- A stale or leftover `griffe-*` branch from an earlier tool run breaks the sentry. Closed by not using `load_git` (AT-13).
- A griffe release changes `Breakage` attributes. Closed by the ceiling pin `<3` and the enumeration test above.

## 10. Slices

One slice, engine only.

| Slice | Content | Risk | Size |
|---|---|---|---|
| SIG-E1 | `griffelib` dev dependency and lock; `_signatures.py` helper; `test_public_signatures.py` (AT-1 to AT-16); `stamp_release.breaking_lists`; `NO_SOURCES` (FROZEN) and `SourceFacts` (EXPERIMENTAL) exported from `decoy_engine.plan`; the docs below; a fragment; the 0.28.3 correction (G3) | R2 | About 11 files. Source: about 12 lines (`plan/__init__.py`, `stability.py`, the `SourceFacts` marker, the `stamp_release.py` rename). Tests: about 400 lines (helper about 160). Docs: about 40 lines. Lock: one package. New public names: `decoy_engine.plan.NO_SOURCES`, `decoy_engine.plan.SourceFacts`. |

Precondition outside the repo (3.0): `~/bin/vm-run` and `~/bin/decoy-vm-t3` push `refs/tags/v*` (orchestrator, edit a copy then `mv`); the selected node shows `git tag | wc -l` greater than 0, and its run shows the sentry green on the slice head before merge.

Docs in the slice:

- `docs/compatibility-contract.md` 3.4: name `decoy_engine.plan.NO_SOURCES` (FROZEN; the census test `test_every_frozen_package_and_exception_is_named_by_contract_3_4` requires it) and `SourceFacts` (EXPERIMENTAL, contract 3.6). State that the signatures of FROZEN and EXPERIMENTAL names are checked against the last release by the signature sentry, and that a break needs one `Breaking:` line that names the object and, for a parameter, the parameter, both in backticks.
- Contract section 6 (machinery): one bullet for the sentry. Section 9 checklist: no new box. The sentry is mechanical; a box would be a second, weaker copy.
- `docs/frozen-surfaces.md`: narrow `RGF1-KL-4` to "Field types, return types and constant values are not pinned"; add `plan.NO_SOURCES` to the row "Subpackage names section 3.4 lists" (`plan.SourceFacts` gets no row: the experimental table lists root and `sdk` names only, and contract 3.4 names it); add one known-limit row per N5 item, each naming its owning gate or "none".
- `changelog.d/README.md`: a `Breaking:` line names each broken public name and, for a parameter change, the parameter, in backticks; how to add a `SIGNATURE_EXEMPTIONS` row for a false break.
- CLI follow-up (CLI repo, not this slice): the repin imports `NO_SOURCES` from `decoy_engine.plan` once it pins the engine release that carries this slice.

Test depth: T0 the new test file per edit. T1 impact selection plus `tests/sentry` and `tests/unit/scripts` per commit. Full suite once on the merge head (lock and frozen-contract triggers), diffed against the saved main baseline.

## 11. Owner answers (recorded 2026-11-22, from the orchestrator after Dennis's plan review)

- Q1. Should INTERNAL-tier census names also need a Breaking line? Answer: no. INTERNAL tier is exempt (N3). Internal churn (for example `StrategyContext.__init__` in 0.28.3) would make builders write Breaking lines no outside reader needs. The CLI's exact pin and its repin tests catch internal-name drift, and moving CLI imports to public paths (as this slice does for `NO_SOURCES`) fixes that side.
- Q2. Correct the released 0.28.3 notes? Answer: yes, in this slice (G3). Add two Breaking bullets (`` `compile_plan` `` now requires the keyword `` `sources` ``, pass `` `NO_SOURCES` `` when you hold no tables; `` `VaultWriter` `` takes `` `prepared` `` in place of `` `mask_key` ``), and in the E1a entry change "`compile_plan` gains `source_schemas`" to "`compile_plan` requires `sources`". The same sentence's "`capture_physical_plan_inputs` gains `source_loader_schemas`" is correct: checked at `v0.28.3`, `src/decoy_engine/execution/physical/_snapshot.py:73`. No digest pin moves: the ratchet pins `releases[1:]`, so the newest section has none yet (correction to the first draft of this plan). The builder re-runs `tests/unit/test_changelog_breaking_ratchet.py` to show the 0.28.3 triage keys still match.

## 12. Review record

Plan review round 1 (Dennis, griffelib 2.3.1 reproductions): NO-GO, 0 BLOCKER, 4 HIGH, 4 MEDIUM, 8 LOW. All addressed in this revision:

| Finding | Where fixed |
|---|---|
| H1 `load_git` leaves branches and worktrees in the shared `.git` | B2 (`git archive` extract), AT-13, class rows 2 and 3 |
| H2 test-node repos hold no tags | 3.0 precondition, section 10, pre-mortem |
| H3 runtime `__module__` rewrites hide breaks | B3 (griffe paths), AT-12, M5 |
| H4 HEAD-only tiers hide a dropped tier | B3a (union), AT-14, M6 |
| M1 any earlier line announces a later break | B5 (per line, backticks, parameter), AT-1, AT-2b |
| M2 cosmetic default renames | B8 exemption table, AT-15 |
| M3 Q2 premise on the digest pin | section 11 Q2, row 9d |
| M4 known-limits list incomplete | N5, docs list |
| L1 to L8 | F9 and 9c; B3a; G1 and AT-6b; 6.3; F7; B1; G2; AT-4 |
