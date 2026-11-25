"""The operator registry is the one place per-operator facts live (R1).

Totality and consistency checks here replace the old hand-synchronized parallel tables.
The snapshot file `test_operator_tables_snapshot.py` pins each derived view's value.
"""

from __future__ import annotations

import dataclasses

import pyarrow as pa
import pytest

from decoy_engine.execution._operator_registry import OPERATORS, OperatorSpec, operator_spec
from decoy_engine.execution.native._chunked_evidence import (
    ARROW_PYTHON,
    RUST_COMPANION,
    RUST_POOL_SELECT,
)
from decoy_engine.execution.physical._shadow_bindings import SLICE_STRATEGIES


def test_registry_keys_equal_slice_strategies() -> None:
    assert set(OPERATORS) == set(SLICE_STRATEGIES)
    assert all(spec.strategy == key for key, spec in OPERATORS.items())


def test_operator_ids_are_unique() -> None:
    ids = [spec.operator_id for spec in OPERATORS.values()]
    assert len(ids) == len(set(ids))


def test_backend_and_kernel_are_consistent() -> None:
    for spec in OPERATORS.values():
        assert (spec.planned_backend == ARROW_PYTHON) == (spec.required_kernel is None), spec
        assert (spec.planned_backend == RUST_POOL_SELECT) == (spec.shape == "pool"), spec
        assert spec.planned_backend in {ARROW_PYTHON, RUST_COMPANION, RUST_POOL_SELECT}


def test_unknown_strategy_raises_key_error() -> None:
    with pytest.raises(KeyError):
        operator_spec("nope")
    assert operator_spec("hash") is OPERATORS["hash"]


def test_spec_is_frozen() -> None:
    spec = operator_spec("hash")
    assert isinstance(spec, OperatorSpec)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.operator_id = "x"  # type: ignore[misc]


def test_group_key_has_no_target_resident_types_and_faker_has_the_allowlist() -> None:
    assert OPERATORS["group_key"].resident_type_domain is None
    assert OPERATORS["faker"].provider_allowlist == frozenset(
        {
            "person_first_name",
            "person_last_name",
            "person_name",
            "person_full_name",
            "person_email",
            "person_phone",
            "address_street",
            "address_city",
            "address_state",
            "address_zip",
            "synthetic_account_number",
            "synthetic_member_id",
            "synthetic_plan_id",
        }
    )
    passthrough = OPERATORS["passthrough"].resident_type_domain
    assert passthrough is not None
    assert passthrough.default.exact == frozenset({pa.string(), pa.int64(), pa.bool_()})
    assert all(spec.provider_allowlist is None for key, spec in OPERATORS.items() if key != "faker")


def test_capability_diagnostics_are_routed_for_every_slice_operator() -> None:
    """A slice operator whose capabilities declare a diagnostic the unified coordinator
    does not route must be a conscious decision (add it to `routed_diagnostics` with a
    real routing path, or keep the operator declined), never an automatic admission."""
    from decoy_engine.execution.native._capabilities import capabilities_for
    from decoy_engine.execution.native._requirements import _diagnostic_reducers

    for spec in OPERATORS.values():
        declared = frozenset(_diagnostic_reducers(capabilities_for(spec.strategy)))
        assert declared <= spec.routed_diagnostics, (spec.strategy, declared)


def test_routed_obligations_are_policy_not_derived_from_capabilities() -> None:
    """The unified slice's routed-diagnostics table is coordinator policy read from each
    descriptor's `routed_diagnostics`. Deriving it from the capability reducers would make
    the admission gate `obligations <= routed` pass for every operator, silently admitting
    a future operator whose diagnostics the coordinator never routes."""
    import ast
    import inspect

    from decoy_engine.execution import _unified_slice_admission as adm

    expected = {
        s.operator_id: s.routed_diagnostics for s in OPERATORS.values() if s.routed_diagnostics
    }
    assert expected == adm._ROUTED_DIAGNOSTIC_OBLIGATIONS
    names = {n.id for n in ast.walk(ast.parse(inspect.getsource(adm))) if isinstance(n, ast.Name)}
    assert "_diagnostic_reducers" not in names


def test_group_key_sibling_types_exclude_floats_even_if_passthrough_widens() -> None:
    import pyarrow as pa

    from decoy_engine.execution.native._operator_config_rejections import group_key_sibling_types

    widened = frozenset({pa.string(), pa.int64(), pa.bool_(), pa.float64(), pa.decimal128(10, 2)})
    assert group_key_sibling_types(widened) == frozenset({pa.string(), pa.int64(), pa.bool_()})
    assert group_key_sibling_types(None) == frozenset()


def test_only_faker_declares_a_positional_resident_domain() -> None:
    from decoy_engine.execution._operator_registry import POSITIONAL_FAKER_SOURCE_TYPES

    numeric = frozenset(
        {
            pa.int8(),
            pa.int16(),
            pa.int32(),
            pa.int64(),
            pa.uint8(),
            pa.uint16(),
            pa.uint32(),
            pa.uint64(),
            pa.bool_(),
            pa.float32(),
            pa.float64(),
        }
    )
    assert numeric == POSITIONAL_FAKER_SOURCE_TYPES
    faker = OPERATORS["faker"].resident_type_domain
    assert faker is not None and faker.positional is not None
    assert faker.positional.exact == numeric | {pa.string()}
    assert faker.default.exact == frozenset({pa.string()})
    assert all(
        spec.resident_type_domain is None or spec.resident_type_domain.positional is None
        for key, spec in OPERATORS.items()
        if key != "faker"
    )


# T11 (DATE-SHIFT-TYPED S1). The resident domains each operator admitted before the one
# descriptor replaced the three parallel fields, per keying mode. The only S1 change is
# `date_shift` gaining `date32` (the zoned-timestamp family comes with S2).
_S = frozenset({pa.string()})
_PRE_CHANGE_DEFAULTS = {
    "passthrough": frozenset({pa.string(), pa.int64(), pa.bool_()}),
    "redact": _S,
    "truncate": _S,
    "text_redact": _S,
    "text_mask": _S,
    "hash": frozenset({pa.string(), pa.int64()}),
    "faker": _S,
    "categorical": _S,
    "bucket_perturb": _S,
    "date_shift": _S,
    "fpe": _S,
}
_S1_ADDED = {"date_shift": frozenset({pa.date32()})}
_PROBE_TYPES = (
    pa.string(),
    pa.large_string(),
    pa.binary(),
    pa.null(),
    pa.bool_(),
    pa.int8(),
    pa.int16(),
    pa.int32(),
    pa.int64(),
    pa.uint8(),
    pa.uint16(),
    pa.uint32(),
    pa.uint64(),
    pa.float32(),
    pa.float64(),
    pa.decimal128(10, 2),
    pa.date32(),
    pa.date64(),
    pa.time32("s"),
    pa.time64("us"),
    pa.duration("s"),
    *(pa.timestamp(unit) for unit in ("s", "ms", "us", "ns")),
    *(pa.timestamp(unit, "UTC") for unit in ("s", "ms", "us", "ns")),
    pa.timestamp("us", "America/New_York"),
)


@dataclasses.dataclass(frozen=True)
class _Params:
    positional: bool = False


def _expected(strategy: str, mode: str) -> frozenset[pa.DataType]:
    from decoy_engine.execution._operator_registry import (
        DETERMINISTIC_FAKER_SOURCE_TYPES,
        POSITIONAL_FAKER_SOURCE_TYPES,
    )

    base = _PRE_CHANGE_DEFAULTS[strategy] | _S1_ADDED.get(strategy, frozenset())
    if strategy == "faker" and mode == "positional":
        return base | POSITIONAL_FAKER_SOURCE_TYPES
    if strategy == "faker" and mode == "deterministic":
        return base | DETERMINISTIC_FAKER_SOURCE_TYPES
    return base


@pytest.mark.parametrize("mode", ["positional", "deterministic"])
@pytest.mark.parametrize("strategy", sorted(_PRE_CHANGE_DEFAULTS))
def test_t11_one_descriptor_admits_exactly_the_pre_change_domains(strategy: str, mode: str) -> None:
    domain = OPERATORS[strategy].resident_type_domain
    assert domain is not None
    params = _Params(positional=mode == "positional")
    admitted = frozenset(t for t in _PROBE_TYPES if domain.admits(t, params))
    assert admitted == _expected(strategy, mode) & frozenset(_PROBE_TYPES)
    # A node without a `positional` attribute (most operator params) takes the value-keyed mode.
    if mode == "deterministic":
        assert admitted == frozenset(t for t in _PROBE_TYPES if domain.admits(t, object()))


def test_t11_only_group_key_has_no_descriptor_and_no_temporal_type_but_date32_is_admitted() -> None:
    assert {k for k, spec in OPERATORS.items() if spec.resident_type_domain is None} == {
        "group_key"
    }
    temporal = [t for t in _PROBE_TYPES if pa.types.is_temporal(t)]
    for key, spec in OPERATORS.items():
        domain = spec.resident_type_domain
        if domain is None:
            continue
        for positional in (False, True):
            got = {t for t in temporal if domain.admits(t, _Params(positional=positional))}
            assert got == ({pa.date32()} if key == "date_shift" else set()), key


def test_t11_operator_spec_has_none_of_the_three_old_fields() -> None:
    names = {f.name for f in dataclasses.fields(OperatorSpec)}
    assert "resident_type_domain" in names
    assert not names & {
        "unified_resident_types",
        "positional_resident_types",
        "deterministic_resident_types",
    }


def test_t11_an_unknown_family_name_is_refused() -> None:
    from decoy_engine.execution._operator_registry import ResidentTypeRule

    with pytest.raises(ValueError, match="unknown resident-type families"):
        ResidentTypeRule(exact=_S, families=frozenset({"zoned_timestamp"}))
