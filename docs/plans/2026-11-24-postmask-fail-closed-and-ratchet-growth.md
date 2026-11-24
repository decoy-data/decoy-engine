# Post-mask fail-closed and ratchet growth guard

Status: plan

Date: 2026-11-24. Rows: POSTMASK-FAIL-CLOSED (CLI `docs/roadmap/groups/trust.md`) and
RATCHET-GROWTH (CLI `docs/roadmap/groups/health.md`).

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`profiles/local-operations.md`, `bugfix.md`, `testing.md`, `workspace-and-vcs.md`,
`cross-cutting-concerns.md`, `architecture.md`, `reuse-first.md`, `proportionality.md`.

Part 1 cites engine #784 at `224a0102d`. Part 2 records its own engine and CLI revisions.

## Slices

| Slice | Repo | Risk | Size | Depends on |
|---|---|---|---|---|
| PM-1a verification ownership and grading | engine | R1 | 1.5 days, about 8 source and 3 test files, including declaration relocation | none |
| PM-1b canonical cell keys and Arrow facts | engine | R2 (integrity) | 3 days, about 6 source and 4 test files, including property tests | PM-1a |
| PM-1c execution ownership consumers | engine | R2 (masked output) | 2 days, about 8 source and 3 route test files | PM-1a, after PM-1b for final route parity |
| RG-E1 registry integrity | engine | R2 | one day | none |
| RG-E2 bounds carry a max or min | engine | R2 | one day | RG-E1 |
| RG-E3 gate runs the base checker | engine | R2 (CI) | half a day | RG-E2 |
| RG-C1a CLI integrity and base run | CLI | R2 (CI) | one day | RG-E3 merged |
| RG-C1b CLI bounds | CLI | R2 | one day | RG-C1a |

The PM slices can proceed independently of RG-E1. The RG slices merge in table order.
Revised after plan review round 1 (2026-11-24); owner decisions are recorded at the end.

# Part 1. POSTMASK-FAIL-CLOSED

## Problem

PR #784 reached round 3 at engine head `224a0102d`. All Part 1 references use that head.
Source paths start at `src/decoy_engine/`. Bare post-mask filenames are in
`verification/postmask/`. Bare test filenames are in `tests/unit/detection_verification/`.

- **V1.** A passthrough entry hides a failed comparison on a sibling that a joint mask writes.
  The same exemption applies when the writer set is unknown. Verification also misses child
  keys that execution rewrites. See `residual_pii.py:513-531`, `_column_facts.py:455-469`,
  `execution/_column_access.py:175-179` and `execution/_chunked_carry.py:242-250`.
- **V1.** Frame and batch identity counts disagree on lists with nulls and reordered maps.
  The batch identity path converts Arrow to pandas. The shared helper freezes dicts in insertion order.
  Its pandas `map` can round adjacent large integers in a nullable object column to the same
  float. See `_column_facts.py:209-212,238-268,377-381` and `residual_pii.py:175-190`.
- **V1.** A surviving email under `hash` already grades `fail`. An unknown source distinct
  count can turn it into `error` because the overrides differ before the base grade is applied.
  The verdict then reports a check error instead of a detected failure.
  See `residual_pii.py:299-300,360-367,462-468,555-574` and `_blocked.py:5-8`.
- **DESIGN.** Verification imports execution's private writer helper and adds its own set of named
  columns. Execution already resolves handler outputs and cascade targets.
  See `_column_facts.py:33,455-469` and `execution/_chunked_carry.py:184-199,225-250`.

## Design

### PM-1a. Writer ownership and residual grading (R1)

Move the declaration registry behind a public plan API in `decoy_engine.plan.column_access`.
Execution and verification both import downward (`.importlinter:19-25`).
An execution re-export creates a cycle. Execution imports chunked execution, which imports
a postmask submodule. Package initialization loads residual checks and column facts before
execution finishes (`execution/__init__.py:73`, `execution/_chunked.py:176`,
`verification/postmask/__init__.py:72-73`, `_column_facts.py:33`).
Keep a fresh-interpreter import test for each import order.

Move the declarations, including joint, composite, conditional and table transform targets.
Keep one registry (`execution/_column_access.py:175-179,233-250,339-352,520-532`).
Trace local imports as well as module imports. The module imports nested JSON, errors and
expressions at lines 34-36. It also loads fixed composite outputs and the execution composite
predicate at lines 284 and 368. Move the predicate from `execution/_runner.py:86-98` to the
lower API and reuse it in work-list construction at line 113. Expose the existing fixed-output
and expression declarations through their owning packages. Do not carry an execution import into plan.

Both packages use this query.

```python
written_columns_by_table(
    config: Mapping[str, Any], *, schemas: Mapping[str, Sequence[str]],
    edges: Sequence[RelationshipEdge], registry: ProviderRegistry,
) -> Mapping[str, TableWrites]
```

Use resolved table declarations and field names. Return a state for each configured table,
schema table and edge child. Name the three states `KnownEmpty`, `KnownSet(columns)` and
`Unknown`. A missing result supplies no proof of exemption. Include each direct target unless
its handler guarantees an unconditional no-op. Use the existing passthrough output declaration
(`execution/_chunked_carry.py:168-201`). Move that fact below execution and have the handler consume it. Include non-dispatch siblings, group components,
conditional targets, transform outputs and every cascade child component. A lookup-only parent
contributes no write. Expand bounded wildcards against the table schema. An unresolved writer
makes its table unknown. Unknown reads alone do not (`execution/_column_access.py:520-532`).

Bind the query result to the run at `execution/pipeline/_post_scan.py:512-528`.
Use the resolved plan declarations, source field names, `ctx.graph.edges` and `ctx.registry`.
The pipeline compiles the graph from profiled relationships and resolves the registry once
(`execution/pipeline/_routing_facts.py:98-117`, `execution/_pipeline_context.py:306,397-422`).
Pass ownership through verification's internal assembly for resident, deferred and staged checks.
Execution already passes those edges and that registry to both resident restoration paths
(`execution/_sequential.py:525-531`, `execution/_pandas_adapter.py:325-331`).

Standalone frame callers provide config and frames (`runner.py:67-75`). Use their field names
and the default provider registry (`_column_facts.py:33-36,465-469`). For these callers,
share the config-to-relationship expansion and graph builder used by execution
(`profile/_source.py:157,370-407`, `execution/pipeline/_routing_facts.py:108-117`).
Factor the graph compilation into a lower public helper if needed. Keep an empty graph for a
proven empty relationship list. If the available metadata cannot resolve writes, use Unknown
for affected tables. Never substitute an empty edge list for an unresolved graph.

Replace verification's `masked_columns`. Apply the exemption before both the detector split
and the identity grade (`residual_pii.py:509-537,575-591`). A passthrough is exempt only
when its table proves the column unwritten. With no detector hit, emit one comparison error
for a possible writer. With a hit, retain the error for every non-exempt column. Keep the
normal detector grade for a proven passthrough (`residual_pii.py:436-444`).

Model source diversity as constant, varied or unknown when comparable rows exist.
Factor the complete known-class grade, including the base grade, gated hits, escalation and
severity ordering (`residual_pii.py:299-300,385-405,534-579`). For unknown diversity, evaluate
both known classes. If the final severities agree, emit that severity once with the base message.
If they differ, emit one value-free error. An output count failure cannot erase a known source
count (`_column_facts.py:397-418`). This slice changes verification decisions only.

### PM-1b. Arrow facts and cell equality (R2)

Both resident gate calls already hold Arrow tables. Today they pass default `to_pandas()`
frames (`execution/pipeline/_post_scan.py:282-290,432-441`). This conversion can round a nullable
integer to float64 and turn a map into a list of tuples. Pass the original tables to a proposed verification entry point, `run_post_mask_arrow`.
Wrap each with `from_table` (`_stream_input.py:49-59`). Preserve the deferred
NER decision, resident models, key findings, distribution input and scratch lifetime
(`runner.py:119-154,243-253`). Materialize pandas only for consumers that require frames.

Use `column_facts` for all routes, including the direct frame check at `residual_pii.py:127-194`.
The report runner already calls it at `runner.py:397-425`. Only external frames need a
frame-to-Arrow adapter. Preserve exact object cells before dtype inference. Replace the text
fallback for comparison at `runner.py:167-217`. For heterogeneous cells that Arrow cannot
infer losslessly, carry per-cell canonical binary keys into the same facts accumulator.
Keep detector input separate from these keys. Preserve the public frame signature.

Define one per-cell key in `postmask/_cell_equality.py`. Use length-delimited canonical
bytes with logical kind tags. Compare exact numbers by reduced numeric value, without
rounding integers through float. Normalize signed zero and decimal scale. Decode dictionary
indices. String width does not affect text equality. Normalize timestamp units without
truncation and compare aware timestamps by instant across time zones. For an unzoned value
with no offset evidence, use the coarser consistent interpretation. Ignore physical type changes
that preserve the logical value. Different known kinds, such as list and map or container and
scalar, differ even when empty or singleton.

Compare lists by position. Encode struct fields by name. Sort map entries by canonical
key and value, retaining duplicates. Recurse at each level. A schema-free dict has unique
keys and uses the same unordered field/value encoding as a struct or unique-key map.
Use schema or paired evidence to identify map pairs. Without schema evidence, give sequences of key/value tuples the unordered map encoding.
Resolve this convention once for both inputs, before comparison or distinct counting.
Ordinary lists retain order. Favor the coarser equivalence when metadata or default pandas
coercion lost a distinction. Count the evidence still present in the frame. Only a truly
undecidable cell raises a comparison error. Ordinary dict and list columns require no schema keyword.

Four decisions consume the key.

1. For residual identity, exclude a row when either top-level cell is null or floating NaN.
2. For `bytes_identical`, compare every aligned position, including missingness. Two top-level
   missing cells match. A one-sided missing cell differs. Inside containers, distinguish null
   from NaN. Two nested nulls match, as do two nested NaNs (`_column_facts.py:259-282`).
3. Make direct policy validation consume the same facts for counts and whole-column equality.
   Replace both `nunique` calls and pandas `equals` (`policy_validation.py:105-106,115-139`).
   Keep policy findings and row-mismatch behavior. Q6's separate policy error-grading work stays deferred.
4. Stream the same binary keys, with top-level missing values represented as SQL NULL, to the
   existing exact DuckDB count on each side. Count across batches with the existing scratch
   and memory limit (`_column_facts.py:325-337,397-418`, `profiling/_scan_integrity.py:552-569`).
   DuckDB distinguishes maps with different entry orders. Encode before DISTINCT in postmask.
   Profiling continues to accept one key column and needs no upward import.

### PM-1c. Execution consumers (R2)

Replace the writer exclusions in `execution/_chunked_carry.py:177-202,225-250` with the same
query result. Passthrough candidates obey the handler declaration and conditional rule.
Untouched candidates come from resolved nodes and cascade edges. Keep the source order,
read set and adapter eligibility checks (`execution/_chunked_carry.py:64-80,261-286`).
Unknown ownership permits no carry or source restoration for that table.

Thread ownership through the planner, unified slice, auto-chunk admission and native schema
rule (`execution/_planner.py:492`, `execution/_unified_slice.py:298`,
`execution/_pipeline_auto_chunk.py:225`, `execution/native/_chunked_schema_rule.py:284-305`).
Retain route-specific schema pins. Check final emitted values on each admitted route.
A schema-only assertion cannot catch a masked sibling overwritten by source restoration.

### Placement

| New file | Location, map and neighbor |
|---|---|
| Writer query and declarations | Add the public subpackage `plan/column_access/__init__.py` beside `plan/checks/`. Move declarations into `plan/column_access/_declarations.py`. Amend the plan row at `CODEMAP.md:268` for this concern. The plan directory has a fan-out freeze. Use its new subpackage for both files. |
| Canonical key | Add `verification/postmask/_cell_equality.py` beside `_column_facts.py`. Extend the postmask map at `CODEMAP.md:129`. Keep the implementation out of `residual_pii.py` (594 lines). |
| Property and fault tests | Add `tests/unit/detection_verification/postscan/test_cell_equality.py` beside `postscan/test_column_facts.py:102`. Follow `CODEMAP.md:303`. The existing `test_column_suite_on_facts.py` has 583 lines. |
| Guard tests | Extend `tests/sentry/post_scan/test_post_scan_choke_points.py:84-109` for the ownership and cell-comparison boundaries. |

## Failure modes

| Failure or input | Required result | Current decision site |
|---|---|---|
| Comparison fails on a joint sibling, FK child or possible wildcard target with its own passthrough entry | One blocking error, even without a detector hit | `residual_pii.py:513-531`, `execution/_chunked_carry.py:244-250` |
| Comparison fails on a proven passthrough | No comparison error. A detector hit keeps its normal info grade | `residual_pii.py:436-444,513-537` |
| Typed conversion or comparison fails after an earlier batch succeeded | Clear partial identity counts for that column. Other columns finish. Propagate pass-through exceptions | `_column_facts.py:378-390,410-412`, `residual_pii.py:180-194` |
| Source missing, unequal lengths, or no comparable rows | No comparison error. Preserve detector-only grading | `residual_pii.py:252-268,534-537` |
| Nested nulls, reordered keys, NaN or adjacent large integers | Both paths return the same reference counts | `_column_facts.py:238-268`, `residual_pii.py:175-190` |
| Source count fails after comparison succeeded | Keep identity counts. Equal final grades stand. Different final grades give one error | `residual_pii.py:538-579` |
| Output count alone fails | Grade with the known source count | `_column_facts.py:400-404`, `postscan/test_column_suite_on_facts.py:508` |

## Acceptance tests

**PM-1a ownership inputs.** Capture the edges and registry passed to verification and execution
for the same config. Compare complete edge tuples, including composite child components.
Assert registry object identity with a custom composite provider. Repeat for the standalone
default registry and for empty, multi-child and parent-only cases. Compare standalone edges
with the compiled run for the same config. Drop one child component to turn this test red
(`relationships/_graph.py:72-96`, `execution/_pipeline_context.py:397-422`).

Run the frame and batch entry points for the round 3 regressions. Use independent expected results.
The current harness and comparison fields are at `test_residual_pii_source_compare.py:286-320`.

- **Writer regressions.** Add a passthrough entry for the joint mask's `zip` sibling. Inject
  a comparison failure with no detector hit. Require exactly one `error` for `zip`. Repeat
  for an FK child key and an unknown wildcard writer. Repeat with a detector hit. Check the
  public query directly for every component of a composite child key and for a read-only parent.
  Keep a sibling table with a proven passthrough quiet. Removing the cascade union or letting
  passthrough win before lookup must fail these tests. See `test_residual_pii_source_compare.py:356-400`
  and `execution/_chunked_carry.py:242-250`.
- **Equality regressions.** An unchanged `[1, null]` counts as one comparable, identical row.
  Reverse a dict's insertion order under a declared map type and under a struct type.
  Both rows stay identical. For nullable object integers, compare `[2**60, None]` with
  `[2**60 + 1, None]`. Expect one comparable row and zero identical rows on each path.
  Keep the existing list-to-scalar case. Restoring pandas `map` must fail the integer case.
  See `_column_facts.py:238-268` and `test_residual_pii_source_compare.py:313-332`.
- **Grading regressions.** Use unchanged hash output with an email hit. Run the same facts with
  source count 1, count 2 and a failed count. Expect one `fail` in all three runs. Repeat with
  a faker case whose final grades differ. Expect one `error` for the failed count. Pin gated
  hits and an output-only count failure. Comparing intermediate overrides must fail the hash
  test. See `residual_pii.py:462-468,538-574` and `postscan/test_column_suite_on_facts.py:414-437,508-520`.
- **PM-1b property test.** Generate paired Arrow schemas and logical rows with Hypothesis
  (`pyproject.toml:182-192`). Include nullable int64 versus float64, string versus large_string,
  dictionary versus plain, timestamp units and time zones, decimal scales, and signed zero.
  Include lists versus maps, container versus scalar, duplicate map pairs, empty containers,
  nested null and NaN, and adjacent integers above 2**53. Generate preserved rows and single-leaf changes.
  Vary source and output batch boundaries independently. Run the actual resident gate, batch
  runner, direct frame check and public frame runner. Supply exact object frames and default
  `table.to_pandas()` frames. Compare against an independent recursive oracle using the
  logical values each input retains. For lossless inputs require identical facts and findings.
  For rounded frames assert the conservative result explicitly. The gate must still distinguish
  adjacent original integers. Compare comparable and identical counts, whole-column equality,
  both distinct counts, failure flags and findings (`test_residual_pii_source_compare.py:286-320`).
  Require one distinct source key for reordered maps in separate batches. Restore raw DuckDB
  DISTINCT or pandas equality and require the corresponding tests to fail.
- **PM-1b comparison guard.** Extend the post-scan sentry to scan normalized Python AST across
  postmask. Flag direct source/output cell comparisons, pandas `equals`, `nunique`, and raw
  cell DISTINCT outside the key path. Include an alias and an extracted local variable in the
  guard fixtures. Permit comparisons of counts, thresholds and schema metadata. Restore the
  direct comparison at `policy_validation.py:131-132` or `_column_facts.py:272-282` to turn it red.
- **PM-1c route parity.** Run each fixture on every eligible route. Compare the ordered
  passthrough names, untouched fields and actual output cells against independent expectations.
  Cover a joint sibling marked passthrough, a custom composite, a conditional target, an
  unbounded writer, an unwritten parent and a rewritten composite child. Keep route-specific
  rejections. Include a source sentinel in each masked output position. Assert the expected
  masked value survives final carry, restoration and native normalization. Remove the child
  exclusion or restore a joint sibling from source and require a red test
  (`execution/_chunked_carry.py:91-105,242-250`, `execution/native/_chunked_schema_rule.py:284-305`).
- **Failure and boundary guards.** Inject a fault at the shared Arrow comparator. Check
  propagation, column isolation, missing input, row mismatch and class-only messages on both
  paths. The key encoder raises only plain exceptions for unsupported cells. A plain
  `ValueError` on a later batch must clear earlier tallies for that column alone. Assert
  that the real unsupported-cell exception fails the `passes_through` predicate. Inject an
  independent engine-family failure at the caller and require propagation
  (`profiling/scan_set.py:307-311`). Seed the exception with a cell value and assert it never appears in the finding.
  Pin the public import and run the layer checks, including a fresh import of each package first.
  Execution already imports postmask. Restoring the private verification import or removing
  the pass-through guard must fail the corresponding test. Import execution, verification.postmask
  and plan.column_access first in separate subprocesses. Resolve the public query and run it in each. See `_column_facts.py:33,378-386`,
  `execution/pipeline/_post_scan.py:53`, `test_residual_pii_source_compare.py:248-273` and
  `tests/sentry/post_scan/test_post_scan_choke_points.py:84-109`.

Run the focused tests and post-scan sentry first. Then run impact tests for execution and
postmask. Record red-before results against `224a0102d` and repeat the listed mutations on the
final implementation head. See `postscan/test_column_facts.py:102`,
`test_residual_pii_source_compare.py:335` and `tests/sentry/post_scan/test_post_scan_choke_points.py:84`.

### Follow-up

| Class | Separate row | Evidence and scope |
|---|---|---|
| DESIGN, existing | Validation post-scan leakage | `validation/post/_scan.py:85-95` enumerates masked columns. `validation/post/_checks/_leakage.py:40-41,58-60` skips passthrough and uses Python cell equality. Migrate this consumer to the public writer query and the canonical key through a verification API in a later slice. |

# Part 2. RATCHET-GROWTH

RG source refs verified with `git show`: engine `3426165fb`, CLI `00ed97b25`.

## Problem

A ratchet list may only shrink unless the owner signs off. The engine and CLI enforce part of this
today: `tests/sentry/_ratchet.py` and `scripts/dev/ratchet_check.py` compare each registered
baseline with the merge base. A grown entry set fails unless an exact-key `approved_growth` row
with a dated decision lists the key. A raised or dropped `max` fails with no approval path at all:
`check()` subtracts approvals from `grown` only, never from `raised` (`_ratchet.py:366-379`; the
CLI `_ratchet.py:303-317` does the same). A ceiling bump the owner signed off can never pass.

Routes that loosen a guard and pass today:

1. Remove a sentry's registry row together with its baseline JSON and its `_baseline_sources`
   row. Removing the row alone already fails ("baseline file is not registered",
   `_ratchet.py:319-321`), and `test_registry_has_no_source_less_sentry` catches a source left
   behind. Removing all three passes: nothing grows.
2. Delete or empty the registry file, with the baselines and sources. Every row reads as removed.
3. Delete a sentry test file. `tests/sentry/test_sentry_manifest.py` only reads the head tree,
   and the head's `OUTSIDE_SENTRIES` can drop the entry in the same diff.
4. Escape a path with `..`. `parse_registry` checks paths with `startswith` (`_ratchet.py:69`).
5. Raise a scalar limit or lower a floor. The scalar bounds are read in the sentries:
   `test_module_size.py:71-81,170`, `layout/test_package_fanout.py:25,69-70`,
   `test_outbound_clients.py:65,321` and `release/test_public_signatures.py:32,342`.
   Three numeric baselines (module-size, log-interpolation, locator-waivers) carry no `max`, so
   `max_raised` cannot see a rise. The module-size docstring (`test_module_size.py:38`) calls its rise rule
   "review-enforced, not machine-enforced".
6. Delete `scripts/dev/ratchet_check.py`. `gates.sh` runs it only `if [ -f ... ]` (a skip meant for
   the baseline worktree), so the gate is green. CI runs the branch's own copy, so a branch can
   edit the checker to pass itself.

Field typos already fail closed and need no new check: a misspelled `approved_growth` gives no
approval, so the growth fails; a misspelled `max` reads as a dropped max, which `max_raised`
fails; a misspelled `moved_from` gives no re-home.

The CLI has routes 1, 2, 3, 4 and 6, and the same raised-max gap. It already has the baseline-file
`created_in` rule, the first-inventory rule, `CEILING_FIELDS` and the moved-field check, and its
`module-size.json` already carries `max`. CI runs `ratchet_check.py --base <PR base sha>` on PRs
(`ci.yml:285`) with the branch's copy.

Source: platform X0a-h H1, H2 and H4 (`decoy-platform`
`docs/plans/2026-11-05-x0a-h-ratchet-hardening.md`, PR #181). Only the plan merged. There is no
platform code to vendor, so the engine builds the mechanism and the CLI ports it. Until RG-E1
merges, the orchestrator checks ratchet growth by hand at each gate.

## Guarantee

After these slices, the gate and CI fail when the diff against the merge base:

- removes an id without a fresh retirement decision or a transfer traceable to that id (RG-E1);
- deletes the registry file or leaves it with no rows;
- deletes a sentry test file (`tests/sentry/**/test_*.py` plus the base's `OUTSIDE_SENTRIES`),
  unless git reports a rename into the sentry set or the head registry adds a fresh `[retired_files]` entry with a dated
  owner decision;
- adds an unknown key to a registry row, or a value that is not a decision string to the
  `[retired]`, `[retired_files]` or `[checker_change]` tables (top-level table names are not a
  closed set);
- names a baseline outside `tests/sentry/baselines/` or a path that is absolute, has a backslash or has a `..` part;
- adds a baseline file with an empty or missing `created_in`;
- raises a `max` or lowers a `min` on any baseline entry, unless an exact-key `approved_growth`
  row new in this diff lists that key;
- drops a key from a `GUARD_KEYS` baseline (`sentry-limits`), on its own row or through a
  whole-id retirement, unless a fresh approval names the old id and exact key (RG-E2);
- names a base commit that does not exist in the repository;
- runs without the checker outside the baseline worktree;
- fails to list or read the base tree, extract its checker or complete its checks;
- fails a base check, except for an approved new registry field under RG-E3.

"New in this diff" has one meaning everywhere. An `approved_growth` row is new when its
(sentry id, key) pair is not among the base approvals; a `[retired]`, `[retired_files]` or
`[checker_change]` entry is new when its name is not in that base table. Rewording a decision that
is already on base does not make it new, so it cannot re-arm an approval.

Adding a key to a `GUARD_KEYS` baseline adds a guard, so it is not growth and needs no approval.

Each decision row new in the diff (`approved_growth`, `[retired_growth]`, `[retired]`, `[retired_files]`,
`[checker_change]`) is printed as a `ratchet: decision ...` line. The sentry step copies these
lines to gate stderr on a pass too (engine `scripts/dev/gates.sh:531,542`),
so the gate reviewer sees every sign-off.

Named limits (known issues, not blockers):

- L-A. A decision row is plain text that anyone with write access can type. V1 relies on the
  report line and gate review (owner decision Q1). The gate reviewer brief adds one step: grep
  the registry diff (`git diff <base> -- scripts/dev/sentry_registry.toml`) for new decision rows
  and check each against OWNER-QUESTIONS.md. SSH-signed approvals and a `merge_check.py` run
  from a main checkout (platform H1) are V2. The V1 threat model covers accidental loosening only.
- L-B. A sentry can be weakened in its test body without touching a baseline or limit (platform
  L3). Review catches this.
- L-C. A limit-like constant nobody lists in `sentry-limits` is not seen. Finding all of them is
  follow-up work.
- L-D. A branch can edit `gates.sh`, a workflow or the head `ratchet_check.py` that starts the base
  run and applies the `[checker_change]` waiver. The base run lowers the impact, every waiver is
  printed, and the `ci-write-scopes` sentry covers workflow writes. A waiver covers only the base schema finding for the named field.
  Branch protection on main remains an owner setting.
- L-E. Platform H4 process hygiene (process-group kill, `flock -o`, bash 3.2, exact workflow `if:`)
  is out of scope except the skip-if-missing fix (owner decision Q4).
- L-F. Runtime single-assignment of ratchet constants (platform AT-RI4) is not checked.

## Established solutions

Search run 2026-11-24: web search "code quality ratchet baseline tool only decrease betterer
phpstan baseline detekt baseline"; codebase search of engine, CLI and platform for ratchet code
(`_ratchet.py`, `ratchet_check.py`, `sentry_registry.toml`, `_baseline_sources.py`,
`layout/_ratchet_cases.py`, the platform X0a-h plan).

Found:

- PHPStan baseline (https://phpstan.org/user-guide/baseline): a snapshot of known errors that only
  shrinks; stale entries are reported so the file holds no dead rows. Pest ratchets (packagist
  `offset-smoker/pest-ratchets`) and Catraca (packagist `b7s/catraca`) apply the same rule to
  metrics. The engine `_ratchet.py` already follows this pattern.
- None of them guards against deleting the baseline, the rule or the checker. They treat config as
  reviewed code, and human sign-off comes from CODEOWNERS plus required review, a branch-protection
  setting rather than a checker feature.
- Closed schemas: JSON Schema `additionalProperties: false` is the standard way to fail unknown
  fields. Each repo supplies its row schema. A key-set check handles unknown fields without a `jsonschema` dependency.
- Path safety: `pathlib.PurePosixPath(...).parts`, rejecting `..`, absolute and backslash paths, is
  the standard library way. It replaces `startswith`.
- Running a trusted copy of the checker: `git archive <ref> <paths> | tar -x` extracts a tree at a
  commit without touching the work tree or `.git`, the same approach CI systems use to evaluate a
  base-branch config.
- `tests/sentry/layout/_ratchet_cases.py` is a case table vendored byte for byte into the CLI and
  pinned by `test_vendored_files.py`. RG-E1 adds integrity cases the same way.

Design follows the shrink-only baseline pattern already in place, extended with the platform
X0a-h H2 list (AT-RI1, RI3, RI5, RI6, RI7). Scalar limits reuse the baseline mechanism (one more
`_baseline_sources` source with `max` or `min`) instead of a second one. Custom code is needed
because no tool covers deletion of the registry, a sentry file or the checker, and the decision
format is house-specific (`owner YYYY-MM-DD reason`, regex `DECISION` in `_ratchet.py`).

## Design notes

- One mechanism for every bound. Scalar caps and floors become entries of a `sentry-limits`
  baseline, approved through `approved_growth` like any other baseline. No `[[limit]]` table, no
  `approved_limit`, no second mirror test.
- One place per fact. The registry TOML stays the one list of sentries and decisions. Limit values
  live in the test constants; `sentry-limits.json` records them and each repo extends its existing mirror test to compare the live bounds.
- `_ratchet.py` is 404 lines and `test_ratchet_check.py` is 652 (over 600), so new rules go in a
  helper module and new test files. `check()` in `_ratchet.py` calls the helper and stays the one
  entry point `ratchet_check.py` runs. No second checker.
- One function per integrity rule, each returning a list of finding strings, the shape
  `reason_findings` and `growth` already return.
- Helpers are loaded by path relative to `_ratchet.py`'s own `__file__`
  (`importlib.util.spec_from_file_location`), the way `ratchet_check.py` loads `_ratchet.py`. A
  base copy extracted to a temp dir therefore loads only the base helpers, never the head's.
- Principles: no new abstraction; new rule functions join an existing pipeline.

Choke point: `_ratchet.check()`, run by `scripts/dev/ratchet_check.py` from the `sentry` gate step
and from CI. Guard tests in `tests/sentry/ratchet/` run `ratchet_check.py` on temporary git repos
with each bypass. Mutations: drop the call to `integrity_findings(...)` in `check()` (the shared-key transfer test goes red); drop `raised -= approved_new` (the raised-max approval test goes red); make
`bound_loosened` ignore `min` (the floor test goes red); make the base run return 0 on an
extraction error (the broken-base test goes red).

## Placement

`tests/sentry/` already has 100 direct `.py` files, so every new file goes in a new
`tests/sentry/ratchet/` sub-package. `_ratchet.py` stays where it is, because `ratchet_check.py`
loads it by that path and the CLI mirrors it.

| New file | Directory | CODEMAP line | Beside |
|---|---|---|---|
| `__init__.py` (empty) | `tests/sentry/ratchet/` | new row, below | `tests/sentry/layout/__init__.py` |
| `_integrity.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/_ratchet.py` (its caller) |
| `_limit_constants.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/_baseline_sources.py` (its caller) |
| `test_integrity.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_ratchet_check.py` |
| `test_bounds.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_ratchet_check.py` |
| `test_base_run.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_bash32_compat.py` |
| `sentry-limits.json` | `tests/sentry/baselines/` | existing baselines | the other baselines |

Map change (engine `CODEMAP.md:292`, CLI `CODEMAP.md:73`): add one "Where Things Go" row, "Ratchet checker helpers and their tests |
`tests/sentry/ratchet/` | private `_<concern>.py` loaded by path from `tests/sentry/_ratchet.py`;
tests `test_*.py` | `scripts/dev/sentry_registry.toml`". No new file goes in `scripts/` (frozen at
26). The CLI mirrors the layout under its own `tests/sentry/ratchet/`.

## RG-E1. Registry integrity (engine, R2, one day)

Changes:

- New `tests/sentry/ratchet/_integrity.py` (about 170 lines, stdlib only):
  - `registry_present(base, head)`: the registry exists at head and has at least one `[[sentry]]`
    row when the base had rows.
  - Replace the union in engine `tests/sentry/_ratchet.py:340-349,380-403` and CLI
    `tests/sentry/_ratchet.py:282-289,318-341` with one transfer check. Use it for both growth
    and removal. With removals in the diff, match each new id's key to one removed id's key.
    Exclude ids with fresh retirement decisions from ordinary transfers. RG-E2 handles guard
    retirements. Require the same key and compare its bounds against that donor. Reject missing or ambiguous donors. Consume each pair (old id, key)
    once. A split can divide one inventory across new ids. It cannot spend one key twice.
    Every removed id must supply at least one matched key or have its own fresh retirement.
    An empty inventory has nothing to transfer. With no removals, keep first inventory.
    RG-E1 starts with an empty `GUARD_KEYS`. RG-E2 adds `sentry-limits`.
  - For both `[retired]` and `[retired_files]`, require the exact id or path to be absent from
    that base decision table. Validate the new decision with the repo's dated-decision and
    reason checks. Rewording an old row cannot retire a restored id or file again.
  - `removed_sentry_files(root, base_sha)`: sentry files in the checked base tree listing
    under `tests/sentry/**/test_*.py` plus the base's `OUTSIDE_SENTRIES`, minus those at
    head. `OUTSIDE_SENTRIES` is read with `git show <base>:tests/sentry/test_sentry_manifest.py`
    and parsed with `ast` (a module-level tuple of string literals). It is never imported, so the
    head copy and pytest are not involved. A base with no `test_sentry_manifest.py` gives an empty
    list. A path `git diff -M --name-status <base> HEAD` reports as renamed passes only when its
    destination is also in the sentry set (`tests/sentry/**/test_*.py` or the head
    `OUTSIDE_SENTRIES`). Others need a `[retired_files]` entry with a dated decision.
  - `closed_keys(head_registry, schema)` checks raw rows against the repo's schema.
    The engine allows `id`, `baseline` and `approved_growth`. RG-C1a supplies the CLI schema.
    Validate the decision strings in `retired`, `retired_files` and `checker_change`.
    Ignore unknown top-level tables for forward compatibility. Implement the field-specific
    input here in RG-E1 so the extracted RG-E2 checker supports the RG-E3 waiver.
  - In both repos, call `safe_path` from `parse_registry` before opening a baseline.
    Reject absolute paths, backslashes and any `..` component. Require the exact
    `PurePosixPath(BASELINE_DIR).parts` prefix and at least one component after it.
    The current directory checks are engine `_ratchet.py:69-70` and CLI `_ratchet.py:90-91`.
  - `new_baselines_dated(base, head)`: a baseline file new in the diff needs a non-empty
    `created_in` (the file-level field all 58 engine baselines and the CLI already carry). Owner
    decision Q7: required for new baselines only, no back-fill.
  - `new_decisions(base, head)`: every decision row at head and not at base, for the report.
- Load the helper relative to `_ratchet.py`. Resolve the commit once. Build one checked
  `git ls-tree -r -t -z --full-tree <sha>` inventory (`-t` lists directories, so a
  directory at the checker path is seen and fails as the wrong type rather than as absent). Treat an optional base path as absent only
  after a successful listing omits it. A listed path must have the expected type and read
  successfully. A registry row naming a missing baseline fails. Fail on listing, blob read,
  decoding or parse errors. Apply this to the registry, baselines, manifest and source lookups.
  Keep "base commit not found" for an invalid ref. Replace the empty-data fallbacks in engine `_ratchet.py:136-147,264,315-316` and CLI
  `_ratchet.py:156-167,197-199,255-256`. Report each new decision from `check()`.
- `scripts/dev/sentry_registry.toml`: add empty `[retired]`, `[retired_files]` and
  `[checker_change]` tables with a one-line comment on the decision format. Fix the stale comment at lines 6-7. Lines 10-11 register the F29 baseline.
- Integrity case table: extend the existing vendored table in
  `layout/_ratchet_cases.py` so RG-C1a parametrizes the same cases.
- CODEMAP row (see Placement). CHANGELOG entry.

Existing tests: no expectation in `test_ratchet_check.py` changes. Replacement and split tests
(`test_split_keeping_the_union_passes`, `test_renamed_baseline_with_extra_key_fails`,
`test_replaced_baseline_with_new_sentry_id_fails`, `test_split_whose_union_adds_a_key_fails`,
`test_a_rename_may_not_raise_a_numeric_max`) keep passing or failing for the same reason, because
each kept key in these fixtures has one donor. Its fixtures write `created_in = "S0"`, so the first
inventory test still passes. The builder runs the file unchanged and reports the result. The file
takes no new tests.

Failure modes:

| Bypass | Expected |
|---|---|
| Registry row, baseline JSON and source row deleted, no `[retired]` entry | Fail, names the id |
| Row renamed to a new id that keeps the keys | Pass (replacement path) |
| Row removed and an unrelated empty sentry added in the same diff | Fail, names the id |
| Sentry file renamed to a path outside the sentry set | Fail |
| `--base` names a commit that does not exist | Fail, "base commit not found" |
| `[retired]` entry with a placeholder reason | Fail, `reason_findings` rules |
| Registry file deleted or emptied | Fail |
| Sentry test file deleted | Fail, names the path |
| Outside sentry file and its `OUTSIDE_SENTRIES` entry both deleted | Fail (base list is read) |
| Sentry test file renamed with `git mv` | Pass |
| Unknown key on a registry row | Fail, names the id and key |
| Baseline path `tests/sentry/../../src/x.json` | Fail |
| New baseline with no `created_in` | Fail |
| Base has no `[retired]` table (first run) | Pass; the tables are optional at base |

Acceptance tests in `tests/sentry/ratchet/test_integrity.py`. Reuse the temporary-git-repo
helpers from `test_ratchet_check.py` by import; do not copy them. Each test is tagged. A
**red-before** test must fail on the base, and the builder records that run. A **pin** test passes
on the base and after; it guards against over-blocking, and the builder does not claim red
evidence for it.

- `test_removed_registry_row_without_retirement_fails` (AT-RI1, red-before): deletes the row and
  the baseline file. For single-id removals, leave a second registered inventory intact.
- `test_removed_row_with_unrelated_empty_new_sentry_fails` (red-before)
- `test_removed_registry_row_with_dated_retirement_passes` (pin)
- `test_row_replaced_by_new_id_keeping_keys_passes` (pin)
- `test_two_removed_ids_cannot_share_one_successor_key` (red-before)
- `test_split_cannot_copy_one_allowance_to_two_successors` (red-before)
- `test_restored_id_requires_fresh_retirement` (red-before)
- `test_restored_file_requires_fresh_retirement` (red-before)
  Keep the old sign-off on base with the restored id or path. Delete it again at head.
- `test_retirement_with_placeholder_reason_fails` (red-before)
- `test_deleted_registry_file_fails` (pin)
- `test_emptied_registry_file_fails` (pin). Both pins leave orphan JSON on disk
  (engine `_ratchet.py:319-321`, CLI `_ratchet.py:259-261`).
- `test_registry_required_after_last_baseline_removed` (red-before). Remove all JSON.
  Delete or empty the registry. Assert the missing-registry or empty-registry finding.
- `test_deleted_sentry_file_fails` (AT-RI3, red-before)
- `test_renamed_sentry_file_passes` (pin)
- `test_sentry_file_renamed_out_of_the_sentry_set_fails` (red-before)
- `test_deleted_outside_sentry_file_with_its_list_entry_fails` (red-before)
- `test_unknown_registry_key_fails` (red-before)
- `test_unknown_top_level_table_is_ignored` (pin)
- `test_dotdot_and_backslash_below_baseline_dir_fail` (AT-RI7, red-before). Put a readable
  file at each path and leave no orphan. Assert the path finding.
- `test_absolute_and_outside_baseline_paths_fail` (pin, both repos). Include a readable
  `docs/example.json`, an absolute path and a sibling directory named `baselines-old`.
- `test_listed_base_registry_read_failure_fails` (red-before). Make only its blob read fail.
- `test_listed_base_baseline_read_failure_fails` (red-before). Use an empty head inventory.
- `test_new_baseline_without_created_in_fails` (AT-RI6, red-before)
- `test_unreachable_base_sha_fails` (red-before)
- `test_new_decision_rows_are_reported` (red-before)
- `test_live_registry_passes_against_origin_main` (pin)

Size: about +170 helper, +15 `_ratchet.py`, +10 TOML, +250 tests, +1 CODEMAP row. No public names.

Test depth: T0 the ratchet test files; T1 impact selection for `tests/sentry`. Escalation trigger:
test tooling (the ratchet is gate tooling), so the merge runs one full suite diffed against the
stored main baseline.

## RG-E2. Bounds carry a max or min (engine, R2, one day)

Merges after RG-E1 and before RG-E3, so the base checker that RG-E3 starts running already knows
the `max` fields this slice adds (H1 order).

Changes:

- `_ratchet.py` (about +20):
  - Raised-max approval: in `check()`, an exact-key `approved_growth` row new in the diff (its
    (sentry id, key) pair is absent from the base approvals) exempts that key from `raised` too,
    and prints "approved raise <key> (<decision>)". An approval already on main does not exempt a
    later raise, even if the branch rewords its decision text.
  - `bound_loosened(head, base)` replaces `max_raised`: a `CEILING_FIELDS = ("max",)` value rose
    or was dropped, or a `FLOOR_FIELDS = ("min",)` value fell or was dropped. Compare each matched transfer against its donor with the same predicate.
  - `GUARD_KEYS = {"sentry-limits"}` (the RG-E1 constant, now filled). For these sentries the
    direction flips, because a key is a guard, not a debt:
    - For a surviving guard id, require fresh `approved_growth` for each lost key.
      Reuse the accepted (id, key) pairs in the stale check at `_ratchet.py:335-338`.
      Exempt that pair on the deletion PR. On later PRs exempt a historical approval only
      if it was on base and the key is absent from both trees. Reject a fresh stray approval.
    - A new guard key tightens the check and needs no approval.
    - Retiring a guard id needs a fresh `[retired]` decision and fresh approvals for every
      old key without an attributable guard successor. Store the approvals under `[retired_growth]`,
      keyed by old id, as arrays of the same `{key, decision}` records as `approved_growth`.
      Use the same parser, freshness comparison and decision report for both locations.
      Compare (id, key) across both base locations so moving an approval cannot refresh it.
      Accept new rows there only for lost keys of a guard id retired in this diff.
      For a guard rename, count a key as retained only in a registered guard successor.
      Match it once by the same transfer and bound rules.
      These matches never excuse the id retirement and never excuse another missing key.
- New `tests/sentry/ratchet/_limit_constants.py` (about 50 lines):
  - `LIMITS`: a dict from `(test file, constant)` to `"max"` or `"min"`.
  - `read_int(file, constant)`: parses the file with `ast` and returns the module-level `NAME =
    <int>` or `NAME: int = <int>` value (`Assign` and `AnnAssign`). A `bool` or a non-int value
    is an error, because `isinstance(True, int)` is true.
- `tests/sentry/_baseline_sources.py` (562 lines, about +15, stays under 600):
  - Add an optional `mins` callable to `Source`, read by the mirror test the way `maxes` is.
  - A `sentry-limits` source over `LIMITS`, keys `<file>::<CONSTANT>`, with `maxes` and `mins`.
  - Add `maxes=` to `module-size` (`in_code("test_module_size.py", "ALLOWLIST").maxes`; values are
    ints), `log-interpolation` and `locator-waivers` (`count_at=0`). See
    `_baseline_sources.py:180,313-319`, `test_log_interpolation.py:71` and `test_locator_hygiene.py:127`.
  - There is no regenerate path (`_baseline_sources.py:535-542` refuses to overwrite). The builder adds `max`
    and `min` to the three baselines and writes `sentry-limits.json` by hand, with `created_in`.
    The mirror test (`test_baseline_registry.py:47-49`, extended to `min`) is the check that the
    hand-written values match the live constants. Register the new file in the TOML. Update the
    module-size docstring sentence that says the rule is review-enforced.
- `tests/sentry/test_baseline_registry.py`: compare each live bound map with the entries carrying that
  field. Require exact integer values. An entry with a floor must not acquire a ceiling.
  Apply the same rule to ceilings with an unexpected floor.
  This lets max and min entries share one baseline (`test_baseline_registry.py:44-50`).
  Replace the hand list in `test_every_numeric_source_declares_its_max` with a walk over every
  `InCode` source: one with any value that is an int, or a tuple holding an int, and not a `bool`,
  must declare `maxes`. The rule does not key off `count_at`, so `locator-waivers` tuple values
  (`_baseline_sources.py:313`, `test_locator_hygiene.py:127` `WAIVERS`) are caught. Add `LIMITS`
  to the `LIST_NAME` pattern (`test_baseline_registry.py:26-28`) so the unregistered-reader scan
  sees the limit list.

Initial `LIMITS` rows. The builder confirms each from the test body before adding it, and records
the line that compares against it:

| Key | Value | Kind | Why it is a bound |
|---|---|---|---|
| `test_module_size.py::GOAL` | 600 | max | entries at or under GOAL need no allowlist row |
| `test_module_size.py::MAX` | 700 | max | hard ceiling for new work |
| `test_module_size.py::MARGIN` | 20 | max | headroom added to a dense ceiling |
| `layout/test_package_fanout.py::LIMIT` | 25 | max | direct-module cap per package |
| `test_outbound_clients.py::WALK_FLOOR` | 146 | min | `>=` floor on files walked (`:321`) |
| `release/test_public_signatures.py::HEAD_FLOOR` | 350 | min | `>=` floor on public names (`:342`) |

`layout/test_scoped_changes.py` LIMIT is not a bound: `LIMIT = 1` at line 20 sits inside the `OLD`
string fixture. It is not listed. `test_date_shift_window_reader.py:47,108` uses the MAX_HITS dict; if no
baseline mirrors it, the builder adds `maxes` to the `date-shift-window-reader` source rather than
a `LIMITS` row.

Failure modes:

| Change | Expected |
|---|---|
| A module-size ALLOWLIST ceiling raised 632 to 650 | Fail via `bound_loosened` |
| The same raise with an exact-key `approved_growth` row new in the diff | Pass, printed |
| The same raise with an approval row already on main | Fail |
| GOAL raised 600 to 650 in the test and in `sentry-limits.json` | Fail unless approved |
| GOAL raised in the test only | Fail, mirror test |
| WALK_FLOOR lowered 146 to 140 | Fail unless approved |
| WALK_FLOOR raised 146 to 150 | Pass |
| `LIMITS` row and its baseline entry deleted | Fail unless approved (`GUARD_KEYS`) |
| The same removal, approved, after it merges to main | Next PR passes (approval is not stale) |
| A new `LIMITS` row added | Pass, not growth |
| `sentry-limits` renamed to `sentry-limits-v2` with GOAL dropped | Fail (no replacement exemption) |
| An approval already on base reworded, and the max raised again | Fail |
| GOAL rewritten as `GOAL: int = 600` | Pass, read via `AnnAssign` |
| GOAL rewritten as `GOAL = True` | Fail, `read_int` refuses a bool |

Acceptance tests in `tests/sentry/ratchet/test_bounds.py` unless noted, tagged as in RG-E1:

- `test_max_raise_with_approved_growth_passes` (H2, red-before)
- `test_max_raise_with_approval_already_on_base_fails` (pin)
- `test_reworded_base_approval_does_not_exempt_a_raise` (pin)
- `test_module_size_ceiling_raise_needs_approval` (red-before)
- `test_log_interpolation_count_raise_needs_approval` (red-before)
- `test_locator_waiver_count_raise_needs_approval` (red-before)
- `test_limit_raise_without_approval_fails` (AT-RI5, red-before)
- `test_floor_lowered_without_approval_fails` (red-before)
- `test_floor_raised_passes` (pin)
- `test_removed_limit_key_needs_approval` (red-before)
- `test_fresh_guard_deletion_passes_then_merged_approval_is_not_stale` (red-before).
  Run the checker on the deletion PR. Commit it as base, keep the row and check the next PR.
- `test_retired_guard_requires_every_lost_key_approval` (red-before). Keep another sentry.
  A fresh id retirement with one key approval missing fails. Add the missing approval and pass.
- `test_added_limit_key_is_not_growth` (red-before)
- `test_guard_sentry_renamed_with_a_dropped_key_fails` (red-before)
- `test_read_int_handles_annassign_and_refuses_bool` (red-before)
- `test_every_numeric_in_code_source_declares_max` (in `test_baseline_registry.py`, red-before)
- `test_limits_list_is_seen_by_the_reader_scan` (in `test_baseline_registry.py`, red-before)
- `test_live_limit_constants_match_recorded_bounds` (red-before). Use a standalone test
  that collects on main. Require the live source and compare its bounds through the mirror.
  After registration also run `test_source_matches_its_registered_baseline[sentry-limits]`.
  That node is post-change coverage only. Main collects from `bs.SOURCES`
  (`test_baseline_registry.py:38-49`). A missing node is no red-before result.

Size: about +20 `_ratchet.py`, +50 helper, +15 `_baseline_sources.py`, +8 TOML, three regenerated
baselines and one new one, +200 tests. No ceiling is raised.

Test depth: T0 the ratchet, baseline-registry and module-size tests; T1 impact selection. Same
test-tooling trigger as RG-E1; it can ride the same merge train.

## RG-E3. Gate runs the base checker (engine, R2 for CI, half a day)

Starts after RG-E2 merges.

Changes:

- Add `--with-base` to `scripts/dev/ratchet_check.py`. Resolve the base once before the
  head check. Pass the same sha and RG-E1 tree inventory through the run.
  - Fail an invalid commit or failed tree listing. Skip only the base run if the successful
    listing omits the exact checker path. Print "ratchet: base has no checker, base run skipped".
    A listed checker must be a readable regular blob. A failed probe never proves absence.
  - Extract `git archive <sha> scripts/dev tests/sentry` into a `TemporaryDirectory`.
    Check the archive command and unpack with the data filter. Run the extracted checker
    with `--root <head root> --base <sha>`. Load helpers relative to the extracted checker.
    Every read, extraction, import, launch or runtime failure fails, even with a waiver.
  - Require the unwaived head check to pass. Scope a fresh `[checker_change]` decision to one added registry field. Use the field
    name as its key. Require an edit to the checker entry point, `_ratchet.py` or a loaded
    ratchet helper. Require the same ids in both registries and
    no baseline edit. The only sentry-row edits allowed are additions of that field to
    existing ids. Check each (id, field) against the actual diff. Reject any other row edit.
  - In RG-E1 give the base checker one optional input for those exact (id, field) pairs
    through its child process environment. Set it only for the extracted run after validation.
    Strip inherited waiver input before the head check in both gate and CI. In `closed_keys`, omit only the corresponding
    unknown-field finding and report each use as "waived by checker_change".
    All other checks run on the real head, including sentry-file retirements. Never turn
    a nonzero process exit into success. Older checkers run with the existing flags and
    can pass a schema change only if they already accept it.
- `scripts/dev/gates.sh` sentry step (`gates.sh:491`): `label` is a local in `run_steps`, so pass it
  into the `bash -c` string as an argument (`env GATE_LABEL="$label"` or a positional). Skip a
  missing checker only when the label is `baseline` and a successful listing of that tree
  proves the checker path absent. A listed but missing worktree file fails. On any other tree, a missing
  `scripts/dev/ratchet_check.py` prints "ratchet checker missing" and fails. Call
  `ratchet_check.py --with-base` on the branch tree. On the `baseline` label call it without
  `--with-base`. Older checkers accept only `--root` and `--base`
  (engine `scripts/dev/ratchet_check.py:37-41`). One shell line; the CLI reuses the same invocation (L7).
- After the step, copy the `ratchet: decision ...` and "waived by checker_change" lines from the
  step log to gate stderr even when the step passes, so the gate reviewer sees them (L-A).
- `.github/workflows/gate-selfhosted.yml` already runs the `sentry` step, so no workflow edit is
  planned (`.github/workflows/gate-selfhosted.yml:84-85`). If one turns out to be needed, the `ci-write-scopes` sentry applies.

Failure modes:

| Change | Expected |
|---|---|
| Branch deletes `ratchet_check.py` | Fail |
| Branch edits `_ratchet.py` so `check()` returns nothing, and grows a baseline | Base copy fails the growth |
| Branch empties `integrity_findings` in the head helper and deletes a registry row | Base copy (its own helper) fails |
| Head adds a new registry-row key with a matching checker change and a `[checker_change]` row | Pass, waiver printed |
| The same without a `[checker_change]` row | Fail |
| This slice's head run by the RG-E2 base checker | Pass (the `[checker_change]` table is known since RG-E1) |
| Base has `ratchet_check.py` but it cannot be extracted or crashes | Fail |
| Base has no `ratchet_check.py` | Skip, one printed line |
| Base sha does not exist | Fail, "base commit not found" |
| `git archive` fails while `tarfile` reads a partial stream | Fail |
| Diff has a `[checker_change]` entry and also edits a baseline | Fail |
| Passing gate with a new decision row | Pass, decision line on gate stderr |
| Baseline-label run | Base checker runs without `--with-base` |
| Baseline worktree with no checker | Skip, as today |

Acceptance tests in `tests/sentry/ratchet/test_base_run.py`, tagged as in RG-E1. They run the
sentry step command or `ratchet_check.py --with-base` on a temporary repo, using the subprocess
harness in `test_ratchet_check.py:61-72`. For negative cases run the branch gate command and
assert the specific failure. An argparse error for an unknown flag is no red-before proof.

- `test_missing_checker_fails_outside_baseline_tree` (red-before)
- `test_missing_checker_skips_in_baseline_tree` (pin)
- `test_base_checker_catches_growth_hidden_by_branch_checker_edit` (red-before)
- `test_base_checker_ignores_tampered_head_helper` (H6, red-before)
- `test_new_registry_key_with_checker_change_passes_base_run` (H1, red-before)
- `test_new_registry_key_without_checker_change_fails_base_run` (red-before)
- `test_checker_change_with_a_baseline_edit_fails` (red-before)
- `test_failed_tree_listing_never_skips_base_checker` (red-before)
- `test_listed_checker_read_error_never_skips` (red-before)
- `test_schema_waiver_cannot_hide_archive_failure_or_crash` (red-before)
- `test_schema_waiver_cannot_hide_sentry_file_retirement` (red-before). Include the valid
  field addition and delete an unrelated sentry. Disable the head retirement check to
  prove the extracted checker still rejects the deletion.
- `test_schema_waiver_rejects_another_row_edit` (red-before)
- `test_broken_base_checker_fails` (M5, red-before): the base has `ratchet_check.py` but its
  `_ratchet.py` has a syntax error
- `test_unreachable_base_sha_fails_with_base` (red-before)
- `test_base_checker_absent_skips_with_message` (red-before)
- `test_decision_lines_shown_on_a_passing_gate` (red-before)
- `test_baseline_label_runs_without_with_base` (pin, engine `gates.sh:474,491`, CLI `gates.sh:269`)

Size: about +55 `ratchet_check.py`, +12 `gates.sh`, +180 tests.

Test depth: T0 the new test file and `test_bash32_compat.py`; T1 impact selection; the gate runs
`gates.sh --keep-going --steps env,ruff,format,mypy,sentry` on the exact head. Test-tooling
trigger: full suite once at merge.

## RG-C1a. CLI integrity and base run (CLI, R2 for CI, one day)

Starts after RG-E3 merges, so the CLI ports reviewed code.

- `tests/sentry/ratchet/_integrity.py`: port from the engine. Keep the CLI's decision grammar
  (`src/decoy/distribution/release_identity.py:58`) and its existing
  baseline-file `created_in` rule (`_ratchet.py:274-275`). Pass the CLI row schema into
  `closed_keys`. Add required `kind` from `_baseline_sources.py:31`. Require `consumer`
  on JSON rows and forbid it on other kinds. Keep `approved_growth` optional for all kinds.
  Use this one schema in both the checker and registry tests. Keep the consumer-to-loader
  check (`test_baseline_registry.py:96-103,291-314`). Update the CLI fixture row writers
  (`test_ratchet_check.py:46-47,180,483,561`) to emit a valid kind. Also update
  `tests/sentry/cli_text/test_error_emitter_ratchet.py:22`: its row needs `kind = "from_scan"` for
  the pass cases at `:68` and `:73`. `tests/sentry/test_lint_debt.py:50` copies the checker into a
  scratch tree; copy `_integrity.py` with it so the scratch checker can load `safe_path`.
  Test: a directory at `scripts/dev/ratchet_check.py` in the base tree fails the gate.
  Pin the shared case table byte for byte (`layout/test_vendored_files.py:44-48`).
- `tests/sentry/_ratchet.py` (342 lines): load the helper by path; call it from `check()`; replace
  `startswith`.
- `scripts/dev/sentry_registry.toml` (201 lines): `[retired]`, `[retired_files]`,
  `[checker_change]`.
- `scripts/dev/ratchet_check.py`: the same `--with-base` flag. The CLI base extraction adds
  `src/decoy/distribution/release_identity.py` to the `git archive` paths, because the CLI
  `_ratchet.py` loads it by path (`tests/sentry/_ratchet.py:52-60`).
- `scripts/dev/gates.sh:269` and `.github/workflows/ci.yml:285` ("Baselines only shrink"): both
  call the same `ratchet_check.py --with-base --base <sha>` line; no second inline copy of the
  shell. In `ci.yml` the step keeps its step-level `if: github.event_name == 'pull_request'`; the
  lane sentry refuses a job-level `if`. Pass `label` into the `gates.sh` `bash -c` string as in
  RG-E3.
- CHANGELOG entry.

Port the RG-E1 and RG-E3 behavior cases. Use valid CLI rows in the shared fixtures.

- `test_live_cli_registry_kinds_and_consumers_pass` (pin). Run the CLI checker on the live
  registry, including JSON rows (`scripts/dev/sentry_registry.toml:7-17`, kind definitions and a
  JSON row) and recomputed rows (`:91-94`).
- `test_cli_integrity_rejects_invalid_kind_or_consumer` (red-before). Run the checker
  on a missing or unknown kind, a missing JSON consumer and a consumer on a recomputed row.
- `test_new_baseline_without_created_in_fails` is a CLI pin (`_ratchet.py:274-275`).
- `test_ci_runs_base_checker_on_pull_requests` (red-before). Check the command and its
  step-level PR condition (`.github/workflows/ci.yml:283-285`).

Size: about +250 helpers and `ratchet_check.py`, +15 TOML, +25 `_ratchet.py`, +10 `gates.sh`,
+3 `ci.yml`, +250 tests.

## RG-C1b. CLI bounds (CLI, R2, one day)

Starts after RG-C1a merges.

- `tests/sentry/_ratchet.py`: the raised-max approval (an exact-key `approved_growth` row new in
  the diff), `FLOOR_FIELDS = ("min",)` beside the existing `CEILING_FIELDS`, and `GUARD_KEYS`.
- `tests/sentry/ratchet/_limit_constants.py`: port, with the same `AnnAssign` and bool rules.
- Register `sentry-limits` as a recomputed source with a CLI reader and a `created_in`
  entry (`test_baseline_registry.py:96-107,116-125`, `_baseline_sources.py:99-106`).
  Extend `test_recomputed_keys_match_the_registered_baseline` at its existing assertion.
  Keep key equality. For a numeric reader compare every live key's field and integer value
  to its recorded `max` or `min`. Reject a missing, extra, wrong-direction or non-integer
  bound, including bool. Read live values with the RG-E2 reader and its one `LIMITS` map.
- Audit other CLI numeric sources for missing recorded bounds. Start with the 800-line
  module size and 25-module fanout ceilings (`layout/test_module_size.py:19,42`,
  `layout/test_package_fanout.py:20,54-55`) and the release floors of 1400 and 7
  (`release/test_retired_name_residual.py:270,311`, `release/test_tag_census.py:16,22`).
  Keep the existing CLI ceiling fields and moved-field check (`_ratchet.py:48-49,175-194`).

Port the RG-E2 guard, approval and bound cases using CLI sources. Include both PRs of
the guard-deletion test and the whole-id case. Engine-only source tests stay in RG-E2.

- `test_cli_mirror_rejects_constant_only_loosening` (red-before). In a scratch tree
  install the numeric reader and a matching baseline. Seed a reader in the existing
  mirror fixture on main so the test collects and exercises its key comparison.
  Run that same mirror before and after raising only the module-size constant. Repeat
  with only the tag-census floor lowered. Keep the keys and JSON byte-identical.
  Assert the mirror names the mismatched key. Main's key-only mirror accepts both edits
  (`test_baseline_registry.py:121-125`).
- `test_module_size_ceiling_raise_needs_approval` is a CLI pin. The recorded max exists
  (`baselines/module-size.json:4-8`) and the checker rejects the raise (`_ratchet.py:312-317`).
- `test_reworded_base_approval_does_not_exempt_a_raise` stays a pin in both repos.
  Main already rejects that raise (engine `_ratchet.py:375-379`, CLI `_ratchet.py:312-317`).

Size: about +20 `_ratchet.py`, +50 helper, +15 sources, +8 TOML, one new baseline, +180 tests.

Test depth (C1a and C1b): T0 the CLI ratchet tests; T1 impact selection. Triggers: CI config and
test tooling, so one full CLI suite at each merge, diffed against the stored main baseline. Use
`gates.sh --full`.

# Defect classes

From the plan contract's class list (classes 1 to 10, checked by `~/bin/plan-lint`).

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | PM-1b: the shared batch facts record only the error class (`_column_facts.py:378-386`). RG: findings name ids, paths, keys and numbers from the repo's own registry, never file content | PM-1 AT asserts no cell value in the message | Put `str(exc)` in `identity_error`: the message check fails |
| 2 | Cleanup on an exit path | RG-E3 extracts the base checker into a `tempfile.TemporaryDirectory` context, removed on every exit; RG tests use pytest `tmp_path` repos; nothing is written to the shared `.git` (`git archive` reads only) | `test_broken_base_checker_fails` checks the temp dir is gone after a failing run | Replace the context with `mkdtemp`: the leftover-dir check fails |
| 3 | State and concurrency | The ratchet helpers keep no module state; each call reads base with `git show` and head from the tree. PM-1 adds no state | Tests run under xdist with separate `tmp_path` repos | N/A: no shared state to mutate |
| 4 | Route parity and silent fallback | PM-1b: frame and batch adapters feed one Arrow facts path (`runner.py:397-425`). RG: gates.sh and CI call the same `ratchet_check.py --with-base`; a missing checker fails outside the baseline tree; a broken base run fails instead of skipping | PM-1b property and fault tests, extending `test_residual_pii_source_compare.py:339-354`; `test_missing_checker_fails_outside_baseline_tree`; `test_broken_base_checker_fails` | Discard the comparison error in `_column_facts.py:378-386`; restore the unconditional `-f` skip; return 0 on extraction error: each test fails |
| 5 | Referential integrity | RG: a registry row's `baseline` path must exist and be safe; a `sentry-limits` key must resolve to a live int constant (mirror test). PM-1a includes each cascade child component. PM-1c uses ownership before restoring source fields (`execution/_chunked_carry.py:244-250`) | `test_dotdot_and_backslash_below_baseline_dir_fail`; `test_source_matches_its_registered_baseline[sentry-limits]` | Revert `safe_path` to `startswith`: the path test fails |
| 6 | Untrusted producer | N/A for V1: inputs are the repo's own registry, baselines and git history (V1 threat model, accidental only). Decision rows are parsed with the anchored `DECISION` regex using `fullmatch` | A decision row with a trailing newline is refused | Swap `fullmatch` for `match` with `$`: that case passes and the test fails |
| 7 | Check then use on a path | `check()` and `--with-base` verify `<base>^{commit}` exists; `ratchet_check.py --with-base` resolves the base sha once and passes the same sha to every `git show`, `git ls-tree`, `git archive` and the base run | Code review on `ratchet_check.py` | Resolve the merge base twice: review finding |
| 8 | Weak tests and overclaimed evidence | Every AT is tagged red-before or pin; each red-before AT is run red on the base first, and pins are never offered as red evidence; `test_removed_registry_row_without_retirement_fails` deletes the baseline file too so it is red before; `test_live_registry_passes_against_origin_main` keeps the real repo in the loop; the numeric-source walk replaces a hand list | Builder report lists each red-before result and each mutation | Return an empty list from `integrity_findings`: the shared-key transfer test fails |
| 9 | Refactor drift | PM-1b replaces the frame comparison at `residual_pii.py:175-194` with batch facts; `max_raised` becomes `bound_loosened` with every caller updated in the same slice | `postscan/test_column_facts.py` and `test_ratchet_check.py` pass unchanged | N/A |
| 10 | Frozen contract drift | PM-1a adds a plan API. PM-1b preserves the public frame call and report shape (`runner.py:67-75`) | Existing census sentries stay green | N/A |

## Recurring defect catalog (11 classes)

Checked against `/home/cam/dev-rules/catalogs/recurring-defects.md`.

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | `DECISION` uses `fullmatch`; `safe_path` works on path parts |
| 2 | Strict wire and stored types | `read_int` refuses `bool` and non-int values; `_max_of` already checks `isinstance(..., int)`, and the builder makes it refuse `bool` too |
| 3 | No exception context | N/A: nothing is re-raised with a cause |
| 4 | Versioned read models | The base run calls the base checker with existing flags only; new registry tables are optional at base; a new registry key needs `[checker_change]` (H1) |
| 5 | Normalized guard scanners | `OUTSIDE_SENTRIES` and `LIMITS` constants are read with `ast` (`Assign` and `AnnAssign`), never by regex |
| 6 | Private modules | `passes_through` comes from the public `decoy_engine.profiling` |
| 7 | No hidden CI failures | The only skip is "base has no checker", proved by a successful tree listing; a missing base commit, an archive or extraction failure or a base run failure fails; the missing-checker skip is limited to the baseline label; decision lines reach gate stderr on a pass |
| 8 | One input, one trust class | N/A: one input class (repo files) |
| 9 | Mutations on the final head | The builder reruns the listed mutations after the last code change and records the head |
| 10 | Allowlisted helpers are still checked | N/A: no sentry allowlist gains a helper |
| 11 | No raised caps | No ceiling is raised; `_baseline_sources.py` stays under 600; `test_ratchet_check.py` takes no new tests |

# Enumerations

### Exit paths

- PM-1b aligns by position. Missing input, unequal row counts and zero comparable rows give
  no residual identity evidence (`residual_pii.py:252-268`, `_column_facts.py:360-375`).
  A failed comparison clears partial counts for its column. A count failure preserves identity.
  Classified exceptions propagate (`_column_facts.py:325-337,378-386,397-418`).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:305`): returns findings and report lines;
  `ratchet_check.py` exits 1 on any finding and 2 when it has no merge base.
- `ratchet_check.py --with-base` skips the base run only on proven checker absence.
  It fails on any read error, extraction error, crash or remaining finding. A successful
  schema waiver prints the exact field and id. All independent checks must pass.
- Engine sentry step (`scripts/dev/gates.sh:491`): checker present (run, fail on non-zero); checker
  missing with label `baseline` (skip); checker missing with any other label (fail).

### Routes

| Route into the check | Where | Slice |
|---|---|---|
| Direct frame check and report runner | `residual_pii.py:127-194`, `runner.py:119-129` | PM-1a, PM-1b |
| Resident and staged Arrow facts | `execution/pipeline/_post_scan.py:285-286,435-436`, `runner.py:132-155,397-425` | PM-1a, PM-1b |
| Engine local gate and `gate-selfhosted.yml` branch pushes | `scripts/dev/gates.sh:491` | RG-E1 to RG-E3 |
| CLI local gate | CLI `scripts/dev/gates.sh:269` | RG-C1a, RG-C1b |
| CLI PR CI "Baselines only shrink" | CLI `.github/workflows/ci.yml:285` | RG-C1a, RG-C1b |

### FK shapes

- For single-column and composite edges, include every child component. Protect these fields during restoration
  (`execution/_chunked_carry.py:244-250`).
- For multiple children, include the components of each child. A lookup-only parent adds no write
  (`profile/_source.py:370-407`, `execution/_chunked_carry.py:249-250`).

### Fields

| Field | Where | Change |
|---|---|---|
| `ColumnFacts.identity_error` | `_column_facts.py:182` | frame and batch already record this field. PM-1b supplies both through one accumulator (`residual_pii.py:180-185`, `_column_facts.py:378-386`) |
| `[[sentry]]` row keys (RG-E1 and RG-C1a) | `scripts/dev/sentry_registry.toml` | one closed schema per repo |
| `[retired]`, `[retired_files]`, `[checker_change]` | registry | new tables (all in RG-E1), `key = "owner YYYY-MM-DD reason"`; top-level table names stay open |
| `[retired_growth]` | registry | RG-E2 stores lost-key approvals by retired guard id |
| Baseline file `created_in` | `tests/sentry/baselines/*.json` | required on baseline files new in the diff |
| Baseline entry `max` | three baselines | added (RG-E2) |
| Baseline entry `min` | `sentry-limits.json` | new floor field (RG-E2) |

### Output surfaces

- Residual comparison-error message (`residual_pii.py:477-482,575-579`): exception class name only.
- Ratchet findings and decision report lines on the stdout of `ratchet_check.py`: ids, paths, keys,
  numbers and the decision text the owner wrote. No file content.
- The base-run lines: "base has no checker", "waived by checker_change", and the base findings.
- The sentry step's "ratchet checker missing" line.

### Loosening forms the checker must see

| Form | Slice | Test |
|---|---|---|
| Registry row and baseline removed | RG-E1 | `test_removed_registry_row_without_retirement_fails` |
| Registry file deleted or emptied | RG-E1 | `test_deleted_registry_file_fails`, `test_emptied_registry_file_fails` |
| Sentry file deleted (inside `tests/sentry/` and the outside list) | RG-E1 | `test_deleted_sentry_file_fails`, `test_deleted_outside_sentry_file_with_its_list_entry_fails` |
| Unknown registry key | RG-E1 | `test_unknown_registry_key_fails` |
| Unsafe path (`_ratchet.py:69` uses `startswith` today) | RG-E1 | `test_dotdot_and_backslash_below_baseline_dir_fail` |
| Baseline count raised with no `max` | RG-E2 | the three `*_raise_needs_approval` tests |
| Scalar cap raised, floor lowered, limit key removed | RG-E2 | `test_limit_raise_without_approval_fails`, `test_floor_lowered_without_approval_fails`, `test_removed_limit_key_needs_approval` |
| Checker deleted, edited or its helper emptied | RG-E3 | `test_missing_checker_fails_outside_baseline_tree`, `test_base_checker_catches_growth_hidden_by_branch_checker_edit`, `test_base_checker_ignores_tampered_head_helper` |

# Reuse inventory

- `ColumnFacts.identity_error` and its `"error"` finding in `residual_pii_findings`: reused, not
  rebuilt.
- `passes_through` from `decoy_engine.profiling.scan_set`: reused for the re-raise guard.
- `_ratchet.py`: `DECISION`, `reason_findings`, `parse_registry`, `parse_approvals`, `max_raised`
  (generalized to `bound_loosened`), `moved_from`, the replacement and split call site, and the
  `check()` entry point: reused; new rules plug into `check()`.
- `approved_growth`: the one approval form for growth, raised maxes, lowered floors and removed
  limit keys. RG-E2 stores the same records under the old id when its sentry row is gone.
- `_baseline_sources.Source` with `maxes`, the regenerate path and
  `test_source_matches_its_registered_baseline`: reused for scalar limits through the
  `sentry-limits` source.
- `ratchet_check.py --root` and `--base`: reused; no `--repo`.
- `test_ratchet_check.py` temporary-repo helpers: imported by the new test files.
- `layout/_ratchet_cases.py` and `test_vendored_files.py`: the pattern for sharing case tables with
  the CLI.
- CLI `is_dated_owner_decision`, `created_in` rule and `CEILING_FIELDS`: kept as they are.

# Frozen contracts

PM-1 adds the plan writer API and a verification entry point for the gate. Keep the public
`run_post_mask` signature, report schema and verdict mapping (`runner.py:67-75`,
`residual_pii.py:580-592`, `_blocked.py:5-8`). Preserve the frame contract in
`docs/compatibility-contract.md:483-494,1237`. The ratchet work is test and
gate tooling only.

# Pre-mortem

- A new registry key or checker fix deadlocks against the base checker. Closed: baseline entries
  have no closed schema, each repo supplies one row schema, RG-E2 merges before RG-E3, and a real
  checker change carries a `[checker_change]` owner row that the report prints.
- A new required key or table breaks every open branch at once. Closed: the new tables are
  optional at base, `created_in` is required only for baselines new in the diff, and RG-E3's own
  head must pass the RG-E2 base checker.
- An approved limit removal goes stale once merged and turns every later PR red. Closed: the
  stale check admits the fresh deletion and keeps the merged approval inert.
- Builders learn to paste decision rows to get green. Partly closed: every new row is printed for
  the gate reviewer (L-A), and builders never write decision rows (see Builder brief items). A
  signed approval is V2.
- The sentry-file walk flags normal moves. Closed by `git diff -M` rename detection. A split of one
  file into two shows as delete plus add: the builder raises it on OWNER-QUESTIONS.md, and the
  `[retired_files]` row is written only with the owner's dated answer.
- The base-checker run fails because the base tree imports something the extract lacks. Closed by
  extracting whole directories with `git archive`, not a file list; a failure then fails the step
  loudly (M5) rather than skipping. The builder runs it once on a real main sha before review.
- PM-1 turns a quiet test into a red one because some existing test input made the comparison
  raise. That is the bug showing. The builder lists any such test and fixes the input, never the
  assertion.

# Builder brief items (every slice)

- Commit messages: Conventional Commits subject, 72 characters or fewer, no body unless it says
  why, final line `cam`. No trailers, file lists, test counts or headings.
  Rule: `/home/cam/dev-rules/workspace-and-vcs.md`, "Commit messages".
- Test depth T0 to T4 per `/home/cam/dev-rules/testing.md`, "Test depth". Use `~/bin/pytest-one`.
  Put the "Test scope" block in the builder report.
- Never raise a module-size ceiling. Every touched file stays at or under 600 lines, or does not
  grow if it is already over (`test_ratchet_check.py` takes no new tests).
- Builders never write an owner decision row (`approved_growth`, `[retired_growth]`, `[retired]`, `[retired_files]`,
  `[checker_change]`). When a change needs one, raise it on the vault `OWNER-QUESTIONS.md` with
  options and a recommendation, and write the row only with the owner's dated answer. Test
  fixtures inside `tmp_path` repos are not decision rows.
- Red before: run each acceptance test tagged red-before on the base first and record that it
  fails. Tests tagged pin pass on the base; do not report them as red evidence.
- No cell values, query text or exception message text in any finding or log line.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG updated before merge.

# Follow-ups (V2-LOG)

- L1 from plan review round 1: route `identity_error` on both the frame and batch paths through
  the central `safe_error_class` (`_progress_events.py:85`) at the message site
  (`residual_pii.py:477-482`). Class names are under the V1 bar.

# Owner decisions (2026-11-24)

The owner took the recommended answer on all seven questions.

- Q1. An owner sign-off in V1 is a dated text decision row plus a printed report line the gate
  reviewer checks. SSH-signed approvals checked from a main checkout (platform H1) are V2.
- Q2. Removing a sentry or deleting a sentry file needs an owner row (`[retired]` or
  `[retired_files]`). A removal covered by a replacement or split id needs none.
- Q3. Floors are covered, as `min` entries in the `sentry-limits` baseline (engine WALK_FLOOR and
  HEAD_FLOOR; CLI floors confirmed in RG-C1b).
- Q4. Platform H4 process hygiene stays out of this row. Only the skip-if-missing fix is in scope
  (RG-E3, RG-C1a). The rest is logged as a 1.x row.
- Q5. Keep the frame-path `check_residual_pii` and fix it in PM-1.
- Q6. `policy_validation.py::_check_one_column` gets the same fail-closed fix as a separate small
  R1 row.
- Q7. `created_in` is required for new baselines only, no back-fill. It is the baseline-file
  field the CLI already requires.
