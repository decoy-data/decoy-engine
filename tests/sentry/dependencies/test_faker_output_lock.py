"""Sentry: Faker output may not move unseen (FAKER-MIGRATE, AT-L1, AT-L3 to AT-L6, AT-L8, AT-L9,
AT-L11, AT-L13).

`scripts/faker-determinism/output_lock.json` records, for every Faker locale, digests of what the
engine's Faker surfaces return under a frozen clock. These cells re-run the workers and diff the
result against the file. The cells that spawn workers carry `faker_output_lock` and run in the
required `faker-output-lock` CI job; the seeded runner cells are static. Digests and exception
class names only: no value reaches a message. Schema and reviewed lists are in
`test_faker_output_lock_schema.py`, argument-bearing calls in
`test_faker_output_lock_arguments.py`.
"""

# ruff: noqa: F811  (fixtures are imported from the shared support module)
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.sentry.dependencies._faker_lock_lists import EXPECTED_CALENDAR, EXPECTED_RAISES
from tests.sentry.dependencies._faker_output_lock_support import (  # noqa: F401
    SMALL,
    _calendar,
    _check_anchors_and_floor,
    _expand,
    _load_lock,
    _minimal_lock,
    _names,
    _pairs,
    _raises,
    _small_diff,
    _stub,
    derived_surface,
    docs_high_seeds_and_clock_b,
    docs_low_seeds,
    full_capture,
    output_lock,
    small_baseline,
)


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_workers_for_the_low_hash_seeds_ran(docs_low_seeds: list[dict[str, Any]]) -> None:
    assert len(docs_low_seeds) == 4


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_workers_for_the_high_hash_seeds_and_clock_b_ran(
    docs_high_seeds_and_clock_b: list[dict[str, Any]],
) -> None:
    assert len(docs_high_seeds_and_clock_b) == 5


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_capture_keeps_anchors_and_floor(full_capture: dict[str, Any]) -> None:
    _check_anchors_and_floor(full_capture)


def _fake_runner(by_seed: dict[int, str], seen: list[tuple[str, int]] | None = None) -> Any:
    """A worker stand-in: one locale, one provider whose digest depends on the hash seed."""

    def run(clock: str, seed: int, locales: Any = None, stub: Any = None, py: Any = None) -> Any:
        if seen is not None:
            seen.append((clock, seed))
        digest = by_seed.get(seed, "9" * 64)
        cell = {"kwargs": [], "per_seed": digest, "sequential": digest}
        return {
            "en_US": {
                "resolved": "en_US",
                "reflected": {"passport_gender": cell},
                "adapter": {},
                "raw": {},
                "argumented": {},
            }
        }

    return run


def _baseline_with(digest: str) -> dict[str, Any]:
    base = _minimal_lock()["locales"]
    base["en_US"]["reflected"] = {
        "passport_gender": {
            "kwargs": [],
            "per_seed": digest,
            "sequential": digest,
            "calendar": False,
        }
    }
    return base


def test_capture_runs_every_one_of_eight_hash_seeds_for_every_locale() -> None:
    seen: list[tuple[str, int]] = []
    output_lock.capture(runner=_fake_runner({s: "1" * 64 for s in range(8)}, seen))
    assert sorted(s for c, s in seen if c == output_lock.CLOCK_A) == list(range(8))
    assert [s for c, s in seen if c == output_lock.CLOCK_B] == [0]
    assert tuple(range(8)) == output_lock.A_SEEDS


@pytest.mark.parametrize("odd_seed", range(8))
def test_a_stable_cell_that_differs_on_any_one_seed_is_caught(odd_seed: int) -> None:
    # The cell holds the locked digest on seven seeds and moves on one: interpreter-dependent
    # output that a two-seed capture would approve whenever the odd seed was not among the two.
    locked = "1" * 64
    by_seed = {s: locked for s in range(8)} | {odd_seed: "2" * 64}
    observed = output_lock.capture(runner=_fake_runner(by_seed))
    assert observed["en_US"]["reflected"]["passport_gender"]["per_seed"] == "unstable"
    diff = output_lock.diff_locales(_baseline_with(locked), observed)
    assert "en_US reflected passport_gender per_seed" in diff["newly unstable"]


def test_unstable_cell_that_agrees_on_most_seeds_is_still_unstable() -> None:
    chance = _fake_runner({s: "1" * 64 for s in range(8)} | {5: "2" * 64})
    seen = output_lock.capture(runner=chance)["en_US"]["reflected"]["passport_gender"]
    assert seen["per_seed"] == "unstable" and seen["calendar"] is False


def test_unstable_cell_that_agrees_on_every_seed_is_newly_reproducible() -> None:
    steady = _fake_runner({s: "1" * 64 for s in range(8)})
    observed = output_lock.capture(runner=steady)
    diff = output_lock.diff_locales(_baseline_with("unstable"), observed)
    assert "en_US reflected passport_gender per_seed" in diff["newly reproducible"]


# --- worker cells (marker faker_output_lock; run in the required CI job) -----------------------


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_lock_matches_installed_faker(full_capture: dict[str, Any]) -> None:
    lock = _load_lock()
    diff = output_lock.diff_locales(lock["locales"], full_capture)
    import faker

    assert not any(diff.values()), (
        f"installed Faker {faker.VERSION}, locked Faker {lock['faker_version']}\n{_names(diff)}\n"
        "Faker output moved. Before 1.0: regenerate with output_lock.py --write in the repin PR. "
        "After 1.0: see compatibility contract 3.3 for which kinds a 1.x release may carry."
    )


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_calendar_independent(full_capture: dict[str, Any]) -> None:
    assert _pairs(full_capture, _calendar) == _expand(full_capture, EXPECTED_CALENDAR)
    seeded = copy.deepcopy(_load_lock()["locales"])
    seeded["en_US"]["reflected"]["date"]["calendar"] = False
    diff = output_lock.diff_locales(_load_lock()["locales"], seeded)
    assert "en_US reflected date" in diff["no longer calendar-dependent"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_changed_pair_is_named(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "from faker.providers.person.en_US import Provider as P\n"
        "P.first_name = lambda self: 'SECRET-CHANGED'\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert "en_US reflected first_name per_seed" in diff["changed"]
    assert "en_US reflected first_name per_seed" in _names(diff)
    assert "SECRET-CHANGED" not in _names(diff)


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_removed_pair_is_named(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "import faker\n"
        "_orig = faker.Faker.__dir__\n"
        "faker.Faker.__dir__ = lambda self: [n for n in _orig(self) if n != 'job']\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert "en_US reflected job" in diff["removed"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_added_pair_is_named_additive(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "from faker.providers import BaseProvider\n"
        "from faker import Faker\n"
        "class Extra(BaseProvider):\n"
        "    def brand_new_probe(self):\n"
        "        return 'x'\n"
        "import faker.proxy as px\n"
        "_orig = px.Faker.__init__\n"
        "def _init(self, *a, **k):\n"
        "    _orig(self, *a, **k)\n"
        "    self.add_provider(Extra)\n"
        "px.Faker.__init__ = _init\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert "en_US reflected brand_new_probe" in diff["added"]
    assert not diff["changed"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_removed_kwarg_is_removed(small_baseline: dict[str, Any]) -> None:
    # The locked copy names a keyword argument that the installed provider does not have.
    lock = copy.deepcopy(small_baseline)
    lock["en_US"]["reflected"]["first_name"]["kwargs"] = ["gender_probe"]
    observed = output_lock.capture(locales=SMALL)
    diff = output_lock.diff_locales(lock, observed)
    assert "en_US reflected first_name keyword argument gender_probe" in diff["removed"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_clock_a_hash_seed_disagreement_is_unstable(
    small_baseline: dict[str, Any], tmp_path: Path
) -> None:
    stub = _stub(
        tmp_path,
        "import os\n"
        "from faker.providers.person.en_US import Provider as P\n"
        "P.first_name = lambda self: os.environ['PYTHONHASHSEED']\n",
    )
    observed = output_lock.capture(locales=SMALL, stub=stub)
    assert observed["en_US"]["reflected"]["first_name"]["per_seed"] == "unstable"
    diff = output_lock.diff_locales(small_baseline, observed)
    assert "en_US reflected first_name per_seed" in diff["newly unstable"]


def test_unstable_set_in_the_lock_is_not_compared_by_digest() -> None:
    old = _minimal_lock()["locales"]
    old["en_US"]["reflected"]["first_name"]["per_seed"] = "unstable"
    new = copy.deepcopy(old)
    assert not any(output_lock.diff_locales(old, new).values())


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_raise_is_recorded_by_class(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "from faker.providers.person.en_US import Provider as P\n"
        "def boom(self):\n"
        "    raise ValueError('SECRET-MESSAGE')\n"
        "P.first_name = boom\n",
    )
    observed = output_lock.capture(locales=SMALL, stub=stub)
    cell = observed["en_US"]["reflected"]["first_name"]
    assert cell["per_seed"] == "raises:ValueError" and cell["sequential"] == "raises:ValueError"
    assert observed["en_US"]["adapter"]["person_first_name"]["batch"] == (
        "raises:AdapterError/ValueError"
    )
    assert "SECRET-MESSAGE" not in json.dumps(observed)
    # A failing worker is a fixed refusal with no cause or context to leak through.
    with pytest.raises(output_lock.OutputLockError) as info:
        output_lock.run_worker(output_lock.CLOCK_A, 0, SMALL, stub=str(tmp_path / "missing.py"))
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert "missing" not in str(info.value)


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_raises_set_equals_expected(full_capture: dict[str, Any]) -> None:
    assert _pairs(full_capture, _raises) == _expand(full_capture, EXPECTED_RAISES)


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_adapter_surface_covered(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    from decoy_engine.providers_v2 import get_default_registry

    names = {c.provider for c in get_default_registry().faker_providers()}
    for loc in SMALL:
        assert set(small_baseline[loc]["adapter"]) == names
    lock = _load_lock()["locales"]
    for loc in SMALL:
        assert small_baseline[loc]["adapter"] == lock[loc]["adapter"]
    stub = _stub(
        tmp_path,
        "from decoy_engine.providers_v2 import _faker_adapter as a\n"
        "a._FAKER_DEFAULT_KWARGS.clear()\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert any(" adapter " in n for n in diff["changed"]), "adapter defaults are not covered"


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_lock_covers_engine_surface(small_baseline: dict[str, Any], tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "from decoy_engine.internal.faker_setup import register_faker_provider\n"
        "register_faker_provider('custom_probe_name', lambda fake: 'x')\n",
    )
    observed = output_lock.capture(locales=SMALL, stub=stub)
    import _engine_access as access

    for loc in SMALL:
        want = set(access.get_faker_providers(access.make_faker(loc), provider_snapshot={}))
        got = set(observed[loc]["reflected"])
        assert got == want
        assert "custom_probe_name" not in got
        assert not {"binary", "profile", "image"} & got
        assert got == set(small_baseline[loc]["reflected"])


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_seed_dependent_output_that_starts_at_a_later_seed_is_caught(
    small_baseline: dict[str, Any], tmp_path: Path
) -> None:
    # Equal to the locked output on seeds 0 and 1, different from seed 2 on.
    stub = _stub(
        tmp_path,
        "import os\n"
        "from faker.providers.person.en_US import Provider as P\n"
        "_orig = P.first_name\n"
        "P.first_name = lambda self: _orig(self) + ('x' if int(os.environ['PYTHONHASHSEED']) > 1 "
        "else '')\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert "en_US reflected first_name per_seed" in diff["newly unstable"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_raw_text_mask_address_shape_is_locked(
    small_baseline: dict[str, Any], tmp_path: Path
) -> None:
    # Faker starts returning "A, B" for "A\nB". The reflected provider joins lines itself, so its
    # digest holds; the raw call text_mask makes changes, and only the raw cell can show it.
    stub = _stub(
        tmp_path,
        "import faker.providers.address as a\n"
        "_orig = a.Provider.address\n"
        "a.Provider.address = lambda self: _orig(self).replace(chr(10), ', ')\n",
    )
    diff = _small_diff(small_baseline, stub)
    assert "en_US raw text_mask.address draws" in diff["changed"]
    assert "en_US reflected address per_seed" not in diff["changed"]
    assert "en_US raw text_mask.person_name draws" not in diff["changed"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_raw_shapes_are_in_the_capture(small_baseline: dict[str, Any]) -> None:
    want = {f"text_mask.{d}" for d in output_lock.TEXT_MASK_DETECTORS} | {"dob_anchored"}
    assert set(small_baseline["en_US"]["raw"]) == want
    assert set(small_baseline["pt_BR"]["raw"]) == {"dob_anchored"}
    assert small_baseline["en_US"]["raw"] == _load_lock()["locales"]["en_US"]["raw"]


_RANDOM_INT = (
    "import functools\n"
    "from faker.providers import BaseProvider as B\n"
    "_o = B.random_int\n"
    "@functools.wraps(_o)\n"
    "def _w(self, min=0, max=9999, step=1):\n"
    "    out = _o(self, min, max, step)\n"
    "    return out + 1 if (min, max) == (7, 7) else out\n"
    "B.random_int = _w\n"
)
_ADDRESS_DROPS_KEYS = (
    "import functools\n"
    "from faker.providers.address import Provider as A\n"
    "_o = A.address\n"
    "@functools.wraps(_o)\n"
    "def _w(self, *a, **k):\n"
    "    return _o(self)\n"
    "A.address = _w\n"
)
_ADAPTER_EXTRA = (
    "from decoy_engine.providers_v2 import _faker_adapter as fa\n"
    "_o = fa.FakerAdapter._faker_call\n"
    "def _w(self, provider, spec, fake=None):\n"
    "    out = _o(self, provider, spec, fake)\n"
    "    hit = spec.extra.get('min') == 7 == spec.extra.get('max')\n"
    "    return out + 1 if hit and isinstance(out, int) else out\n"
    "fa.FakerAdapter._faker_call = _w\n"
)
_DATE_BETWEEN_POSITIONAL = (
    "import functools\n"
    "from faker.providers.date_time import Provider as P\n"
    "_o = P.date_between\n"
    "@functools.wraps(_o)\n"
    "def _w(self, *a, **k):\n"
    "    out = _o(self, *a, **k)\n"
    "    return out.replace(year=out.year - 1) if a else out\n"
    "P.date_between = _w\n"
)


def _non_none_only(module: str, method: str, param: str, tail: str) -> str:
    """A stub that changes `method`'s output only when `param` is not None (an object or type
    argument a no-argument or `None` row cannot reach)."""
    return (
        "import functools, datetime\n"
        f"from faker.providers.{module} import Provider as P\n"
        f"_o = P.{method}\n"
        "@functools.wraps(_o)\n"
        "def _w(self, *a, **k):\n"
        "    out = _o(self, *a, **k)\n"
        f"    return {tail} if k.get({param!r}) is not None else out\n"
        f"P.{method} = _w\n"
    )


_STUBS = {
    "reflected_random_int": (_RANDOM_INT, "reflected.random_int.min_max_equal"),
    "address_override_drops_keys": (
        _ADDRESS_DROPS_KEYS,
        "address_override.address.unexpected_keyword",
    ),
    "adapter_extra": (_ADAPTER_EXTRA, "adapter.random_int_range.min_max_equal"),
    "formula_positional": (_DATE_BETWEEN_POSITIONAL, "formula.date_between.positional_"),
    "tzinfo_only": (
        _non_none_only("date_time", "date_time", "tzinfo", "out - datetime.timedelta(days=366)"),
        "reflected.date_time.tzinfo_set",
    ),
    "cast_to_only": (
        _non_none_only("misc", "uuid4", "cast_to", "str(out) + 'x'"),
        "reflected.uuid4.cast_to_set",
    ),
    "cls_only": (
        _non_none_only("misc", "json", "cls", "str(out) + ' '"),
        "reflected.json.cls_set",
    ),
    "value_types_only": (
        _non_none_only("misc", "xml", "value_types", "str(out) + ' '"),
        "reflected.xml.value_types_set",
    ),
}


def _reflected_oracle(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    """Every reflected cell that differs between two captures, found without the sentry's diff."""
    out = set()
    for loc in SMALL:
        old, new = before[loc]["reflected"], after[loc]["reflected"]
        out |= {f"{loc} reflected {n}" for n in set(old) | set(new) if old.get(n) != new.get(n)}
    return out


def _reflected_reported(diff: dict[str, list[str]]) -> set[str]:
    return {
        " ".join(n.split(" ")[:3]) for names in diff.values() for n in names if " reflected " in n
    }


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
@pytest.mark.parametrize("name", sorted(_STUBS))
def test_argument_only_changes_are_locked(
    name: str, small_baseline: dict[str, Any], tmp_path: Any
) -> None:
    body, named = _STUBS[name]
    after = output_lock.capture(locales=SMALL, stub=_stub(tmp_path, body))
    diff = output_lock.diff_locales(small_baseline, after)
    changed = [n for n in diff["changed"] if " argumented " in n]
    assert any(f" argumented {named}" in n for n in changed), changed
    # The complete reflected diff equals an independent cell-by-cell oracle: no subset filter, and
    # an indirect reflected caller of the changed method is reported too.
    assert _reflected_reported(diff) == _reflected_oracle(small_baseline, after)
    assert "SECRET" not in output_lock.render_diff(diff)


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
def test_decade_relative_case_crosses_clock_boundary() -> None:
    # The exact instants plan AT-L2 names: the same day and time, across month, year and decade.
    assert output_lock.CLOCK_A == "2026-10-16T12:00:00Z"
    assert output_lock.CLOCK_B == "2030-01-16T12:00:00Z"
    cells = output_lock.capture(locales=["en_US"])["en_US"]["argumented"]
    for helper in ("date_this_decade", "date_this_year", "date_this_month"):
        assert cells[f"formula.{helper}.after_today_true"]["calendar"] is True, helper
