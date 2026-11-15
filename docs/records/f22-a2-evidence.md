# F22 slice a2: build evidence

Slice a2 of `docs/plans/2026-10-30-f22-publication-replan.md` (revision 11, V1 scope; design 5.2,
class 10): the `decoy-publication/v1` descriptor codec (with the vault `size`), `result_id`, the
request and receipt types, one field declaration for writer and reader, exact stored types,
`re.fullmatch` tokens and version refusal.

## Environment

- Container, Linux, effective uid 0. Lock profile `.venv` (built by `scripts/dev/bootstrap.sh`,
  not re-synced in this slice). `.venv/bin/python -V`: Python 3.10.20. PyArrow 24.0.0,
  DuckDB 1.5.4.
- Branch `feat/f22-a2`. Slice start commit `6bc5bc87` (a1b head). Main baseline: `origin/main`
  `c96e2855`.
- Commits: `765db959` red tests; `ce5a1ac9` production, placement and docs. Code head for every
  check below: `ce5a1ac9`; the commit after it adds only this record.

## Production files and placement

New package `src/decoy_engine/publication/`: `__init__.py` 48, `_descriptor.py` 439, `_types.py`
180 lines (plan 9 row a2: exactly these three). Placement per plan 6.1:

- CODEMAP: the "Publication (descriptor, judge, bind, sink state)" row in "Where Things Go"
  (later modules marked `(target)`), and a key-paths row; `src/decoy_engine/_MAP.md` row.
- `.importlinter` and the `LAYERS` snapshot in `tests/sentry/layout/test_import_layers.py`: the
  exhaustive contract needs every top-level package placed. `publication` goes in tier 2 beside
  `execution` and `vault`, the tier its planned edges need (execution's sink imports it in c1,
  `_vault_order.py` imports `vault` in b1). It sits between `quarantine` and `validation`: the
  file's meta-test `test_a_downward_tier_move_goes_green_only_with_its_snapshot` edits the literal
  ` : verification : vault`, so the tier line keeps that suffix. No ignore line, census number or
  threshold changed.
- `docs/methodology-registry.yaml`: `_descriptor.py` carries a `Pattern:` line (Git content
  addressing plus RFC 8785 canonical JSON), and the registry sentry requires every such module to
  be registered, so it is.
- `tests/unit/publication/` (CODEMAP "Unit tests" row).

## Red first (start commit `6bc5bc87`, tests from `765db959`)

Detached worktree at `765db959`, `PYTHONPATH=<worktree>/src`, run from the worktree root;
`decoy_engine.__file__` printed under the worktree. Command:
`.venv/bin/python -m pytest tests/unit/publication -q -p no:cacheprovider -n 2 -rf --tb=line`.
Result: 107 failed, 0 passed. Every one fails with `ModuleNotFoundError: No module named
'decoy_engine.publication'` (absent API): the tests import the package inside each test, so each
id is recorded, not a collection error. Worktree removed.

| Test id | Count |
|---|---|
| `test_descriptor_strict.py::test_descriptor_canonical_and_strict[*]` | 53 |
| `test_descriptor_strict.py::test_the_base_document_is_accepted`, `::test_refusal_carries_no_value_and_no_chained_parse_error`, `::test_writer_round_trips_through_the_reader`, `::test_writer_sorts_and_escapes`, `::test_writer_refuses_a_bad_operation_id_and_duplicate_paths`, `::test_result_id_is_the_artifacts_only` | 6 |
| `test_descriptor_strict.py::test_writer_refuses_through_the_same_declaration[*]` | 5 |
| `test_descriptor_schema_snapshot.py::test_descriptor_schema_snapshot`, `::test_golden_document_bytes_and_ids` | 2 |
| `test_descriptor_bounded_read.py::test_descriptor_bounded_read`, `::test_deep_nesting_under_the_cap_is_refused_not_raised`, `::test_only_bytes_are_read`, `::test_writer_refuses_over_the_cap` | 4 |
| `test_publication_types.py::test_field_lists_are_the_planned_ones`, `::test_a_valid_receipt_builds`, `::test_summary_drops_the_path`, `::test_request_accepts_int_and_float_timeouts`, `::test_operation_id_is_one_check_for_request_receipt_and_descriptor` | 5 |
| `test_publication_types.py::test_receipt_refuses_unchecked_fields[*]` | 17 |
| `test_publication_types.py::test_artifact_summary_refuses[*]` | 5 |
| `test_publication_types.py::test_request_refuses[*]` | 10 |

No test was green at baseline, so none is characterization. The test documents are built with
`json` and `hashlib` only (`tests/unit/publication/_doc.py`), never with the codec, and the
golden bytes, `result_id` and digest in the snapshot test were written by hand from the plan's
rules before the codec existed.

## Mutations (each applied once on the code head, run, then reverted with `git checkout -- src`)

Runner: `.venv/bin/python -m pytest tests/unit/publication -q -p no:cacheprovider -rf --tb=no`;
the tree was clean after every revert and no commit carries a mutation.

| Mutation (plan source) | Tests that went red |
|---|---|
| `$`-anchored `re.match` instead of `re.fullmatch` for `operation_id` and hex digests (7.2 a2) | 10: `test_descriptor_canonical_and_strict[artifact_sha256_newline]`, `[operation_id_newline]`, `[result_id_newline]`, `[vault_sha256_newline]`; `test_writer_refuses_through_the_same_declaration[sha256-...\n-bad_token]`; `test_writer_refuses_a_bad_operation_id_and_duplicate_paths`; `test_receipt_refuses_unchecked_fields[operation_id-job-42\n]`, `[result_id-...\n]`; `test_artifact_summary_refuses[sha256-...\n]`; `test_request_refuses[operation_id-op-1\n]` |
| `isinstance(value, int)` instead of `type(value) is int` for counts (7.2 a2) | 6: `test_descriptor_canonical_and_strict[artifact_size_bool]`, `[artifact_rows_bool]`, `[vault_size_bool]`, `[vault_entry_count_bool]`; `test_writer_refuses_through_the_same_declaration[size-True-wrong_type]`; `test_artifact_summary_refuses[size-True]` |
| drop the duplicate-key hook (7.2 a2) | `test_descriptor_canonical_and_strict[duplicate_key_top]`, `[duplicate_key_artifact]` (they fall through to `not_canonical`) |
| drop the 1 MiB cap on read and write (class 6) | `test_descriptor_bounded_read`, `test_writer_refuses_over_the_cap` |
| add a descriptor field (`created_by`) to the model and declaration without a snapshot update (class 10) | 43, including `test_descriptor_schema_snapshot`, `test_golden_document_bytes_and_ids` and every hand-built-document cell |
| add `path` to `ArtifactSummary` and fill it in `Artifact.summary()` (class 1) | `test_field_lists_are_the_planned_ones`, `test_summary_drops_the_path` |

## Checks (code head `ce5a1ac9`)

| Command | Tree | Passed | Failed | Errors | Skipped | Other |
|---|---|---|---|---|---|---|
| `.venv/bin/python -m pytest tests/unit/publication tests/fileaccess tests/sentry -q -p no:cacheprovider -n 2 -rfE --tb=no` | `ce5a1ac9` | 6070 | 10 | 56 | 7 | 6143 collected |
| same without `tests/unit/publication` (absent on main) | `c96e2855` (worktree) | 5897 | 10 | 56 | 7 | 5970 collected |
| `.venv/bin/python -m pytest tests/unit/execution tests/integration tests/parity tests/security -q -p no:cacheprovider -n 2 -rfE --tb=no` | `ce5a1ac9` | 12230 | 0 | 6 | 2389 | 37 xfailed |
| same | `c96e2855` (worktree) | 12230 | 0 | 6 | 2389 | 37 xfailed |
| `.venv/bin/ruff check src tests` | `ce5a1ac9` | All checks passed | | | | |
| `.venv/bin/ruff format --check src tests` | `ce5a1ac9` | 2224 files already formatted | | | | |
| `.venv/bin/mypy src/decoy_engine` | `ce5a1ac9` | Success, 789 source files | | | | |
| `GATES_WORKERS=2 bash scripts/dev/gates.sh --keep-going --baseline tests/unit/publication tests/unit/scripts/test_gates_shard.py` | `ce5a1ac9`, baseline `origin/main` `c96e2855` | exit 0 | | | | |

Baselines ran in a detached worktree with the same `.venv` and `PYTHONPATH=<worktree>/src`;
`decoy_engine.__file__` printed under the worktree.

First command, failing ids: identical sets on head and baseline (`diff` empty), 66 ids: the 56
errors of `tests/fileaccess/scratch/test_private_creators.py` (fixture asserts a non-root uid)
and the 10 failures of `tests/sentry/layout/test_import_layers.py` (import-linter is not in
`.venv`; gates runs it in `.venv-layers`). No new failing id; no baseline id now passes.
Collected 5970 to 6143 (+173), by `--collect-only` per file: +107 `tests/unit/publication`
(this slice); +51 `tests/fileaccess/publication` (a1a and a1b, not on main); sentry +15 net:
`test_module_size` +3, `test_deprecation_expiry`, `test_expression_safety`,
`test_validate_no_mutation` +4 each and `test_perf_claim_provenance` +3 (per-module
parametrizations over the new modules of a1b and this slice), `test_methodology_citations` +1
(the new registry entry), `test_package_fanout` +1, `test_private_files` +1, and
`test_ci_config` -6 (main `c96e2855` carries two CI/docs commits this stack does not; not this
slice).

Second command, failing ids: identical on both sides (`diff` empty), the 6 errors of
`tests/unit/execution/test_scratch_root_umask.py` (root precondition). Collected count
unchanged (14662 on both).

Layer gate: `bash scripts/dev/gates.sh --steps layers` on the code tree: 15 passed (the first
placement, `publication` after `vault`, and the second, before `vault`, each failed the meta-test
named above, 14 passed and 1 failed, before the final placement; log directories removed).

gates.sh EVIDENCE (Python 3.10.20, ruff 0.15.22, mypy 2.3.0, pytest 9.1.1, workers 2; the
only uncommitted path was this record): branch `env`, `ruff`, `format`, `mypy`, `sentry` (4985
passed, 0 failed, 2 skipped), `layers` (15 passed), `licenses` (63 passed), `tests` (133 passed:
the 107 slice tests and `test_gates_shard.py`) all PASS. Baseline not rerun by gates because
every branch step passed; failing ids branch=0, baseline=0, branch-only=0. Log directory removed.
The gates run also left 29 `/tmp/gates.*` directories with times inside the run (made by its
test step, likely `test_gates_shard.py`); removing them was refused by the session's permission
classifier, so they remain.

Signature grep: `git grep -l` in `tests/` for `decoy_engine.publication`, `import_layers` and
`LAYERS` (the changed names) finds `tests/unit/publication/*`, `tests/sentry/*` (run by the first
command) and `tests/unit/scripts/test_gates_shard.py` (run in the gates line above).

## Plan differences and decisions

- **Refusal type.** Plan 5.2 says a malformed record "is refused as
  `publication_target_occupied`"; that code and the publication error classes register in a3. A
  new exception class here would trip
  `tests/sentry/test_reason_registry.py::test_every_engine_exception_family_is_classified_or_listed`,
  and a2's files cannot classify one (standing owner decision). So the reader and the type
  checks raise a built-in `ValueError` whose text is `descriptor_refused:<check>` (a closed
  token) or `invalid <field>`, never a value; a3 maps any descriptor refusal to
  `publication_target_occupied`. No new exception family, no `UNCLASSIFIED` entry.
- **Raised outside handlers.** The JSON hooks (duplicate key, non-finite constant, over-long
  integer) record the defect and let parsing finish; the refusal is raised after the `try`, so no
  exception context carries a `JSONDecodeError` (whose `doc` holds the bytes). Checked by
  `test_refusal_carries_no_value_and_no_chained_parse_error`.
- **Stricter than the plan's list, no guarantee changed:** the reader also refuses bytes that are
  not the canonical encoding (`not_canonical`; the writer only ever writes canonical bytes),
  unsorted or repeated artifact paths, deep nesting (`RecursionError` caught as `not_json`), and
  JSON integers longer than 20 digits before `int()` runs (bounded parse cost). The writer
  (`build_descriptor`, `encode_descriptor`) runs the same declaration and document rules and
  refuses a descriptor over 1 MiB, so it cannot bind one the reader would refuse.
- **Paths** are checked component by component with the engine's one component validator
  (`fileaccess._component.is_valid_component`), plus the descriptor's own name refused at the
  root; `/` is the separator. Not a second validator.
- **Values the plan leaves open:** `role` is the closed set `{"table"}` (every planned route binds
  Parquet tables; the quarantine sidecar stays outside the unit, L5); `rows` is a required count;
  counts are bounded at 2^63 - 1; `engine_version` matches `[0-9][0-9A-Za-z.+!_-]{0,63}`;
  `PublicationRequest.lock_timeout_s` defaults to 30 seconds; `CommitReceipt.reason_code` is
  shape-checked (`[a-z][a-z0-9_]{0,63}`) until a3 checks it against the registry; `Outcome` is
  `published`, `already_committed`, `operation_conflict`, `refused`, `failed`,
  `commit_uncertain` (the results of 4.1). `VaultBinding(writer, out)` is typed only; nothing uses
  it before b1.
- The plan's `vm-run`/devbox wording is ignored per the brief; tests ran in this container.

## Not run

- The full suite, the perf suite and the docs build.
- No uid 65534 run: this slice adds no mode or permission behaviour.
- `tests/sentry/layout/test_import_layers.py` outside gates (gates runs it in `.venv-layers`).
- macOS and Windows: the package is pure Python with no platform branch.

## V2-LOG

- `_types.py` keeps the shape checks (`is_operation_id`, `is_hex64`, `is_count`) that the
  descriptor declaration reuses; if a4's managed unit or later outcomes widen the closed sets, the
  schema snapshot must move with them (v1 is frozen at GA).

## Merge of main and the canonical JSON form (2026-11-15)

`feat/f22-a1b` `254be660` (which carries main `f34b398e`, B-6 and #581) merged into a2 as
`7e8e997d`. Conflicts were ledger files only: `.importlinter` and the `LAYERS` snapshot keep
main's move of `subset` to tier 3 plus a2's `publication` in tier 2; CODEMAP keeps main's
`plan/` and `run_result/` rows plus a2's `publication/` row.

Two of main's new sentries flagged `publication/_descriptor.py` on the merge:

- D3 (#581, `tests/sentry/defects/test_canonical_json_choke_point.py`): one canonical JSON owner
  for every digest. The descriptor's own `_canonical` helper (sorted keys, `ensure_ascii=True`)
  fed both the `result_id` digest and the stored bytes. **Owner ruling 2026-11-15:** switch to
  main's form. This deviates from plan 5.2, whose pattern line names "ASCII" canonical JSON:
  the descriptor bytes and the `result_id` input are now
  `decoy_engine._canonical.canonical_json_bytes` (UTF-8 text as-is). Nothing is released, so
  the schema stays `decoy-publication/v1` with no version bump; the strict reader and the 1 MiB
  cap are unchanged, and `_descriptor.py` is on no D3 allowlist.
  - Red first: `e33e19fb` and `4af4ac9c` add `tests/unit/publication/test_descriptor_canonical_form.py`.
    On `7e8e997d` all three tests were red: the bytes differ from `canonical_json_bytes` for a
    non-ASCII path (line 38), the module holds a sorted-key dump site (`['_canonical']`), and a
    path with no UTF-8 form was accepted (`DID NOT RAISE`).
  - Production `15cbb018`: the helper is deleted; `compute_result_id`, `encode_descriptor` and
    the `not_canonical` check in `decode_descriptor` use `canonical_json_bytes` through
    `_canonical_or_refuse`, which turns `CanonicalJsonError` into the closed
    `descriptor_refused:not_canonical` token outside the handler. Behaviour change beyond the bytes:
    an artifact path holding an unpaired surrogate (an undecodable filename byte through
    `os.fsdecode`) was written as a `\udc80` escape before and is now refused as `not_canonical`
    by the writer and the reader, since it has no UTF-8 form.
  - Tests updated with it: `test_writer_sorts_and_escapes` became
    `test_writer_sorts_and_writes_text_as_is` (it pinned the `é` escape; it now pins the UTF-8
    bytes), and `tests/unit/publication/_doc.py` hand-builds with `ensure_ascii=False` and UTF-8.
    The schema golden is ASCII-only, so its bytes, `result_id` and digest are unchanged (comment
    corrected).
  - Mutation (`encode_descriptor` back to the ASCII form, detached worktree, reverted, tree clean):
    red `test_descriptor_bytes_and_result_id_are_the_canonical_form`,
    `test_descriptor_module_has_no_sorted_key_dump_of_its_own`,
    `test_writer_sorts_and_writes_text_as_is` and
    `test_every_sorted_key_dump_outside_the_owner_is_an_allowlisted_document`.
- Snapshot parse owner (`tests/sentry/generation/test_snapshot_parse_single_owner.py`): its surface
  is every module whose text says "snapshot"; `_descriptor.py` names its schema-snapshot test
  (`describe_declaration`), which is genuine, so the docstring stays and the exact map gains the
  module's five sites with reasons: `_parse` (the reader's one `json.loads`) and the field
  declaration's own `.load(raw)` calls (`_check_document`, `build_descriptor`, `decode_descriptor`,
  `load` x3), none of which decodes snapshot bytes.

Checks on the code head (`.venv` re-bootstrapped; Python 3.10.20, PyArrow 24.0.0, DuckDB 1.5.4):
`ruff check`, `ruff format --check`, `mypy src/decoy_engine` (845 files) clean;
`registry_renumber --check --main origin/main` consistent; `check_fragment --base origin/main`
and `ratchet_check` exit 0. `.venv/bin/python -m pytest tests/fileaccess tests/sentry
tests/unit/publication -q -p no:cacheprovider -n 2 -rfE --tb=no`: 6757 passed, 10 failed,
87 errors, 6 skipped; failing ids identical to main `f34b398e`'s for `tests/fileaccess
tests/sentry` (the 56 + 31 root-only errors and the 10 `test_import_layers` failures).
