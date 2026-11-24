"""Every registered validator has a shape and a fold; findings carry an exact count."""

from __future__ import annotations

from decoy_engine.validators import validate
from decoy_engine.validators._registry import _REGISTRY, _SPECS
from tests.unit.validators._fold_cases import build_cases


def test_every_registered_validator_has_a_shape_and_a_fold() -> None:
    assert set(_SPECS) == set(_REGISTRY)
    assert {spec.shape for spec in _SPECS.values()} == {"cell", "paired", "keyed"}
    assert all(spec.fn is _REGISTRY[name] for name, spec in _SPECS.items())


def test_a_finding_count_equals_its_indices_when_nothing_is_capped() -> None:
    for name, case in build_cases().items():
        report = validate(case.outputs, case.config, sources=case.sources)
        assert report.findings, name
        for finding in report.findings:
            assert finding.failing_row_count == len(finding.failing_row_indices), name
        assert [r.status for r in report.results] == ["failed"], name
        assert report.results[0].failing_row_count == sum(
            f.failing_row_count for f in report.findings
        )
