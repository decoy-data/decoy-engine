# Mutation grading: `execution/_residency_warning.py` -- logic 0 unresolved

P4-A (Option A) caller-managed residency warning
(`docs/plans/2026-09-01-p4a-ooc-residency-guard.md`). The module holds the shape
predicate `caller_managed_residency_shapes` (the admission logic: which
caller-managed input shapes are present), `residency_quality_warning` (the
structured `QualityWarning` factory attached to `ExecutionResult.warnings`), and
`residency_warning_message` (the human-facing heads-up text).

Graded via `scripts/native-testing/python_mutation_pilot.py` (mutmut generation +
standalone-pytest-per-mutant readjudication), selection
`tests/unit/execution/test_ooc_residency_warning.py`.

## Numbers

**51 mutants: 35 killed, 16 survivors.** Every survivor is in
`residency_warning_message` -- the human-readable warning string. Its one LOGIC
branch, the `if not shapes: return ""` empty-guard, is killed
(`test_empty_shapes_message_is_empty`). Both the shape predicate
`caller_managed_residency_shapes` and the `residency_quality_warning` factory
have **0 surviving mutants**: the factory's `code`/`provider`/`detail` fields are
pinned by `test_residency_quality_warning_shape` and by the evidence-model test
(see "Evidence-model mutations" below); the redundant `column=None`
default was dropped so no equivalent survivor exists. The predicate's every
branch (resident-by-type, `sink is None`, `source_loader is not None`, and the
tuple assembly) is killed by the by-shape unit tests
(`test_resident_source_is_detected_by_type_not_dict_non_emptiness`,
`test_missing_sink_is_a_caller_managed_shape`,
`test_source_loader_is_a_caller_managed_shape`,
`test_all_three_shapes_reported_together`, `test_mixed_residency_reports_resident`,
`test_bounded_shape_reports_no_caller_managed_shapes`).

**0 unresolved LOGIC survivors.** The 16 message survivors are accepted prose:
mutations to fragments of the warning's free text (its lead phrase, the
parenthetical asides, punctuation, casing). The machine-relevant phrases a caller
would key on are pinned by
`test_warning_message_names_shape_and_bounded_alternative` (the shape name,
`LazySource`, `write_batches`, `full_frame`); the remaining wording carries no
verifiable behavior. Same policy as the chunked-lane ledgers
(`execution_chunked_code_set.md` et al.): coded/consumed fields pinned, prose
adjudicated.

## The predicate mutant that matters is killed

The one bug worth guarding -- detecting residency by whether `sources` is
non-empty (`bool(sources)`) instead of by TYPE (`isinstance(value, pa.Table)`) --
would wrongly warn on the guaranteed LazySource+sink shape. It is pinned by
`test_resident_source_is_detected_by_type_not_dict_non_emptiness` and
`test_bounded_shape_reports_no_caller_managed_shapes` (a non-empty dict of
LazySources reports no shapes). The corresponding mutmut mutants on the
`isinstance` check are all killed.

## Evidence-model mutations (2026-11-17, fix/ooc-warning-evidence)

The factory now emits `provider="out_of_core_route"` and a scalar-only `detail` (one `True`
flag per shape plus `message`) so `EvidencePayload` accepts it. Three hand mutations on the
final head, run against `tests/unit/records/test_evidence_accepts_run_warnings.py`,
`test_ooc_residency_warning.py` and `test_r3_within_route_baseline.py`; all killed:

- restore `provider=""`: killed (evidence model refuses the empty name; the shape test pins the name);
- restore a list in `detail` (`detail["shapes"] = list(shapes)`): killed (evidence model refuses the list);
- skip unknown shapes (`... for s in shapes if s in _SHAPE_FLAGS`): killed by
  `test_residency_warning_refuses_an_unknown_shape`.

The mutmut counts above predate this change and were not regenerated.

## Candidate findings

None. No mutation exposed a wrong shape verdict or a predicate branch the tests
do not pin. The warning never alters output or routing (the byte-parity test
`test_forced_ooc_byte_parity_preserved_with_warning` holds with the warning
present), so a surviving prose mutant cannot mask a behavioral defect.

## Regenerate

```
python scripts/native-testing/python_mutation_pilot.py \
  --module src/decoy_engine/execution/_residency_warning.py \
  --tests tests/unit/execution/test_ooc_residency_warning.py \
  --timeout 20
```
