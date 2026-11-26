# Thermo-Nuclear Evidence: Native and Transforms

Status: complete lane record

Frozen revision: `2b8a47fbee913a9f4df3fcdfe4876064a776d930`

## Checked scope

The lane inspected the Rust companion, Python native bridge, operator registry, capability tables, dispatch, chunk execution, and FF1.

It also inspected text-redaction parity, detection, profiling, and the largest modules in this scope.

## Evidence

### Native operator ownership

- `execution/_operator_registry.py:59-307` owns operator descriptors.
- `execution/native/_capabilities.py:120-482` owns another behavior and diagnostic table.
- `execution/native/_operator_step.py:303-501` owns a central parameter-type dispatch chain.
- `execution/native/_dispatch.py:551-599` hard-codes four kernel probe paths.

This evidence supports TNR-04.

### Text-redaction duplication

- `detection/detectors.py:768-854` owns Python IDs, patterns, and street vocabulary.
- `execution/native/_text_redact_kernel.py:41-141` owns the native ID and version gate.
- `decoy-engine-native/src/text_redact/catalog.rs:6-78` repeats catalog policy.
- `decoy-engine-native/src/text_redact/scanners.rs:155-208` repeats street vocabulary.
- `tests/native/test_c6c_ii_text_redact_rust.py:773-835` keeps another frozen catalog copy.

This evidence supports TNR-06.

The parity suite already provides strong drift controls. It pins Python pattern bodies and flags at `tests/native/test_c6c_ii_text_redact_rust.py:815-856`.

The same suite compares street vocabularies and runs per-vocabulary behavioral differential cases after line 859. The residual finding concerns coordinated ownership, not missing parity checks.

### Large lifecycle functions

`native/_chunk_masking.py:56-288` combines traversal with operator-specific result processing. The function accepts about twenty keyword arguments.

`profiling/model_pack/trainer.py:290-596` combines corpus construction, splitting, fitting, thresholding, metrics, calibration, OOD evaluation, serialization, manifest creation, and report hashing.

The same trainer module also contains test-only pack loading and inference at lines 599-711.

This evidence supports TNR-05.

## Strengths

- `OperatorSpec` provides a useful consolidation base.
- Native admission is fail-closed and table-atomic.
- The Rust and Python boundary has ABI checks and known-answer tests.
- Rust algorithm code is separate from PyO3 glue.
- Text redaction falls back to Python on catalog skew or unsupported cells.

## Reconciled prior findings

The July custom-Feistel FPE finding is closed in current code. The native implementation uses FF1 with fail-closed domain handling.

The July missing key-provider boundary is also closed in this scope.

## Rejected concerns

- No current text-redaction output mismatch was established.
- Arrow FFI wrappers repeat scaffolding, but a generic wrapper can cost more than the duplication.
- Ordered native admission gates are not automatically spaghetti. The duplicated kernel probe ownership is the specific finding.

## Unchecked scope

The lane did not inspect every Rust algorithm, transform, provider, benchmark, or memory characteristic.
