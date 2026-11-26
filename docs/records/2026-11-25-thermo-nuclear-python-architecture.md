# Thermo-Nuclear Evidence: Python Architecture

Status: complete lane record

Frozen revision: `2b8a47fbee913a9f4df3fcdfe4876064a776d930`

## Checked scope

The lane inspected `run_pipeline`, run context construction, route selection, route dispatch, full-frame execution, and unified-slice admission.

It also inspected physical execution, package layout, size sentries, strategy registries, and relationship compilation.

The lane compared current code with the July architecture review and later remediation plans.

## Evidence

### Routing authority

- `_pipeline_context.py:513-573` composes route, chunk, out-of-core, multi-table, and resident-fit decisions.
- `_pipeline_full_frame.py:170-177` applies a later unified-slice diversion.
- `_pipeline_routing.py:274-566` contains the primary route decision.
- `_unified_slice_admission.py:196` and `:410` contain additional admission authorities.

This evidence supports TNR-01.

### Run boundary size

- `run_pipeline` has 47 parameters.
- `build_run_context` has 46 parameters.
- `PipelineRunContext` has 52 fields.

This evidence supports TNR-02.

### Package structure

- `execution` has 103 direct modules in the fan-out allowlist.
- `execution/native` has 55.
- `execution/out_of_core` has 44.
- `plan` has 30.

Compatibility and forwarding examples:

- `_fk_key_compat.py:1-22`
- `out_of_core/_source.py:1-14`
- `_pipeline_route_exec.py:591-597`

This evidence supports TNR-03.

### Static strategy facts

Static facts appear in these owners:

- `execution/_strategies/__init__.py:52-135`
- `contracts/strategy_requirements.py:79-112`
- `execution/native/_capabilities.py:146-482`
- `execution/_chunked.py:190-208`
- `execution/_chunked_fk_vocab.py:44-84`
- `execution/out_of_core/_compat.py:37-64`
- `execution/native/_requirements.py:129-161`

`plan/_seed_envelope.py:41-367` compiles another large set of strategy facts. Its comments name mirrored native determinism logic.

This evidence supports TNR-04.

### Relationship fallback

`plan/_graph.py:20-100` reparses configuration when no lookup is supplied. Production always supplies the validated lookup from `plan/_compile.py:441`.

The fallback exists for one unit test at `tests/unit/plan/test_compile_s2_refactor.py:689-723`.

This evidence supports TNR-11.

## Rejected concerns

- Sequential FK execution is not a finding by itself. The topology requires ordered work.
- Strategy handlers are not all thin wrappers. Many adapt a real transform to an execution protocol.
- A file over 600 lines is not automatically a finding. Several files contain cohesive algorithms or registries.
- Ruff complexity is maintainability evidence. It does not prove a runtime defect.

## Unchecked scope

The lane did not inspect every strategy, file-access operation, generation algorithm, or runtime behavior.
