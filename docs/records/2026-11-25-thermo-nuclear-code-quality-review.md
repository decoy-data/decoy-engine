# Thermo-Nuclear Code Quality Review

Status: complete, report only

Audit date: 2026-11-25

Frozen revision: `2b8a47fbee913a9f4df3fcdfe4876064a776d930`

Release phase: pre-GA

Risk: R2. This review covers architecture and broad remediation direction. It changed no production code.

## Recommendation

No finding reaches BLOCKER or HIGH on current evidence. The review found ten MEDIUM maintainability risks and one LOW cleanup item.

Continue the H-1 code-organization program before new route or operator expansion. Start with routing ownership, execution inputs, and package layout. These three items amplify most other costs.

## Scope

The review covered the Python engine, the Rust companion, tests, sentries, public contracts, and current remediation records.

The frozen tree contains 1,003 tracked production Python and Rust files with 228,484 lines. It also contains 2,083 tracked Python test files with 536,139 lines. An earlier pathspec census missed eight Rust files directly under `decoy-engine-native/src` and twelve Python files directly under `tests`.

The review used four concern lanes:

1. Python execution and plan architecture.
2. Native code, transforms, detection, and profiling.
3. Tests, sentries, public contracts, and documentation.
4. Cross-lane synthesis and prior-finding reconciliation.

The detailed lane records are:

- [Python architecture evidence](2026-11-25-thermo-nuclear-python-architecture.md)
- [Native and transforms evidence](2026-11-25-thermo-nuclear-native-transforms.md)
- [Tests and contracts evidence](2026-11-25-thermo-nuclear-tests-contracts.md)
- [Remediation register](2026-11-25-thermo-nuclear-remediation.md)

## Findings

| ID | Severity | Problem | Required outcome |
|---|---|---|---|
| TNR-01 | MEDIUM | Routing has several decision authorities and later diversions | One immutable execution plan and one dispatcher |
| TNR-02 | MEDIUM | The main run boundary is a 47-parameter policy and dependency bag | Cohesive typed inputs and narrow route contracts |
| TNR-03 | MEDIUM | Size caps coexist with package sprawl, forwarding modules, and private re-exports | Cohesive route packages with direct internal imports |
| TNR-04 | MEDIUM | Strategy and native behavior facts have several owners | One typed static descriptor per strategy or operator |
| TNR-05 | MEDIUM | High-branch workflows still concentrate several lifecycle phases | Typed phase boundaries that remove later conditions |
| TNR-06 | MEDIUM | Text-redaction policy is copied across Python, Rust, and tests | One language-neutral catalog that generates both surfaces |
| TNR-07 | MEDIUM | Test modules have no size ratchet | A test-size policy and contract-based splits |
| TNR-08 | MEDIUM | `tests/sentry` is a package with 100 direct modules outside the fan-out guard | Recursive test fan-out checks and concern packages |
| TNR-09 | MEDIUM | The 230-name root API uses a copied source-code table as its contract | One versioned public-surface manifest and a smaller facade |
| TNR-10 | MEDIUM | Two remediation documents claim ownership, and one is materially stale | One current register with explicit pointers from old records |
| TNR-11 | LOW | The plan relationship builder retains an unused second parser | Require the canonical lookup and delete the fallback |

## Detailed findings

### TNR-01: Routing has several decision authorities

`decide_route` builds decisions in stages at `src/decoy_engine/execution/_pipeline_context.py:513-573`. Full-frame execution can later divert through `maybe_run_unified_slice` at `src/decoy_engine/execution/_pipeline_full_frame.py:170-177`.

The primary router spans `src/decoy_engine/execution/_pipeline_routing.py:274-566`. Ruff reports the router and the unified admission functions as complex. The October F06 plan also states that no universal compiler governs routing.

This is the current form of the older DE-15 finding. A new route capability touches selection, chunk planning, unified admission, split planning, execution, decline records, and telemetry.

The required outcome is one immutable plan before source mutation. The plan records the route, sub-lane, capabilities, resource policy, and output mode. Runtime changes append typed transitions.

### TNR-02: The main run boundary is a policy and dependency bag

`run_pipeline` has 47 parameters at `src/decoy_engine/execution/_pipeline.py:116-165`. `build_run_context` has 46 parameters at `src/decoy_engine/execution/_pipeline_context.py:176-224`. `PipelineRunContext` has 52 fields at `src/decoy_engine/execution/_pipeline_context.py:83-146`.

The carrier mixes source handles, compiled artifacts, secrets, route policy, resource limits, reporting controls, quarantine state, test hooks, and sinks. Most route executors receive more state than they use.

The required outcome is a small set of cohesive inputs. Candidate types are `RunRequest`, `ExecutionPolicy`, `RunServices`, and `ObservationPolicy`. Each route receives a narrow contract.

### TNR-03: Size caps coexist with structural indirection

The package sentry records 103 direct modules in `execution`, 55 in `execution/native`, 44 in `execution/out_of_core`, and 30 in `plan`. See `tests/sentry/layout/test_package_fanout.py:28-43`.

Several modules preserve old imports or delegate a small amount of code. Examples include `_fk_key_compat.py:1-23`, `out_of_core/_source.py:1-16`, and `_pipeline_route_exec.py:591-597`.

The required outcome is a move of complete route clusters into the packages already named in `CODEMAP.md`. Internal callers and tests move in the same change. Private compatibility shims do not remain.

### TNR-04: Static strategy facts have several owners

Strategy facts appear in handler instances, `strategy_requirements.py`, native capability tables, chunked admission sets, FK vocabularies, and out-of-core groups. Native operator facts also appear in `OperatorSpec`, `_capabilities.py`, `_operator_step.py`, and `_dispatch.py`.

`_build_seed_envelope` adds another large policy reader at `src/decoy_engine/plan/_seed_envelope.py:41-367`. Its comments name mirrored determinism logic in `native/_requirements.py`.

Totality tests detect missing entries, but they do not provide one owner. A new strategy still needs synchronized edits across several tables and dispatch chains.

The required outcome is one typed descriptor for static facts. Dynamic schema and configuration predicates stay in route owners. Generated views replace copied registries.

### TNR-05: High-branch workflows still contain several phases

Ruff 0.15.22 reports 194 C901 findings under `src/decoy_engine`. This count is supporting evidence, not a defect count.

The clearest examples are:

- `out_of_core/_stream_driver.py:128-575`, which combines source staging, masking, FK joins, reorder budgets, output emission, evidence, and cleanup.
- `execution/_sequential.py:229-680`, which combines route lifecycle phases in one function.
- `plan/_seed_envelope.py:41-367`, which compiles provider, cardinality, NER, gating, pool, and relationship facts.
- `profiling/model_pack/trainer.py:290-596`, which combines split, fit, calibration, evaluation, serialization, manifest creation, and report hashing.
- `native/_chunk_masking.py:56-288`, which combines chunk coordination and operator-specific result reduction.

The required outcome is typed phase inputs and outputs. A valid split removes conditions from later phases. Forwarding modules do not satisfy this outcome.

### TNR-06: Text-redaction policy is copied across language boundaries

Python owns detector IDs, patterns, and street vocabulary in `detection/detectors.py:768-854`. The native bridge owns another ID and version list in `native/_text_redact_kernel.py:41-66`. Rust repeats the catalog in `decoy-engine-native/src/text_redact/catalog.rs:6-78` and vocabulary in `scanners.rs:155-208`.

The parity suite pins Python pattern bodies and flags at `tests/native/test_c6c_ii_text_redact_rust.py:815-856`. It also compares street vocabularies and runs behavioral differential cases after line 859.

These controls catch drift, but coordinated policy still exists in several language-specific locations. Each intended policy change needs synchronized edits across those locations.

The required outcome is one language-neutral detector descriptor. It contains IDs, patterns, validator tags, and vocabularies. The build generates Python, Rust, and parity fixtures from this descriptor.

### TNR-07: Test modules have no size ratchet

The production size sentry scans `src/decoy_engine` and `scripts`, but not tests. See `tests/sentry/test_module_size.py:156-157`.

Thirty-nine Python test modules exceed 1,000 lines. They contain 50,469 lines. In all, 129 modules exceed 700 lines (these 39 included) and contain 123,977 lines.

Examples include `test_code_set.py` at 2,498 lines and `test_out_of_core_fk_parity.py` at 1,933 lines. These files combine several contracts and large shared harnesses.

The required outcome is a separate test-size ratchet. Split files by behavior or contract. Extract a helper only when two focused test modules need it.

### TNR-08: The sentry package has no learnable structure

The fan-out sentry says that more than 25 direct modules prevents readers from learning a package. Its walk excludes tests at `tests/sentry/layout/test_package_fanout.py:46-54`.

`tests/sentry` now contains 100 direct Python modules, excluding `__init__.py`. `CODEMAP.md` already names `layout`, `defects`, `dependencies`, `tooling`, and `release` packages.

The required outcome is recursive fan-out enforcement for test packages. Existing root sentries move into the named packages. No re-export shims remain.

### TNR-09: The root API contract is a copied table

`src/decoy_engine/__init__.py:358-589` defines a 230-name `__all__`. `tests/unit/test_public_api.py:25-341` copies the same names into another set. Separate stability registries add more ownership points in `contracts/stability.py:24-72`.

The equality test catches one-sided edits but preserves the parallel-table design. The root facade also grew from 149 names in the prior remediation record to 230 names at this revision.

The required outcome is one versioned release manifest. Compatibility tests read that manifest. Before GA, the root facade keeps only common construction and execution entry points.

### TNR-10: Remediation ownership is unclear and stale

`docs/remediation-source.md:3-13` calls itself the source-of-truth register and describes a June 2026 baseline. It still lists the missing compatibility corpus as an open launch blocker at lines 42-48.

The current tree contains `tests/integration/compat_corpus/`. `CODEBASE_AUDIT_MAP.md:3-9` separately states that the commercial platform repository owns current audit tracking.

The required outcome is one current register. If the platform register owns remediation, archive the engine register and replace it with a pointer. Historical records must not claim current status.

### TNR-11: The plan relationship builder retains a second parser

`plan/_graph.py:20-100` accepts an optional canonical lookup. It reparses raw configuration when the lookup is absent. The production caller always supplies the validated lookup at `plan/_compile.py:441`.

The only no-lookup caller is a fallback unit test. The required outcome is a mandatory lookup and deletion of the fallback parser.

## Strengths to preserve

- The repository records size and fan-out debt with shrink-only sentries.
- Route failures use typed reason codes and usually fail closed.
- Native admission is table-atomic and falls back before output publication.
- The Rust boundary has ABI checks, known-answer tests, differential tests, and fuzz targets.
- CI lane ownership and sentry manifests use seeded failure cases.
- The July security findings for FPE, key providers, and raw-column passthrough have current remediation evidence.

## Prior finding reconciliation

This review did not reopen the July 2026 FPE construction finding. The current native implementation uses FF1 and fail-closed domain checks.

This review did not reopen the missing `KeyProvider` seam. The current code has the abstraction and uses it across keyed paths.

TNR-01 continues DE-15. The implementation added typed decisions, but several routing authorities remain.

TNR-03, TNR-05, TNR-07, and TNR-08 extend the active H-1 module-size audit with current evidence.

## Verification record

| Check | Result | Coverage |
|---|---|---|
| `git fetch origin` | Passed | Current remote revision fetched before freeze |
| Fresh detached worktree | `2b8a47fbee913a9f4df3fcdfe4876064a776d930` | Isolated audit tree, no user changes |
| Module-size and package-fan-out sentries | 1,254 passed, one pytest configuration warning | Existing production and script ratchets |
| Ruff 0.15.22, C901 over `src/decoy_engine` | 194 findings | Branch complexity indicator only |
| AST parameter and field counts | 47, 46, and 52 | `run_pipeline`, context builder, context record |
| Tracked-file census | 1,003 production files, 2,083 Python test files | Python and Rust production source, Python tests |
| Graphify query | Returned only plan-risk nodes | Too weak for findings. Source and CODEMAP evidence replaced it |
| Three independent audit lanes | Complete | Python, native, tests and contracts |

The sentry run used pytest 9.1.1. Cargo 1.98.0 was present. No full Python or Rust suite ran.

### Reproduction commands

All commands ran from `/tmp/decoy-engine-audit.yXdVJn`. This worktree held the frozen revision.

The sentry run used the existing locked environment from the main checkout:

```sh
/home/cam/vscode/decoy-engine/.venv/bin/python -m pytest \
  tests/sentry/test_module_size.py \
  tests/sentry/layout/test_package_fanout.py -q
```

The Ruff run used this executable and command:

```sh
/home/cam/vscode/decoy-engine/.venv/bin/ruff --version
/home/cam/vscode/decoy-engine/.venv/bin/ruff check \
  src/decoy_engine --select C901 --output-format json
```

The executable reported Ruff 0.15.22. The JSON result contained 194 entries.

The parameter counts used Python 3.11 `ast` over `_pipeline.py` and `_pipeline_context.py`. The script counted positional, named, and keyword-only parameters. It counted annotated class fields in `PipelineRunContext`.

```sh
python3 - <<'PY'
import ast
from pathlib import Path

targets = [
    ("src/decoy_engine/execution/_pipeline.py", {"run_pipeline"}),
    ("src/decoy_engine/execution/_pipeline_context.py", {"build_run_context"}),
]
for file, names in targets:
    tree = ast.parse(Path(file).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            count = len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs)
            print(file, node.name, count)

tree = ast.parse(Path("src/decoy_engine/execution/_pipeline_context.py").read_text())
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "PipelineRunContext":
        print("PipelineRunContext fields", sum(isinstance(item, ast.AnnAssign) for item in node.body))
PY
```

The file census used these commands:

```sh
git ls-files 'src/**/*.py' 'decoy-engine-native/src/**/*.rs' | xargs wc -l
git ls-files 'tests/**/*.py' 'decoy-engine-native/tests/**/*.rs' | xargs wc -l
git ls-files 'tests/**/*.py' | xargs wc -l
```

The census ignored the `wc` total rows before it summed file rows. The test thresholds used strict `> 1000` and `> 700` comparisons.

## Coverage limits

The audit did not prove runtime correctness or performance. It did not inspect every strategy, provider, Rust algorithm, workflow branch, or test module.

The audit reviewed maintainability. It did not repeat a full security or release-readiness review.

The active checkout contained user-owned changes and was 463 commits behind the remote branch. The audit preserved that checkout and used a fresh worktree.
