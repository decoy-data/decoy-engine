# Thermo-Nuclear Evidence: Tests and Contracts

Status: complete lane record

Frozen revision: `2b8a47fbee913a9f4df3fcdfe4876064a776d930`

## Checked scope

The lane inspected test layout, source sentries, CI lane registries, public API checks, documentation ownership, prior remediation records, and recurring defect sentries.

## Evidence

### Test size

The source size sentry scans `src/decoy_engine` and `scripts`. It does not scan tests.

- 39 Python test modules exceed 1,000 lines.
- Those modules contain 50,469 lines.
- 129 Python test modules exceed 700 lines, including those 39.
- Those modules contain 123,977 lines.
- `tests/unit/transforms/test_code_set.py` has 2,498 lines.
- `tests/parity/test_out_of_core_fk_parity.py` has 1,933 lines.

This evidence supports TNR-07.

### Test fan-out

`tests/sentry/layout/test_package_fanout.py:46-54` scans production source and scripts. It does not scan tests.

`tests/sentry` has 100 direct Python modules, excluding `__init__.py`. `CODEMAP.md` already names suitable concern packages.

This evidence supports TNR-08.

### Public API ownership

- `src/decoy_engine/__init__.py:358-589` defines 230 public names.
- `tests/unit/test_public_api.py:25-341` copies the names into a second set.
- `contracts/stability.py:24-72` adds stability registries.

This evidence supports TNR-09.

### Remediation ownership

- `docs/remediation-source.md:3-13` claims source-of-truth status for a June 2026 baseline.
- `docs/remediation-source.md:42-48` still states that no compatibility corpus exists.
- `tests/integration/compat_corpus/` exists at the frozen revision.
- `CODEBASE_AUDIT_MAP.md:3-9` assigns current audit tracking to the commercial platform repository.

This evidence supports TNR-10.

## Strengths

- CI lane registries have seeded sentry tests.
- Source size and fan-out limits have shrink-only behavior.
- The public stability census checks object identity across re-exports.
- The sentry manifest discovers nested folders.
- Recurring defect classes have structural guards for validation, exception context, canonical JSON, environment reads, and choke points.

## Rejected concerns

- The root facade can import private implementation modules. That import pattern is intentional for a facade.
- Production size debt is ungoverned. The source sentries govern it, although debt remains.
- CI required jobs are only a manual list. The CI sentry reconciles the list with workflows and seeded failures.

## Unchecked scope

The lane did not inspect every workflow branch, shell path, or test module. It did not run the full suite.
