"""The masking `CompositeHandler` output, pinned as canonical Arrow fingerprints.

GEN-PROVIDERS E2 moves every composite's constructor call into one factory table. These digests
were captured on the code before that move, for each of the six composites in deterministic mode
(keyed by `mask_key`) and non-deterministic mode (seeded by `job_seed`), so the refactor cannot
change a masking byte. A digest that moves is a masking output change, not a test to update.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._runner import WorkNode
from decoy_engine.execution._strategies._composite import CompositeHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceBinding, NamespaceRegistry
from tests.parity._f0_canonical import table_fingerprint

ROWS = 12
JOB_SEED = (0x1122334455667788).to_bytes(8, "big")
MASK_KEY = bytes(range(32))
CUSTOM_BUNDLE = [
    {"column": "a", "provider": "person_first_name"},
    {"column": "b", "provider": "person_last_name"},
]
# provider -> (the columns the handler writes, the provider_config its ColumnSeed carries)
CASES: dict[str, tuple[tuple[str, ...], tuple[tuple[str, Any], ...]]] = {
    "composite_name_email": (("email", "first_name", "last_name"), ()),
    "composite_city_state_zip": (("city", "state", "zip"), ()),
    "composite_person": (("dob", "email", "first_name", "last_name"), ()),
    "composite_address": (("city", "state", "street_address", "zip"), ()),
    "composite_provider": (("npi", "practice_address", "provider_name"), ()),
    "composite_custom": (("a", "b"), (("bundle", CUSTOM_BUNDLE),)),
}
# Captured on the pre-refactor handler (origin/main 104dfb442): provider -> mode -> table digest.
EXPECTED: dict[str, dict[str, str]] = {
    "composite_name_email": {
        "keyed": "8635458cc3dc01cb2424f21aeb673c596a259d26ea8c474f6db6e7113b7b94bf",
        "fresh": "ce80368c8c724f6de53cd1dbef0b09e75fc7b50676d79ede8c67c30fc63787db",
    },
    "composite_city_state_zip": {
        "keyed": "e53efe7a380f9142e8360714e85e1cae718250f4b2dfc9c6b86bc749a9076648",
        "fresh": "e5f088cf54e791b5f12ed61ef621bd00e8bba41792e5795ba977a9235cab8a38",
    },
    "composite_person": {
        "keyed": "c33c0a3afb2a3b4b9996a6539f07e36c794ea38166b69880547d07041f883f31",
        "fresh": "0efa2114a99757419226ad115e11bfd036b558634b5097e9b241f34c2162a987",
    },
    "composite_address": {
        "keyed": "5be56b199668f0fa754303d7f61bb83a61863148c388d859e9aab7ec81d8bf87",
        "fresh": "3754f456b332ade5018cf66a274fd36e361927a24e98edb5501b260d97eefcfa",
    },
    "composite_provider": {
        "keyed": "47f9d6e94043a8b257a85a82b37a19142cc0e0ba7159f5c997a11f153a27b62b",
        "fresh": "ff43c1543bf333ce993c3b67138c6a17704d7430b7da6ff253979a232ccd92ae",
    },
    "composite_custom": {
        "keyed": "0d9ee67fa9e3f3ea3ac8ebf16d825a923720e90a801b1d284fdc53836183d303",
        "fresh": "bafe5ebf319642466d191df8d0cc46893ea009e390e109a26b2ca0c4f6284e80",
    },
}


def _frame(columns: tuple[str, ...]) -> pd.DataFrame:
    """Source values per column; the first sorted column is the deterministic key, with a null."""
    data: dict[str, list[Any]] = {c: [f"{c}-{i}" for i in range(ROWS)] for c in columns}
    data[columns[0]][3] = None
    return pd.DataFrame(data)


def run_handler(provider: str, *, deterministic: bool) -> pa.Table:
    columns, provider_config = CASES[provider]
    node = WorkNode(
        table="t",
        columns=columns,
        kind="composite",
        strategy="<composite>",
        provider=provider,
        plan_slice=ColumnSeed(
            namespace=None,
            strategy="<composite>",
            provider=provider,
            backend_type="faker",
            backend_version="v",
            cardinality_mode="reuse",
            deterministic=deterministic,
            provider_config=provider_config,
            coherent_with=columns[1:],
        ),
    )
    ctx = StrategyContext(
        registry=get_default_registry(),
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(
            bindings=(NamespaceBinding(namespace="ns", declared_by=(("t", columns),)),)
        ),
        job_seed=JOB_SEED,
        mask_key=MASK_KEY,
    )
    out, _ = CompositeHandler().run(_frame(columns), node, ctx)
    return pa.Table.from_pandas(out, preserve_index=False)


def digests() -> dict[str, dict[str, str]]:
    return {
        provider: {
            mode: table_fingerprint(run_handler(provider, deterministic=mode == "keyed"))["table"]
            for mode in ("keyed", "fresh")
        }
        for provider in CASES
    }


@pytest.mark.parametrize("mode", ["keyed", "fresh"])
@pytest.mark.parametrize("provider", sorted(CASES))
def test_the_handler_output_matches_its_pre_refactor_digest(provider: str, mode: str) -> None:
    got = table_fingerprint(run_handler(provider, deterministic=mode == "keyed"))["table"]
    assert got == EXPECTED[provider][mode]


def test_a_malformed_custom_bundle_is_refused_by_the_handler() -> None:
    columns = ("a", "b")
    node = WorkNode(
        table="t",
        columns=columns,
        kind="composite",
        strategy="<composite>",
        provider="composite_custom",
        plan_slice=ColumnSeed(
            namespace=None,
            strategy="<composite>",
            provider="composite_custom",
            backend_type="faker",
            backend_version="v",
            cardinality_mode="reuse",
            deterministic=True,
            provider_config=(("bundle", "notalist"),),
            coherent_with=("b",),
        ),
    )
    ctx = StrategyContext(
        registry=get_default_registry(),
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(
            bindings=(NamespaceBinding(namespace="ns", declared_by=(("t", columns),)),)
        ),
        job_seed=JOB_SEED,
    )
    with pytest.raises(ExecutionError) as exc:
        CompositeHandler().run(_frame(columns), node, ctx)
    assert exc.value.code == "composite_custom_bundle_shape"
