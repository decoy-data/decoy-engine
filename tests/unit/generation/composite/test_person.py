"""MG-4 Step 3 (2026-05-31): composite_person regression cells.

Locks the 4-output (first/last/email/dob) coherent bundle:
- All 4 outputs present + same length.
- Email matches the {first}.{last}@{domain} default format.
- Email format override works.
- DOB drawn from the faker person_dob pool.
- Same source -> same 4-tuple across runs (identity stability).
- Null source -> all-null row.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest
from faker.providers.person.en_US import Provider as _EnUs

from decoy_engine.determinism import derive, resolve_seed
from decoy_engine.generation._dob_anchor import age_on_anchor
from decoy_engine.generation.composite import CompositeError
from decoy_engine.generation.composite._person import CompositePerson
from decoy_engine.generation.pool._canonicalize import _canonicalize_source
from decoy_engine.providers_v2._adapter import ProviderSpec

_SEED = (0x0123456789).to_bytes(8, "big")


def _spec(extra: dict | None = None) -> ProviderSpec:
    return ProviderSpec(
        locale="en_US",
        deterministic=True,
        namespace="p",
        seed=_SEED,
        extra=extra or {},
    )


def _make(pool_size: int = 200) -> CompositePerson:
    return CompositePerson(coherent_namespace="p", pool_size=pool_size)


class TestOutputs:
    def test_person_4_outputs_match_output_columns(self):
        c = _make()
        out = c.generate_bundle(_spec(), 3, source=pd.Series(["a", "b", "c"]), deterministic=True)
        assert set(out.keys()) == {"first_name", "last_name", "email", "dob"}
        for k in out:
            assert len(out[k]) == 3

    def test_person_email_matches_first_dot_last_at_domain(self):
        c = _make()
        out = c.generate_bundle(_spec(), 1, source=pd.Series(["alice"]), deterministic=True)
        first = str(out["first_name"].iloc[0]).lower()
        last = str(out["last_name"].iloc[0]).lower()
        email = out["email"].iloc[0]
        assert email.startswith(f"{first}.{last}@")

    def test_person_email_format_override_works(self):
        c = _make()
        out = c.generate_bundle(
            _spec(extra={"email_format": "{last}_{first}@{domain}"}),
            1,
            source=pd.Series(["alice"]),
            deterministic=True,
        )
        first = str(out["first_name"].iloc[0]).lower()
        last = str(out["last_name"].iloc[0]).lower()
        email = out["email"].iloc[0]
        assert email.startswith(f"{last}_{first}@")

    def test_person_dob_drawn_from_faker_date_pool(self):
        c = _make()
        out = c.generate_bundle(_spec(), 3, source=pd.Series(["a", "b", "c"]), deterministic=True)
        # All non-null dobs are real date objects (faker.date_of_birth -> datetime.date).
        for d in out["dob"]:
            assert isinstance(d, datetime.date)


class TestIdentityStability:
    def test_person_identity_stable_across_runs(self):
        c1 = _make()
        c2 = _make()
        src = pd.Series(["alpha", "beta"])
        out1 = c1.generate_bundle(_spec(), 2, source=src, deterministic=True)
        out2 = c2.generate_bundle(_spec(), 2, source=src, deterministic=True)
        for k in ("first_name", "last_name", "email", "dob"):
            assert out1[k].tolist() == out2[k].tolist()


class TestNullHandling:
    def test_person_null_source_handling(self):
        c = _make()
        src = pd.Series(["alpha", None, "beta"])
        out = c.generate_bundle(_spec(), 3, source=src, deterministic=True)
        for k in ("first_name", "last_name", "email", "dob"):
            assert pd.isna(out[k].iloc[1])
        # Row 0 + 2 are populated.
        assert not pd.isna(out["first_name"].iloc[0])
        assert not pd.isna(out["first_name"].iloc[2])


FEMALE = set(_EnUs.first_names_female)
MALE = set(_EnUs.first_names_male)
BASE = ("first_name", "last_name", "email", "dob")


def _bundle(optional: set[str], n: int = 400, extra: dict | None = None) -> dict[str, pd.Series]:
    c = CompositePerson(coherent_namespace="p", pool_size=300, optional_fields=frozenset(optional))
    src = pd.Series([f"row{i}" for i in range(n)])
    return c.generate_bundle(_spec(extra), n, source=src, deterministic=True)


class TestOptionalFields:
    def test_the_canonical_columns_never_include_the_optional_ones(self):
        assert CompositePerson.output_columns == ("dob", "email", "first_name", "last_name")
        assert set(CompositePerson.optional_columns) == {"age", "sex"}

    def test_no_optional_field_gives_exactly_the_four_canonical_columns(self):
        assert set(_bundle(set())) == set(BASE)

    def test_sex_and_age_are_added_only_when_requested(self):
        assert set(_bundle({"sex"})) == {*BASE, "sex"}
        assert set(_bundle({"age"})) == {*BASE, "age"}
        assert set(_bundle({"sex", "age"})) == {*BASE, "sex", "age"}

    def test_a_field_the_composite_does_not_have_is_refused(self):
        with pytest.raises(CompositeError):
            CompositePerson(coherent_namespace="p", optional_fields=frozenset({"height"}))

    def test_every_first_name_comes_from_the_pool_of_its_rows_sex(self):
        out = _bundle({"sex"}, 600)
        assert set(out["sex"]) == {"F", "M"}
        for sex, first in zip(out["sex"], out["first_name"], strict=True):
            assert first in (FEMALE if sex == "F" else MALE)
        # 13 names are in both lists (Faker 40.23), so a unisex draw shows in the names that are
        # in one list only.
        for sex, first in zip(out["sex"], out["first_name"], strict=True):
            assert first not in ((MALE - FEMALE) if sex == "F" else (FEMALE - MALE))

    def test_age_is_whole_years_from_dob_to_the_anchor(self):
        out = _bundle({"age"}, 500)
        for dob, age in zip(out["dob"], out["age"], strict=True):
            assert age == age_on_anchor(dob)
            assert isinstance(age, int)

    def test_age_alone_changes_no_other_column(self):
        base = _bundle(set())
        with_age = _bundle({"age"})
        for k in BASE:
            assert base[k].tolist() == with_age[k].tolist()

    def test_sex_changes_the_first_name_and_nothing_else_in_the_base(self):
        base = _bundle(set())
        with_sex = _bundle({"sex"})
        assert base["first_name"].tolist() != with_sex["first_name"].tolist()
        for k in ("last_name", "dob"):
            assert base[k].tolist() == with_sex[k].tolist()

    def test_the_email_follows_the_sex_keyed_first_name(self):
        out = _bundle({"sex"})
        for first, last, email in zip(
            out["first_name"], out["last_name"], out["email"], strict=True
        ):
            assert email.startswith(f"{first}.{last}@".lower())

    def test_sex_is_stable_for_a_source_and_split_roughly_evenly(self):
        a = _bundle({"sex"}, 2000)
        b = _bundle({"sex"}, 2000)
        assert a["sex"].tolist() == b["sex"].tolist()
        assert 0.45 < (a["sex"] == "F").mean() < 0.55

    def test_null_sources_give_null_sex_and_age(self):
        c = CompositePerson(
            coherent_namespace="p", pool_size=100, optional_fields=frozenset({"sex", "age"})
        )
        out = c.generate_bundle(_spec(), 3, source=pd.Series(["a", None, "b"]), deterministic=True)
        assert pd.isna(out["sex"].iloc[1]) and pd.isna(out["age"].iloc[1])
        assert not pd.isna(out["sex"].iloc[0]) and not pd.isna(out["age"].iloc[2])

    def test_the_pool_build_without_optional_fields_is_unchanged(self):
        c = _make()
        pool = c.build_pool(_spec(), size=5)
        assert pool.output_columns == ("dob", "email", "first_name", "last_name")

    def test_a_pool_draw_without_a_source_refuses_optional_fields(self):
        c = CompositePerson(
            coherent_namespace="p", pool_size=50, optional_fields=frozenset({"sex"})
        )
        with pytest.raises(CompositeError):
            c.generate_bundle(_spec(), 3, deterministic=False)
        with pytest.raises(CompositeError):
            c.build_pool(_spec(), size=3)

    def test_sex_is_the_low_bit_of_the_ext_derive_not_of_the_main_latent(self):
        """Pins the second derive: sex comes from `namespace + "/ext"`, byte 0, low bit.

        A sex read from the main latent (a different derive) would fail this on about half the
        rows, and drawing both from one latent would couple sex to the other slots.
        """
        seed = resolve_seed(_SEED)
        sources = [f"row{i}" for i in range(300)]
        c = CompositePerson(
            coherent_namespace="p", pool_size=100, optional_fields=frozenset({"sex"})
        )
        out = c.generate_bundle(_spec(), 300, source=pd.Series(sources), deterministic=True)
        for src, sex in zip(sources, out["sex"], strict=True):
            ext = derive(seed, "p/ext", _canonicalize_source(src))
            assert sex == ("F" if ext[0] & 1 == 0 else "M")
