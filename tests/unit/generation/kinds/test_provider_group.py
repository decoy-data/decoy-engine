"""`type: provider` composite groups: coherent person, address and provider columns.

Each composite output is its own generate column named by `field`; columns with the same
(provider, group) in one table take their values from one bundle. Covers row coherence at
10,000 rows, group identity (seed, order, names, tables, label reuse, stable and fresh),
reproducibility with committed digests, the null mask, the route behavior and the fixed-text
error boundary.

Mutants (run by hand on the final head, listed in the PR): a bundle seeded from each member's own
column root, a bundle cache keyed by group alone, a cache made once per run, `determinism` left out
of the group config, a changed constructor argument in a factory.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.determinism import DeterminismError
from decoy_engine.generation import synthesize
from decoy_engine.generation._admission import classify_plan
from decoy_engine.generation.composite import COMPOSITES, CompositeError, load_locality_table
from decoy_engine.generation.kinds._provider import provider_column_values
from decoy_engine.generation.kinds._provider_group import provider_group_values
from decoy_engine.generation.pool._errors import GenerationError, PoolCapacityError
from decoy_engine.generators.derivation import with_table
from decoy_engine.providers_v2 import ProviderError, get_default_registry
from decoy_engine.providers_v2.identifiers import IdentifierError, NpiValidator
from tests.parity._f0_canonical import table_fingerprint
from tests.parity._fr0_support import plan_of, run_resident
from tests.unit.generation.kinds._support import SEED, cfg, generate, one, table

FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "gen_providers" / "composite-digests.json"
)
REGISTRY = get_default_registry()
FIXED = sorted(n for n, d in COMPOSITES.items() if not d.variable_output)
LOCALITY = set(load_locality_table())


def member(provider: str, field: str, name: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "name": name or field,
        "type": "provider",
        "provider": provider,
        "field": field,
        **extra,
    }


def group_cols(provider: str, **extra: Any) -> list[dict[str, Any]]:
    """One column per output field of `provider`, named after the field."""
    return [member(provider, f, **extra) for f in COMPOSITES[provider].output_columns]


def run(cols: list[dict[str, Any]], rows: int = 200, seed: int = SEED) -> dict[str, list[Any]]:
    out = generate(cfg([table("t", rows, cols)], seed))["t"]
    return {name: out.column(name).to_pylist() for name in out.column_names}


# ---- coherence at 10,000 rows ----------------------------------------------------------------

ROWS = 10_000


@pytest.fixture(scope="module")
def big() -> dict[str, dict[str, list[Any]]]:
    return {p: run(group_cols(p), ROWS) for p in FIXED}


@pytest.mark.parametrize("provider", ["composite_person", "composite_name_email"])
def test_every_email_is_built_from_the_same_rows_name(
    provider: str, big: dict[str, dict[str, list[Any]]]
) -> None:
    out = big[provider]
    assert len(out["email"]) == ROWS
    for first, last, email in zip(out["first_name"], out["last_name"], out["email"], strict=True):
        assert email.split("@", 1)[0] == f"{first}.{last}".lower()


@pytest.mark.parametrize("provider", ["composite_city_state_zip", "composite_address"])
def test_every_city_state_zip_is_a_row_of_the_locality_table(
    provider: str, big: dict[str, dict[str, list[Any]]]
) -> None:
    out = big[provider]
    triples = zip(out["city"], out["state"], out["zip"], strict=True)
    assert all(t in LOCALITY for t in triples)


def test_every_provider_npi_passes_luhn_and_the_address_is_the_locality_text(
    big: dict[str, dict[str, list[Any]]],
) -> None:
    out = big["composite_provider"]
    assert all(NpiValidator.is_valid(v) for v in out["npi"])
    assert all(v and v.strip() for v in out["provider_name"])
    assert {a.split(", ")[0] for a in out["practice_address"]} <= {c for c, _, _ in LOCALITY}


@pytest.mark.parametrize("provider", FIXED)
def test_every_value_is_text_and_none_is_null(
    provider: str, big: dict[str, dict[str, list[Any]]]
) -> None:
    for field, values in big[provider].items():
        assert all(isinstance(v, str) for v in values), (provider, field)


# ---- group identity --------------------------------------------------------------------------


def person_fields(provider: str = "composite_person", **extra: Any) -> list[dict[str, Any]]:
    return group_cols(provider, **extra)


def test_two_groups_in_one_table_are_two_different_people() -> None:
    cols = [
        *person_fields(),
        *[
            member("composite_person", f, f"g_{f}", group="guardian")
            for f in ("first_name", "email")
        ],
        member("composite_person", "last_name", "g_last_name", group="guardian"),
    ]
    out = run(cols, 300)
    differing = sum(a != b for a, b in zip(out["first_name"], out["g_first_name"], strict=True))
    assert differing > 250
    for first, last, email in zip(
        out["g_first_name"], out["g_last_name"], out["g_email"], strict=True
    ):
        assert email.split("@", 1)[0] == f"{first}.{last}".lower()


def test_members_of_one_group_agree_row_for_row_in_any_order_under_any_name() -> None:
    base = run(person_fields(), 200)
    fields = COMPOSITES["composite_person"].output_columns
    reordered = run(list(reversed(person_fields())), 200)
    renamed_cols = [member("composite_person", f, f"renamed_{f}") for f in fields]
    renamed = run(renamed_cols, 200)
    extra = run([*person_fields(), {"name": "zz", "type": "constant", "value": 1}], 200)
    for f in fields:
        assert reordered[f] == base[f]
        assert renamed[f"renamed_{f}"] == base[f]
        assert extra[f] == base[f]
    assert len({tuple(base[f]) for f in fields}) == len(fields)


def test_a_subset_of_the_fields_gives_the_same_values_as_the_whole_group() -> None:
    whole = run(person_fields(), 100)
    some = run([member("composite_person", "email"), member("composite_person", "dob")], 100)
    assert some["email"] == whole["email"] and some["dob"] == whole["dob"]


def test_two_tables_with_the_same_group_name_do_not_share_a_bundle() -> None:
    config = cfg(
        [
            table("a", 100, person_fields(group="g")),
            table("b", 100, person_fields(group="g")),
        ]
    )
    out = generate(config)
    assert out["a"].column("first_name").to_pylist() != out["b"].column("first_name").to_pylist()


def test_composites_sharing_a_group_label_keep_their_own_bundles() -> None:
    cols = [
        *person_fields(group="x"),
        *[member("composite_address", f, f"a_{f}", group="x") for f in ("city", "state", "zip")],
        member("composite_address", "street_address", "a_street", group="x"),
    ]
    out = run(cols, 300)
    assert all(
        e.split("@", 1)[0] == f"{f}.{la}".lower()
        for f, la, e in zip(out["first_name"], out["last_name"], out["email"], strict=True)
    )
    assert all(t in LOCALITY for t in zip(out["a_city"], out["a_state"], out["a_zip"], strict=True))
    assert all(out["a_street"])


def test_a_stable_group_repeats_and_a_fresh_group_is_coherent_but_changes_across_runs() -> None:
    assert run(person_fields(), 100) == run(person_fields(), 100)
    fresh = person_fields(determinism="fresh")
    one_run, other = run(fresh, 100), run(fresh, 100)
    assert one_run["first_name"] != other["first_name"]
    for first, last, email in zip(
        one_run["first_name"], one_run["last_name"], one_run["email"], strict=True
    ):
        assert email.split("@", 1)[0] == f"{first}.{last}".lower()


def test_a_different_seed_changes_the_group() -> None:
    assert (
        run(person_fields(), 100, seed=1)["first_name"]
        != run(person_fields(), 100, seed=2)["first_name"]
    )


def test_an_explicit_locale_is_part_of_the_group_seed_and_en_us_is_accepted() -> None:
    plain = run(person_fields(), 50)
    explicit = run(person_fields(locale="en_US"), 50)
    for f in COMPOSITES["composite_person"].output_columns:
        assert explicit[f] == plain[f]


# ---- null mask -------------------------------------------------------------------------------


def test_a_members_nulls_are_its_own_and_leave_every_other_value_alone() -> None:
    plain = run(person_fields(), 400)
    cols = [
        member("composite_person", "first_name", null_probability=0.3),
        member("composite_person", "last_name"),
        member("composite_person", "email"),
    ]
    out = run(cols, 400)
    assert out["last_name"] == plain["last_name"] and out["email"] == plain["email"]
    nulls = [v is None for v in out["first_name"]]
    assert 0.2 < sum(nulls) / 400 < 0.4
    assert [b for b, n in zip(out["first_name"], nulls, strict=True) if not n] == [
        b for b, n in zip(plain["first_name"], nulls, strict=True) if not n
    ]


# ---- reproducibility and committed digests ---------------------------------------------------


def composite_config(
    rows: int = 500, seed: int = SEED, extra: list[dict[str, Any]] | None = None
) -> Any:
    cols = [member(p, f, f"{p}.{f}") for p in FIXED for f in COMPOSITES[p].output_columns]
    # A second person group asks for the optional slots, so the first group's bytes stay the E2 ones.
    optional = [
        member("composite_person", f, f"composite_person+.{f}", group="optional")
        for f in ("first_name", "sex", "age", "dob")
    ]
    return cfg([table("t", rows, [*cols, *optional, *(extra or [])])], seed)


def digests(table_: pa.Table) -> dict[str, str]:
    return dict(map(tuple, table_fingerprint(table_)["columns"]))


_CHILD = (
    "import json\n"
    "from tests.unit.generation.kinds.test_provider_group import composite_config, digests\n"
    "from tests.unit.generation.kinds._support import generate\n"
    "print(json.dumps(digests(generate(composite_config())['t'])))\n"
)


def test_two_runs_and_two_processes_with_different_hash_seeds_agree() -> None:
    here = digests(generate(composite_config())["t"])
    assert here == digests(generate(composite_config())["t"])
    root = Path(__file__).resolve().parents[4]
    outs = []
    for hash_seed in ("1", "99"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(root)}
        done = subprocess.run(  # noqa: S603  (fixed argv, no user input)
            [sys.executable, "-c", _CHILD], env=env, cwd=root, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr[-2000:]
        outs.append(json.loads(done.stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1] == here


def test_a_different_seed_changes_every_composite_output() -> None:
    a = digests(generate(composite_config(200, seed=1))["t"])
    b = digests(generate(composite_config(200, seed=2))["t"])
    assert all(a[k] != b[k] for k in a)


def test_an_unrelated_column_changes_nothing() -> None:
    extra = {"name": "zz", "type": "constant", "value": 1}
    plain = digests(generate(composite_config(200))["t"])
    more = digests(generate(composite_config(200, extra=[extra]))["t"])
    assert all(plain[k] == more[k] for k in plain)


# These outputs read the locality table or a keyed identifier, never Faker, so the default loop
# pins them. The rest draw names and dates from Faker and are pinned with the Faker output lock
# (`tests/sentry/dependencies/test_faker_output_lock_providers.py`).
FAKER_FREE = {
    f"composite_city_state_zip.{f}" for f in COMPOSITES["composite_city_state_zip"].output_columns
} | {
    "composite_address.city",
    "composite_address.state",
    "composite_address.zip",
    "composite_provider.npi",
    "composite_provider.practice_address",
}


def test_every_locality_and_identifier_output_matches_its_committed_digest() -> None:
    committed = json.loads(FIXTURE.read_text())
    got = digests(generate(composite_config())["t"])
    assert sorted(committed) == sorted(FAKER_FREE)
    assert {k: got[k] for k in FAKER_FREE} == committed


# ---- routes ----------------------------------------------------------------------------------


def test_streamed_admission_declines_and_the_resident_fallback_matches() -> None:
    config = one(member("composite_person", "email"), rows=300)
    adm = classify_plan(json.loads(plan_of(config).generation.config_json))
    assert not adm.eligible
    direct = generate(config)["t"].column("email").to_pylist()
    assert run_resident(config)["t"].column("email").to_pylist() == direct


def test_pinned_compile_refuses_a_composite_column() -> None:
    from decoy_engine.generation.pinned import PinnedModeError, compile_pinned_plan

    config = one(member("composite_person", "email"))
    config["global_settings"]["reference_date"] = "2026-10-22T09:30:00Z"
    with pytest.raises(PinnedModeError) as info:
        compile_pinned_plan(config)
    assert info.value.code == "pinned_provider_unsupported"


def test_a_reference_child_of_a_composite_column_draws_only_parent_values() -> None:
    config = cfg(
        [
            table("parent", 40, [member("composite_person", "email", "id")]),
            table(
                "child",
                100,
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


# ---- fixed-text error boundary ---------------------------------------------------------------

SENTINEL = "SENTINEL-9a02de"
ERRORS = [
    lambda: ProviderError(code="x", message=SENTINEL),
    lambda: IdentifierError(code="x", message=SENTINEL),
    lambda: DeterminismError(code="x", message=SENTINEL),
    lambda: PoolCapacityError(code="x", message=SENTINEL),
    lambda: GenerationError(code="x", message=SENTINEL),
    lambda: CompositeError(code="x", message=SENTINEL),
]


def _direct(registry: Any = REGISTRY, provider: str = "composite_person") -> list[Any]:
    col = with_table(member(provider, "first_name", "x"), "t")
    return provider_group_values(col, 20, SEED, None, registry, "en_US", {})


def _assert_fixed_failure(info: pytest.ExceptionInfo[GenerationError], caplog: Any) -> None:
    exc = info.value
    assert exc.code == str(reasons.runtime.GENERATION_PROVIDER_FAILED)
    assert SENTINEL not in str(exc) and SENTINEL not in caplog.text
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("make", ERRORS)
def test_a_composite_error_becomes_one_fixed_text_error(
    make: Any, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    from decoy_engine.generation.composite import CompositePerson

    def boom(*_a: Any, **_k: Any) -> Any:
        raise make()

    monkeypatch.setattr(CompositePerson, "generate_bundle", boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct()
    _assert_fixed_failure(info, caplog)


def test_a_provider_removed_between_the_check_and_the_draw_fails_with_the_same_code(
    caplog: Any,
) -> None:
    from decoy_engine.providers_v2 import ProviderRegistry

    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct(ProviderRegistry({}))
    _assert_fixed_failure(info, caplog)


def test_a_capability_that_drops_the_locale_fails_with_the_same_code(caplog: Any) -> None:
    from decoy_engine.generation.composite import CompositeAdapter

    caps = REGISTRY.get_capabilities("composite_person")
    other = caps.model_copy(update={"supported_locales": ("de_DE",)})
    registry = REGISTRY.override("composite_person", CompositeAdapter("composite_person"), other)
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as info:
        _direct(registry)
    _assert_fixed_failure(info, caplog)


def test_a_missing_field_in_the_bundle_is_the_same_fixed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    col = with_table(member("composite_person", "no_such_field", "x"), "t")
    with pytest.raises(GenerationError) as info:
        provider_column_values(col, 5, SEED, None, None, {})
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_the_bundle_cache_is_filled_once_per_group() -> None:
    cache: dict[Any, Any] = {}
    col = with_table(member("composite_person", "first_name", "a"), "t")
    first = provider_column_values(col, 30, SEED, None, None, cache)
    assert list(cache) == [("composite_person", "composite_person")]
    cached = cache[("composite_person", "composite_person")]
    other = with_table(member("composite_person", "last_name", "b"), "t")
    provider_column_values(other, 30, SEED, None, None, cache)
    assert cache[("composite_person", "composite_person")] is cached
    assert provider_column_values(col, 30, SEED, None, None, cache) == first


def test_generate_column_reads_the_table_cache_it_is_given() -> None:
    cache: dict[Any, Any] = {}
    col = member("composite_person", "first_name")
    synthesize._generate_column(col, 10, SEED, table_name="t", bundles=cache)
    assert ("composite_person", "composite_person") in cache


def test_a_group_member_drawn_without_a_table_cache_is_a_programming_error() -> None:
    """A fresh group draws an OS-entropy root per bundle, so a missing cache would make each member
    its own person without any error."""
    col = with_table(member("composite_person", "first_name", "a", determinism="fresh"), "t")
    with pytest.raises(RuntimeError):
        provider_column_values(col, 5, SEED, None, None, None)
    with pytest.raises(RuntimeError):
        synthesize._generate_column(col, 5, SEED, table_name="t")


# ---- E3: sex and age on composite_person -----------------------------------------------------

SEX_ROWS = 20_000


@pytest.fixture(scope="module")
def sexed() -> dict[str, list[Any]]:
    cols = [
        member("composite_person", f)
        for f in ("first_name", "last_name", "email", "dob", "sex", "age")
    ]
    return run(cols, SEX_ROWS)


def test_every_first_name_comes_from_the_pool_of_its_rows_sex_at_20000_rows(
    sexed: dict[str, list[Any]],
) -> None:
    from faker.providers.person.en_US import Provider

    female, male = set(Provider.first_names_female), set(Provider.first_names_male)
    assert set(sexed["sex"]) == {"F", "M"}
    for sex, first in zip(sexed["sex"], sexed["first_name"], strict=True):
        assert first in (female if sex == "F" else male)
        assert first not in ((male - female) if sex == "F" else (female - male))
    share = sexed["sex"].count("F") / SEX_ROWS
    assert 0.45 < share < 0.55


def test_age_is_whole_years_from_dob_to_the_anchor_on_every_row(
    sexed: dict[str, list[Any]],
) -> None:
    import datetime as dt

    from decoy_engine.generation._dob_anchor import DOB_ANCHOR

    for dob, age in zip(sexed["dob"], sexed["age"], strict=True):
        born = dt.date.fromisoformat(dob)
        years = (
            DOB_ANCHOR.year
            - born.year
            - ((DOB_ANCHOR.month, DOB_ANCHOR.day) < (born.month, born.day))
        )
        assert age == str(years)


def test_sex_and_age_are_text_like_every_other_provider_value(sexed: dict[str, list[Any]]) -> None:
    assert all(isinstance(v, str) for v in sexed["sex"])
    assert all(isinstance(v, str) and v.isdigit() for v in sexed["age"])


def test_the_email_follows_the_sex_keyed_name_and_the_members_agree_in_any_order() -> None:
    fields = ("first_name", "last_name", "email", "sex", "age")
    cols = [member("composite_person", f) for f in fields]
    base = run(cols, 300)
    assert run(list(reversed(cols)), 300) == base
    renamed = run([member("composite_person", f, f"x_{f}") for f in fields], 300)
    assert {k: renamed[f"x_{k}"] for k in fields} == base
    for first, last, email in zip(
        base["first_name"], base["last_name"], base["email"], strict=True
    ):
        assert email.split("@", 1)[0] == f"{first}.{last}".lower()


def test_asking_for_age_changes_no_other_value_and_asking_for_sex_changes_only_the_first_name() -> (
    None
):
    plain = run(person_fields(), 300)
    with_age = run([*person_fields(), member("composite_person", "age")], 300)
    with_sex = run([*person_fields(), member("composite_person", "sex")], 300)
    for f in plain:
        assert with_age[f] == plain[f]
    assert with_sex["first_name"] != plain["first_name"]
    assert with_sex["dob"] == plain["dob"] and with_sex["last_name"] == plain["last_name"]


def test_a_group_that_does_not_ask_for_sex_is_untouched_by_another_group_that_does() -> None:
    guardian = [
        member("composite_person", f, f"g_{f}", group="guardian") for f in ("first_name", "email")
    ]
    alone = run([*person_fields(), *guardian], 300)
    mixed = run(
        [*person_fields(), *guardian, member("composite_person", "sex", "g_sex", group="guardian")],
        300,
    )
    for f in person_fields():
        assert mixed[f["name"]] == alone[f["name"]]
    assert mixed["g_first_name"] != alone["g_first_name"]


def test_a_member_alone_can_ask_for_sex_without_the_rest_of_its_group() -> None:
    out = run([member("composite_person", "sex")], 50)
    assert set(out["sex"]) <= {"F", "M"}
