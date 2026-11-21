"""`type: provider`: values come from the masking provider registry through its own adapters.

Covers registry presence, per-provider validity at 1,000 rows, determinism and committed
digests, the null mask, route behavior, the fixed-text error boundary and the draw-site mapping.
Mutants (run by hand, listed in the slice report): a fixed provider tuple missing one name,
`generate_batch` on the identifier path, a family other than `faker` for a seeded batch, the
null mask seeded from the value family, `raise ... from None` inside the `except` block.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.config import iter_generate_input_refs
from decoy_engine.config._generate_option_catalog import generate_option_catalog
from decoy_engine.config._generate_options import GENERATE_OPTIONS
from decoy_engine.config._tables import GENERATE_TYPES
from decoy_engine.determinism import DeterminismError
from decoy_engine.execution.native._capabilities import capabilities_for
from decoy_engine.execution.native._determinism_protocol import GEN_KIND_TO_SITE
from decoy_engine.generation import synthesize
from decoy_engine.generation._admission import ADMISSION_MATRIX, classify_plan
from decoy_engine.generation._pinned_compile import REJECTED_TYPES
from decoy_engine.generation.composite import CompositeError
from decoy_engine.generation.kinds import provider_generate
from decoy_engine.generation.pool._errors import GenerationError, PoolCapacityError
from decoy_engine.generators.derivation import GenDeriveContext, with_table
from decoy_engine.providers_v2 import ProviderError, get_default_registry
from decoy_engine.providers_v2.identifiers import (
    CusipValidator,
    EinValidator,
    IbanValidator,
    Icd10Validator,
    IdentifierError,
    MrnValidator,
    NdcValidator,
    NpiAdapter,
    NpiValidator,
    PanValidator,
    SsnValidator,
)
from tests.parity._f0_canonical import table_fingerprint
from tests.parity._fr0_support import partition_from_cuts, plan_of, run_resident
from tests.unit.generation.kinds._support import SEED, cfg, generate, one, table

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "gen_providers" / "scalar-digests.json"
ROWS = 1000
REGISTRY = get_default_registry()
SCALARS = sorted(p for p in REGISTRY.known_providers() if not p.startswith("composite_"))
VALIDATORS = {
    "synthetic_ssn": SsnValidator,
    "synthetic_ein": EinValidator,
    "synthetic_npi": NpiValidator,
    "synthetic_ndc": NdcValidator,
    "synthetic_mrn": MrnValidator,
    "synthetic_pan": PanValidator,
    "synthetic_icd10": Icd10Validator,
    "synthetic_iban": IbanValidator,
    "synthetic_cusip": CusipValidator,
}


def prov(provider: str, name: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"name": name or provider, "type": "provider", "provider": provider, **extra}


def all_scalars(rows: int, seed: int = SEED, extra: list[dict[str, Any]] | None = None) -> Any:
    return cfg([table("t", rows, [*(prov(p) for p in SCALARS), *(extra or [])])], seed)


@pytest.fixture(scope="module")
def big() -> pa.Table:
    return generate(all_scalars(ROWS))["t"]


# ---- registry presence ----------------------------------------------------------------------


def test_the_type_is_present_in_every_registry_that_lists_generate_types() -> None:
    assert "provider" in GENERATE_TYPES
    assert "provider" in generate_option_catalog()
    opts = GENERATE_OPTIONS["provider"]
    assert set(opts.keys) == {"provider", "locale", "field", "group"}
    assert tuple(opts.required) == ("provider",)
    assert ADMISSION_MATRIX["provider"][0] is False
    assert "provider" in REJECTED_TYPES
    # A provider reads no sibling column, so the one input resolver yields no edge for it.
    assert iter_generate_input_refs({"name": "t"}, {"name": "c", "type": "provider"}) == ()
    assert GEN_KIND_TO_SITE["provider"] == "gen.derive_context"
    caps = capabilities_for("provider")
    assert not caps.is_row_local and caps.is_order_sensitive and caps.is_global
    assert caps.needs_global_row_identity and not caps.output_type_is_static
    assert caps.key_source != "mask_key"


def test_the_proof_manifest_and_matrix_list_the_type() -> None:
    root = Path(__file__).resolve().parents[4]
    manifest = json.loads((root / "docs" / "proof-manifest.json").read_text())
    assert "provider" in manifest["generation_strategies"]
    assert manifest["surface"]["generate"] == 16  # GEN-INHERIT E1 adds the sixteenth
    assert "`provider`" in (root / "docs" / "capability-matrix.md").read_text()


def test_the_provider_option_validates_its_keys() -> None:
    from decoy_engine.config._generate_options import option_problems

    assert option_problems("provider", {"provider": "synthetic_npi", "locale": "en_US"}) == []
    assert option_problems("provider", {})
    assert option_problems("provider", {"provider": 5})


# ---- every live provider ---------------------------------------------------------------------


def test_every_identifier_has_a_checksum_validator() -> None:
    native = {p for p in SCALARS if REGISTRY.get_capabilities(p).backend_type == "decoy_native"}
    assert set(VALIDATORS) == native


@pytest.mark.parametrize("name", SCALARS)
def test_every_scalar_provider_generates_valid_values(name: str, big: pa.Table) -> None:
    values = big.column(name).to_pylist()
    assert len(values) == ROWS and all(v is not None for v in values)
    caps = REGISTRY.get_capabilities(name)
    if caps.format_regex:
        for v in values:
            assert re.fullmatch(caps.format_regex, v), name
            assert re.fullmatch(caps.format_regex, v + "\n") is None
    if name in VALIDATORS:
        assert all(VALIDATORS[name].is_valid(v) for v in values)
    assert len(set(map(str, values))) > 1


def test_every_provider_value_is_text_as_the_typing_claims(big: pa.Table) -> None:
    from decoy_engine.generation._numeric_typing import _generated_type

    cols = {("t", p): prov(p) for p in SCALARS}
    for p in SCALARS:
        assert _generated_type(cols, {}, {}, set(), ("t", p)) == pa.string(), p
        assert big.schema.field(p).type == pa.string(), p
        assert all(isinstance(v, str) for v in big.column(p).to_pylist()), p


# ---- determinism and committed digests -------------------------------------------------------


def _digests(table_: pa.Table) -> dict[str, str]:
    return {name: digest for name, digest in table_fingerprint(table_)["columns"]}


_CHILD = (
    "import json, sys\n"
    "from tests.unit.generation.kinds.test_provider import all_scalars, ROWS, _digests\n"
    "from tests.unit.generation.kinds._support import generate\n"
    "print(json.dumps(_digests(generate(all_scalars(ROWS))['t'])))\n"
)


def test_two_runs_are_identical(big: pa.Table) -> None:
    assert _digests(generate(all_scalars(ROWS))["t"]) == _digests(big)


def test_two_processes_with_different_hash_seeds_agree(big: pa.Table) -> None:
    root = Path(__file__).resolve().parents[4]
    outs = []
    for hash_seed in ("1", "99"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(root)}
        done = subprocess.run(  # noqa: S603  (fixed argv, no user input)
            [sys.executable, "-c", _CHILD], env=env, cwd=root, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr[-2000:]
        outs.append(json.loads(done.stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1] == _digests(big)


def test_a_different_seed_changes_every_provider() -> None:
    a = _digests(generate(all_scalars(200, seed=1))["t"])
    b = _digests(generate(all_scalars(200, seed=2))["t"])
    assert all(a[p] != b[p] for p in SCALARS)


def test_an_unrelated_column_changes_nothing() -> None:
    plain = _digests(generate(all_scalars(200))["t"])
    extra = {"name": "zz", "type": "constant", "value": 1}
    more = _digests(generate(all_scalars(200, extra=[extra]))["t"])
    assert all(plain[p] == more[p] for p in SCALARS)


# The Faker and Mimesis backed providers pin Faker output, so their digests live with the Faker
# output lock (`tests/sentry/dependencies/test_faker_output_lock_providers.py`). Only the keyed
# identifiers, which draw no Faker output, are pinned in the default loop.
NATIVE_SCALARS = sorted(
    p for p in SCALARS if REGISTRY.get_capabilities(p).backend_type == "decoy_native"
)


def test_every_native_provider_matches_its_committed_digest(big: pa.Table) -> None:
    committed = json.loads(FIXTURE.read_text())["scalars"]
    assert sorted(committed) == NATIVE_SCALARS
    got = _digests(big)
    assert {p: got[p] for p in NATIVE_SCALARS} == committed


# ---- null mask -------------------------------------------------------------------------------


def _col(name: str, **extra: Any) -> dict[str, Any]:
    return prov("synthetic_npi", name, **extra)


def test_nulls_come_from_the_np_family_and_leave_values_alone() -> None:
    n = 500
    base = synthesize._generate_column(_col("x"), n, SEED, table_name="t")
    with_nulls = synthesize._generate_column(
        _col("x", null_probability=0.3), n, SEED, table_name="t"
    )
    ctx = GenDeriveContext.for_column(
        derive_key=None,
        column_config=with_table(_col("x", null_probability=0.3), "t"),
        fallback_seed=SEED,
    )
    expected = np.random.default_rng(ctx.base_int("np")).random(n) < 0.3
    assert [v is None for v in with_nulls] == expected.tolist()
    assert [b for b, e in zip(with_nulls, expected, strict=True) if not e] == [
        b for b, e in zip(base, expected, strict=True) if not e
    ]


def test_the_null_digest_is_committed() -> None:
    n = 500
    values = synthesize._generate_column(_col("x", null_probability=0.3), n, SEED, table_name="t")
    got = table_fingerprint(pa.table({"x": values}))["table"]
    assert got == json.loads(FIXTURE.read_text())["nulls"]["synthetic_npi:0.3:500"]


# ---- routes ----------------------------------------------------------------------------------


def test_streamed_admission_declines_and_the_fallback_equals_the_resident_output() -> None:
    config = one(prov("synthetic_npi", "x"), rows=300)
    adm = classify_plan(json.loads(plan_of(config).generation.config_json))
    assert not adm.eligible
    direct = generate(config)["t"].column("x").to_pylist()
    assert run_resident(config)["t"].column("x").to_pylist() == direct
    assert (
        run_resident(config, partition_from_cuts({"t": [7, 100]}))["t"].column("x").to_pylist()
        == direct
    )


def test_a_reference_child_draws_only_parent_values() -> None:
    config = cfg(
        [
            table("parent", 50, [prov("synthetic_npi", "id")]),
            table(
                "child",
                200,
                [
                    {
                        "name": "pid",
                        "type": "reference",
                        "reference_table": "parent",
                        "reference_column": "id",
                    }
                ],
            ),
        ]
    )
    out = generate(config)
    assert set(out["child"].column("pid").to_pylist()) <= set(
        out["parent"].column("id").to_pylist()
    )


def test_a_fresh_column_changes_across_runs() -> None:
    config = one(prov("synthetic_npi", "x", determinism="fresh"), rows=50)
    first = generate(config)["t"].column("x").to_pylist()
    assert first != generate(config)["t"].column("x").to_pylist()


# ---- fixed-text error boundary ---------------------------------------------------------------

SENTINEL = "SENTINEL-4c91e7"
ERRORS = [
    lambda: ProviderError(code="x", message=SENTINEL),
    lambda: IdentifierError(code="x", message=SENTINEL),
    lambda: DeterminismError(code="x", message=SENTINEL),
    lambda: PoolCapacityError(code="x", message=SENTINEL),
    lambda: GenerationError(code="x", message=SENTINEL),
    lambda: CompositeError(code="x", message=SENTINEL),
]


def _direct(provider: str, registry: Any = REGISTRY, locale: str = "en_US") -> list[Any]:
    col = with_table(prov(provider, "x"), "t")
    ctx = GenDeriveContext.for_column(derive_key=None, column_config=col, fallback_seed=SEED)
    return list(provider_generate(col, 20, ctx, registry, locale))


def _assert_fixed_failure(info: pytest.ExceptionInfo[GenerationError], caplog: Any) -> None:
    exc = info.value
    assert exc.code == str(reasons.runtime.GENERATION_PROVIDER_FAILED)
    assert SENTINEL not in str(exc) and SENTINEL not in caplog.text
    assert "t" in str(exc) and "x" in str(exc)
    assert exc.__cause__ is None and exc.__context__ is None


def _patch_targets() -> list[tuple[str, Any, str]]:
    from decoy_engine.generation.pool._builder import PoolBuilder
    from decoy_engine.providers_v2._faker_adapter import FakerAdapter

    return [
        ("synthetic_npi", NpiAdapter, "generate"),
        ("person_phone", PoolBuilder, "build"),
        ("uuid", FakerAdapter, "generate_batch"),
    ]


@pytest.mark.parametrize("make", ERRORS)
@pytest.mark.parametrize(("provider", "owner", "attr"), _patch_targets())
def test_an_adapter_or_pool_error_becomes_one_fixed_text_error(
    provider: str, owner: Any, attr: str, make: Any, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise make()

    monkeypatch.setattr(owner, attr, boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct(provider)
    _assert_fixed_failure(info, caplog)


def test_a_provider_removed_between_the_check_and_the_draw_fails_with_the_same_code(
    caplog: Any,
) -> None:
    from decoy_engine.providers_v2 import ProviderRegistry

    empty = ProviderRegistry({})
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct("synthetic_npi", empty)
    _assert_fixed_failure(info, caplog)


def test_a_capability_that_drops_the_locale_fails_with_the_same_code(caplog: Any) -> None:
    caps = REGISTRY.get_capabilities("synthetic_npi")
    other = caps.model_copy(update={"supported_locales": ("de_DE",)})
    registry = REGISTRY.override("synthetic_npi", NpiAdapter(), other)
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct("synthetic_npi", registry)
    _assert_fixed_failure(info, caplog)


def _npi(locale: str | None, instance_default: str | None = None) -> list[Any]:
    col = prov("synthetic_npi", "x", **({"locale": locale} if locale else {}))
    return synthesize._generate_column(
        col, 20, SEED, table_name="t", instance_default_locale=instance_default
    )


def test_a_column_locale_and_the_instance_default_reach_the_draw() -> None:
    """No scalar provider's output depends on the locale (every multi-locale one ignores it), so
    the locale is observable only as the draw's supported-locale refusal. `synthetic_npi` is
    `en_US` only: the column locale, then the instance default, then `en_US`, in that order."""
    ok = _npi(None)
    assert _npi("en_US", "de_DE") == _npi("en_US")
    assert _npi(None, "en_US") == ok
    with pytest.raises(GenerationError):
        _npi("de_DE")
    with pytest.raises(GenerationError):
        _npi(None, "de_DE")


# ---- draw sites ------------------------------------------------------------------------------


def test_the_draw_site_catalogue_gains_no_site() -> None:
    from decoy_engine.execution.native._determinism_protocol import PROVIDER_IDENTIFIER_SITES

    assert set(PROVIDER_IDENTIFIER_SITES.values()) == {"gen.identifier_deterministic"}


def test_a_value_whose_str_raises_becomes_the_value_free_error(monkeypatch) -> None:
    from decoy_engine.generation.kinds import _provider

    class Leaky:
        def __str__(self) -> str:
            raise RuntimeError("SECRET-CELL")

    monkeypatch.setattr(_provider, "_draw", lambda *a, **k: [Leaky()])
    col = {"name": "c", "type": "provider", "provider": "random_int_range"}
    with pytest.raises(GenerationError) as info:
        provider_generate(col, 1, None, None, "en_US")  # type: ignore[arg-type]
    exc = info.value
    assert exc.__cause__ is None and exc.__context__ is None
    assert "SECRET-CELL" not in str(exc)
