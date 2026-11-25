# Thermo-Nuclear Remediation Register

Status: plan. All efforts are 1.x work, tracked as rows in the roadmap health group (`docs/ROADMAP.md` in the CLI repo). Effort 0 is done.

Source review: [Thermo-Nuclear Code Quality Review](2026-11-25-thermo-nuclear-code-quality-review.md)

Frozen revision: `2b8a47fbee913a9f4df3fcdfe4876064a776d930`

This register converts the findings into bounded remediation efforts. Each effort needs its own risk classification, plan, tests, review, and exact-artifact gate.

## Priority order

| Order | Findings | Effort | Risk | Proposed owner | Status |
|---:|---|---|---|---|---|
| 0 | TNR-10 | Reconcile remediation ownership | R1 docs | H-1 documentation owner | Done 2026-11-25 |
| 1 | TNR-01, TNR-02 | Compile one execution plan and narrow route inputs | R2 architecture | H-1 engine architecture | Unassigned |
| 2 | TNR-03 | Move route clusters and delete private shims | R2 refactor | H-1 engine architecture | Unassigned |
| 3 | TNR-04 | Consolidate strategy and operator descriptors | R2 architecture | Engine and native owners | Unassigned |
| 4 | TNR-06 | Generate the text-redaction catalog | R2 native parity | Detection and native owners | Unassigned |
| 5 | TNR-05 | Split lifecycle workflows by typed phase | R2 refactor | Route-specific owners | Unassigned |
| 6 | TNR-07, TNR-08 | Add test ratchets and reorganize sentries | R1 test refactor | Test-infrastructure owner | Unassigned |
| 7 | TNR-09 | Replace the copied public API table | R2 compatibility | Public API owner | Unassigned |
| 8 | TNR-11 | Delete the relationship fallback parser | R1 cleanup | Plan owner | Unassigned |

## Effort 0: Reconcile remediation ownership

Required outcome:

- One document owns current engine remediation status.
- Historical records state that they are historical.
- `CODEBASE_AUDIT_MAP.md`, the engine archive guide, and the platform audit index agree.

Acceptance evidence:

- Every open row in `docs/remediation-source.md` maps to current code, a current effort, or a closed record.
- The compatibility-corpus row reflects `tests/integration/compat_corpus/`.
- No two documents claim source-of-truth status.

Non-goal: redesign the roadmap during this docs effort.

## Effort 1: Compile one execution plan

Required outcome:

- One immutable plan selects the route, sub-lane, resource policy, and output mode.
- One dispatcher consumes the plan.
- Runtime changes create typed transition records.
- Route executors receive only their route-specific inputs.

Child-plan entry requirements:

- The plan defines a finite route matrix from the current route modes, relationship shapes, source residency, validators, vault use, substrate, and memory signals.
- Each matrix row names its current outcome and expected compiled plan.

Acceptance evidence:

- The defined route matrix proves parity with the current router.
- One mutation of each route condition changes the expected plan or refusal.
- Telemetry derives from the plan and transition record.
- The old unified diversion and duplicate route decisions are absent.

Non-goal: add a new route or change output behavior.

## Effort 2: Move cohesive route packages

Required outcome:

- Complete route clusters move into mapped targets.
- These targets are `execution/chunked/`, `execution/pipeline/`, `execution/sequential/`, and `execution/isolated/`.
- Native work uses `execution/native/draw/` or `execution/native/chunked/`.
- Out-of-core stream work uses `execution/out_of_core/stream/`.
- Internal imports use the new owners directly.
- Private compatibility shims and historical re-exports are deleted.

Acceptance evidence:

- The execution root fan-out decreases from 103.
- Import contracts remain green.
- Test patches use stable seams, not historical module paths.
- No forwarding-only module remains from the move.

## Effort 3: Consolidate static behavior descriptors

Required outcome:

- Each strategy or operator has one static descriptor.
- The descriptor owns static capabilities, kernel needs, evidence type, and diagnostic metadata.
- Route-specific dynamic predicates remain with route owners.
- Catalogs and capability views are generated from descriptors.

Acceptance evidence:

- Adding a seeded strategy requires one descriptor plus its implementation and tests.
- A guard fails when a copied static strategy table appears.
- Kernel preflight derives its loaders from admitted descriptors.
- The seed-envelope compiler consumes a typed compiled-column record.

## Effort 4: Generate the text-redaction catalog

Required outcome:

- One descriptor owns detector IDs, pattern data, validator tags, and vocabularies.
- Python, Rust, and parity fixtures come from the descriptor.
- Specialized Rust scanners stay handwritten only where semantics require them.

Acceptance evidence:

- A generated-artifact check fails on drift.
- Existing pattern-body, vocabulary, and behavioral differential checks stay green.
- Deterministic regeneration produces no repository diff.
- Generated Python and Rust fields agree with the source descriptor.
- Catalog changes require one source edit.

## Effort 5: Split lifecycle workflows

Start with these functions:

- `out_of_core._stream_driver.stream_table`
- `execution._sequential.run_sequential`
- `plan._seed_envelope._build_seed_envelope`
- `profiling.model_pack.trainer.train_and_evaluate`
- `native._chunk_masking._mask_chunk_native`

Required outcome:

- Each phase has a typed input and output.
- Resource acquisition and cleanup stay in one visible lifecycle owner.
- Operator-specific reduction leaves the shared chunk coordinator.
- Training, evaluation, serialization, and inference have separate owners.

Acceptance evidence:

- The child plan records the starting line and branch counts for each target.
- The finishing record reports the same measures and explains each remaining branch cluster.
- Existing parity and lifecycle tests stay behavior-based.
- The split deletes conditions or duplicate policy. It does not add forwarding layers.

Current AST baseline:

| Function | Lines | Branch nodes |
|---|---:|---:|
| `out_of_core._stream_driver.stream_table` | 448 | 55 |
| `execution._sequential.run_sequential` | 452 | 45 |
| `plan._seed_envelope._build_seed_envelope` | 327 | 46 |
| `profiling.model_pack.trainer.train_and_evaluate` | 307 | 35 |
| `native._chunk_masking._mask_chunk_native` | 241 | 40 |

The branch metric counts `if`, loops, `try`, `match`, boolean operators, and conditional expressions in each function AST.

## Effort 6: Govern test size and layout

Required outcome:

- A test-size ratchet covers tracked Python test files.
- A test fan-out sentry covers packages such as `tests/sentry`.
- Root sentries move into the concern packages already listed in `CODEMAP.md`.

Acceptance evidence:

- Seeded over-size and over-fan-out cases fail.
- Existing giant files have shrink-only ceilings and named split targets.
- `tests/sentry` has at most 25 direct modules after the migration.
- The sentry manifest still discovers nested tests.

## Effort 7: Replace the copied public API table

Required outcome:

- One versioned manifest records the public surface and stability tier.
- Compatibility tests compare the package against that manifest.
- The root facade contains only common entry points before GA.

Acceptance evidence:

- A removed or changed symbol produces a manifest diff and a compatibility failure.
- No second source-code set copies `__all__`.
- CLI and platform consumer scans identify every retained root export.

## Effort 8: Delete the relationship fallback parser

Required outcome:

- `_build_relationships` requires the validated orphan-policy lookup.
- The raw-configuration fallback and its fallback-only test are deleted.

Acceptance evidence:

- Plan compilation tests cover all orphan-policy values through the canonical validator.
- No direct caller bypasses the canonical lookup.

## Sequencing rules

Do not split routing files before Effort 1 fixes decision ownership. An early move can distribute the same branching across more files.

Do not reduce the public facade until consumer scans cover the CLI and platform. This action affects compatibility.

Efforts 3 and 4 can run in parallel after the execution-plan boundary is stable. Both must retain parity tests.

Effort 6 can run independently. Keep its first change mechanical and behavior-neutral.

## Closure record

Close a row only after the original evidence no longer applies. Record the exact revision and the verification commands.

If a remediation changes source, run the applicable development loop from PLAN through GATE. Do not close a finding from a code diff alone.
