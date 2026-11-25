"""One frozen descriptor per native masking operator: the single home of shared per-operator facts.

Before this module the same facts (operator id, backend, compiled kernel, resident types,
assembly shape, provider allowlist) were hand-written in about a dozen parallel tables, so
adding an operator edited 8-14 files and a missed table drifted silently. Each of those
tables is now a one-line derivation over `OPERATORS`, keeping its old name and type.

Adding an operator means one `OperatorSpec` here plus its kernel-call branch and its
route-specific gates. Route-specific contracts (chunked source-type domains, degenerate
output handling, the two evidence records, missing-companion handling, date_shift's error
channel, group_key's sibling check) deliberately stay in their route modules.

Leaf module: stdlib and pyarrow only. Cheap unified-slice admission imports this at process
start and must never reach `execution.physical`, and the backend vocabulary lives here
because `native/_chunked_evidence.py` (which imports the planner) cannot be imported back
without a cycle. `native/_chunked_evidence.py` re-exports the vocabulary names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

import pyarrow as pa

__all__ = [
    "ARROW_PYTHON",
    "DETERMINISTIC_FAKER_SOURCE_TYPES",
    "OPERATORS",
    "PANDAS_ORACLE",
    "POSITIONAL_FAKER_SOURCE_TYPES",
    "PYTHON_PANDAS",
    "PYTHON_SCALAR",
    "RUST_COMPANION",
    "RUST_POOL_SELECT",
    "OperatorSpec",
    "ResidentTypeDomain",
    "ResidentTypeRule",
    "operator_spec",
]

# The backend vocabulary the chunked route's evidence and the unified slice share.
RUST_COMPANION: Final = "rust_companion"
RUST_POOL_SELECT: Final = "rust_pool_select"
ARROW_PYTHON: Final = "arrow_python"
PANDAS_ORACLE: Final = "pandas_oracle"
# The out-of-core route's per-value Python kernels (`kernel/_scalar`): neither the pandas oracle nor
# an Arrow-Python kernel, so its hash loop must not borrow either label in caller-visible evidence.
PYTHON_SCALAR: Final = "python_scalar"
# The out-of-core route's declined bucket_perturb path: `apply_bucket_perturb` over a pandas Series.
# Not the whole-frame pandas oracle route, and not a per-value scalar loop either.
PYTHON_PANDAS: Final = "python_pandas"

Shape = Literal["kernel", "pool"]
RequiredKernel = Literal["crypto", "index", "raw_hex", "fpe"]
AssemblyShape = Literal["tokenizing", "null_on_empty", "type_preserving"]


# Named resident-type families, evaluated here and nowhere else. A family covers types that an
# exact set cannot list (a timezone is a free string). Empty until a slice proves one.
_RESIDENT_TYPE_FAMILIES: Final[Mapping[str, Callable[[pa.DataType], bool]]] = MappingProxyType({})


@dataclass(frozen=True)
class ResidentTypeRule:
    """One admitted domain: an exact-type set plus any named families from the central vocabulary."""

    exact: frozenset[pa.DataType]
    families: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        unknown = self.families - _RESIDENT_TYPE_FAMILIES.keys()
        if unknown:
            raise ValueError(f"unknown resident-type families: {sorted(unknown)!r}")

    def admits(self, resident_type: pa.DataType) -> bool:
        return resident_type in self.exact or any(
            _RESIDENT_TYPE_FAMILIES[name](resident_type) for name in self.families
        )


@dataclass(frozen=True)
class ResidentTypeDomain:
    """The resident types one operator admits, per keying variant.

    `positional` applies to a position-keyed node (it reads only the null mask, so it admits
    more); `deterministic` applies to a value-keyed node of an operator that has one (C5c-ii
    Faker: string plus bool/int/uint). A variant left `None` falls back to `default`."""

    default: ResidentTypeRule
    positional: ResidentTypeRule | None = None
    deterministic: ResidentTypeRule | None = None

    def rule_for(self, params: Any) -> ResidentTypeRule:
        """The rule for a node bound with `params` (a node's `positional` flag picks the variant)."""
        variant = self.positional if getattr(params, "positional", False) else self.deterministic
        return variant if variant is not None else self.default

    def admits(self, resident_type: pa.DataType, params: Any) -> bool:
        """Whether a node bound with `params` admits a target column of `resident_type`."""
        return self.rule_for(params).admits(resident_type)


def _exact(types: frozenset[pa.DataType]) -> ResidentTypeDomain:
    return ResidentTypeDomain(default=ResidentTypeRule(exact=types))


@dataclass(frozen=True)
class OperatorSpec:
    """The facts about one native slice operator that more than one module needs.

    `resident_type_domain` is the target-column type domain the unified slice admits, asked
    only through `ResidentTypeDomain.admits`; `None` means "no target type gate", which is
    group_key (its admission checks the sibling column instead).
    `required_kernel` names the compiled kernel the operator loads, `None` for the
    pure-Arrow operators. `positive_kernel_evidence` marks operators whose "compiled kernel
    ran" claim must be observed rather than inferred. `routed_diagnostics` lists the
    diagnostic obligations the unified coordinator routes for the operator (a policy)."""

    strategy: str
    operator_id: str
    shape: Shape
    planned_backend: str
    required_kernel: RequiredKernel | None
    positive_kernel_evidence: bool
    resident_type_domain: ResidentTypeDomain | None
    full_frame_assembly: AssemblyShape
    provider_allowlist: frozenset[str] | None = None
    # Diagnostic obligations the unified-slice coordinator actually ROUTES for this
    # operator. A coordinator policy, not a capability fact: an operator whose
    # capabilities declare any diagnostic outside this set declines the unified slice.
    routed_diagnostics: frozenset[str] = frozenset()


_STRING_ONLY = frozenset({pa.string()})

# Source families whose pandas missingness the positional Faker step takes from the oracle's own
# conversion. Explicit instances, not a predicate: the registry compares exact datatypes.
POSITIONAL_FAKER_SOURCE_TYPES: Final = frozenset(
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

# C5c-ii: the DETERMINISTIC-Faker source families. bool/signed int/unsigned int only: the draw
# keys from the source VALUE through `_canonicalize_source`, which hard-errors on float and has no
# proven temporal sentinel path yet, so float and temporal are NOT admitted (unlike the
# position-keyed variant, which reads only the null mask and so admits float).
DETERMINISTIC_FAKER_SOURCE_TYPES: Final = frozenset(
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
    }
)

_SPECS = (
    OperatorSpec(
        strategy="passthrough",
        operator_id="native_passthrough",
        shape="kernel",
        planned_backend=ARROW_PYTHON,
        required_kernel=None,
        positive_kernel_evidence=False,
        resident_type_domain=_exact(frozenset({pa.string(), pa.int64(), pa.bool_()})),
        full_frame_assembly="type_preserving",
    ),
    OperatorSpec(
        strategy="redact",
        operator_id="native_redact",
        shape="kernel",
        planned_backend=ARROW_PYTHON,
        required_kernel=None,
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        full_frame_assembly="tokenizing",
    ),
    OperatorSpec(
        strategy="truncate",
        operator_id="native_truncate",
        shape="kernel",
        planned_backend=ARROW_PYTHON,
        required_kernel=None,
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        full_frame_assembly="tokenizing",
    ),
    OperatorSpec(
        strategy="text_redact",
        operator_id="native_text_redact",
        shape="kernel",
        planned_backend=ARROW_PYTHON,
        required_kernel=None,
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        # The oracle assigns an object column, so an empty or all-null result is Arrow null.
        full_frame_assembly="null_on_empty",
    ),
    OperatorSpec(
        strategy="text_mask",
        operator_id="native_text_mask",
        shape="kernel",
        planned_backend=ARROW_PYTHON,
        required_kernel=None,
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        # The handler assigns a fresh object column, so an empty or all-null result is Arrow
        # null on the full-frame route (same as text_redact); the chunked route pins string.
        full_frame_assembly="null_on_empty",
        # text_mask's handler builds one aggregate sub-floor warning per column, outside
        # `mask_cell` (Python-computed, transported on `ExecutionResult.warnings`, never on the
        # output). Declared here together with the capability warning so unified admission
        # routes it instead of declining (C6b-i).
        routed_diagnostics=frozenset({"reduce_warning:text_mask_sub_floor_span_handled"}),
    ),
    OperatorSpec(
        strategy="hash",
        operator_id="native_keyed_hash",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="crypto",
        positive_kernel_evidence=True,
        resident_type_domain=_exact(frozenset({pa.string(), pa.int64()})),
        full_frame_assembly="tokenizing",
    ),
    OperatorSpec(
        strategy="faker",
        operator_id="native_faker_select",
        shape="pool",
        planned_backend=RUST_POOL_SELECT,
        required_kernel="index",
        positive_kernel_evidence=True,
        resident_type_domain=ResidentTypeDomain(
            default=ResidentTypeRule(exact=_STRING_ONLY),
            positional=ResidentTypeRule(exact=_STRING_ONLY | POSITIONAL_FAKER_SOURCE_TYPES),
            deterministic=ResidentTypeRule(exact=_STRING_ONLY | DETERMINISTIC_FAKER_SOURCE_TYPES),
        ),
        full_frame_assembly="tokenizing",
        # The string-pool providers proven by tests/parity/test_faker_native_widen.py. Every
        # other pool_native provider is rejected with a coded reason rather than silently
        # admitted; tests/sentry/defects/test_faker_native_allowlist_total.py walks the live
        # registry so a new pool_native provider must be listed here or excluded there.
        provider_allowlist=frozenset(
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
        ),
    ),
    OperatorSpec(
        strategy="categorical",
        operator_id="native_categorical",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="index",
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        full_frame_assembly="tokenizing",
    ),
    OperatorSpec(
        strategy="bucket_perturb",
        operator_id="native_bucket_perturb",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="index",
        positive_kernel_evidence=False,
        resident_type_domain=_exact(_STRING_ONLY),
        # Differs from the tokenizing operators only on an empty column: it passes its
        # source object series through, which becomes an Arrow null column.
        full_frame_assembly="null_on_empty",
        routed_diagnostics=frozenset({"reduce_row_error:format_error"}),
    ),
    OperatorSpec(
        strategy="group_key",
        operator_id="native_group_key",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="raw_hex",
        positive_kernel_evidence=False,
        resident_type_domain=None,
        full_frame_assembly="tokenizing",
    ),
    OperatorSpec(
        strategy="date_shift",
        operator_id="native_date_shift",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="index",
        positive_kernel_evidence=False,
        # A typed `date32` source (plan shape DATE) shifts natively too (DATE-SHIFT-TYPED S1);
        # the config rejection checks the plan shape against the resident type.
        resident_type_domain=_exact(_STRING_ONLY | {pa.date32()}),
        full_frame_assembly="tokenizing",
        routed_diagnostics=frozenset({"reduce_row_error:format_error"}),
    ),
    OperatorSpec(
        strategy="fpe",
        operator_id="native_fpe",
        shape="kernel",
        planned_backend=RUST_COMPANION,
        required_kernel="fpe",
        # The compiled FF1 kernel runs over the source column, so its "the compiled kernel
        # ran" claim is observed (like hash), never inferred.
        positive_kernel_evidence=True,
        resident_type_domain=_exact(_STRING_ONLY),
        # The handler assigns a fresh Python list (`df[column] = out`), so an empty column
        # rounds through pandas as float64, an all-null one as null, an all-empty one as string
        # -- exactly the tokenizing reconciliation (C6a plan §3i). fpe stays OUT of the chunked
        # string-pinning set; its degenerate chunk types are reconciled in `_chunk_masking`.
        full_frame_assembly="tokenizing",
        # fpe emits two residual-risk warnings (Python-computed, transported on
        # `ExecutionResult.warnings`, never on the output); the fail-closed kill is a
        # `StrategyError`, not a routed RowError, so it carries no row-error obligation.
        routed_diagnostics=frozenset(
            {
                "reduce_warning:fpe_join_group_active",
                "reduce_warning:fpe_partial_plaintext_disclosure",
            }
        ),
    ),
)

# Keyed by strategy. Read-only so a consumer cannot mutate the shared facts.
OPERATORS: Final[Mapping[str, OperatorSpec]] = MappingProxyType(
    {spec.strategy: spec for spec in _SPECS}
)


def operator_spec(strategy: str) -> OperatorSpec:
    """The descriptor for `strategy`; raises `KeyError` for a strategy with no native slice operator."""
    return OPERATORS[strategy]
