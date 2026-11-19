"""Sentry: Faker output may not move unseen (FAKER-MIGRATE, AT-L1 to AT-L18).

`scripts/faker-determinism/output_lock.json` records, for every Faker locale, digests of what the
engine's two Faker surfaces return under a frozen clock. These cells re-run the workers and diff
the result against the file. The static cells (shape, reviewed lists, anchors) run in the ordinary
sentry gate; the cells that spawn workers carry `faker_output_lock` and run in the required
`faker-output-lock` CI job. Digests and exception class names only: no value reaches a message.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.sentry.dependencies._faker_lock_lists import (
    ANCHORS,
    EN_US_DIGEST_FLOOR,
    EXPECTED_CALENDAR,
    EXPECTED_RAISES,
    EXPECTED_UNSTABLE,
    Entry,
    Everywhere,
)

ROOT = Path(__file__).resolve().parents[3]
TOOL_DIR = ROOT / "scripts" / "faker-determinism"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

_spec = importlib.util.spec_from_file_location("output_lock", TOOL_DIR / "output_lock.py")
assert _spec is not None and _spec.loader is not None
output_lock = importlib.util.module_from_spec(_spec)
sys.modules["output_lock"] = output_lock
_spec.loader.exec_module(output_lock)

LOCK_FILE = output_lock.LOCK_PATH
SMALL = ["en_US", "pt_BR"]
WORKER_CELL = [pytest.mark.faker_output_lock, pytest.mark.timeout(180)]


# --- helpers -----------------------------------------------------------------------------------


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def _fields(surface: str) -> tuple[str, ...]:
    return output_lock.SURFACE_FIELDS[surface]


def _pairs(locales: dict[str, Any], pred: Any) -> set[tuple[str, str, str]]:
    return {
        (loc, surface, name)
        for loc, entry in locales.items()
        for surface in output_lock.SURFACE_FIELDS
        for name, cell in entry[surface].items()
        if pred(cell, surface)
    }


def _expand(
    locales: dict[str, Any], table: dict[tuple[str, str], Entry]
) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for (surface, name), (where, reason) in table.items():
        assert reason, f"{surface} {name} needs a reason"
        if isinstance(where, Everywhere):
            have = {
                (loc, surface, name)
                for loc, e in locales.items()
                if name in e[surface] and loc not in where.except_
            }
            # A locale that joins the lock widens "everywhere"; the count makes that an edit.
            assert len(have) == where.count, f"{surface} {name} now covers {len(have)} locales"
            out |= have
        else:
            out |= {(loc, surface, name) for loc in where}
    return out


def _unstable(cell: dict[str, Any], surface: str) -> bool:
    return any(cell[f] == "unstable" for f in _fields(surface))


def _raises(cell: dict[str, Any], surface: str) -> bool:
    return any(cell[f].startswith("raises:") for f in _fields(surface))


def _calendar(cell: dict[str, Any], surface: str) -> bool:
    return cell["calendar"] is True


def _names(diff: dict[str, list[str]]) -> str:
    return output_lock.render_diff(diff)


def _stub(tmp_path: Path, body: str) -> str:
    path = tmp_path / "stub.py"
    path.write_text(body, encoding="utf-8")
    return str(path)


def _minimal_lock() -> dict[str, Any]:
    digest = "a" * 64
    return {
        "lock_version": 2,
        "faker_version": "40.23.0",
        "codec_version": 1,
        "samples": 8,
        "clocks": ["2026-10-16T12:00:00Z", "2027-11-20T12:00:00Z"],
        "locales": {
            "en_US": {
                "resolved": "en_US",
                "reflected": {
                    "first_name": {
                        "kwargs": ["a"],
                        "per_seed": digest,
                        "sequential": "raises:ValueError",
                        "calendar": False,
                    }
                },
                "adapter": {
                    "person_email": {"batch": "raises:AdapterError/KeyError", "calendar": True}
                },
                "raw": {"dob_anchored": {"draws": digest, "calendar": False}},
                "argumented": {
                    "date_between.date_objects": {
                        "arguments": {
                            "args": [],
                            "kwargs": {"start_date": {"date": "2000-01-01"}, "end_date": "today"},
                        },
                        "draws": digest,
                        "calendar": False,
                    }
                },
            }
        },
    }


def _leaf_paths(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Paths of every primitive field and every list element of a lock document."""
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in _leaf_paths(v, (*path, k))]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _leaf_paths(v, (*path, i))]
    return [path]


def _set_at(doc: Any, path: tuple[Any, ...], value: Any) -> None:
    for key in path[:-1]:
        doc = doc[key]
    doc[path[-1]] = value


_WRONG_TYPES = (True, 7, 8.0, "7", "x", None, [], {})


@pytest.fixture(scope="module")
def small_baseline() -> dict[str, Any]:
    return output_lock.capture(locales=SMALL)


# The full capture is nine workers (eight clock-A hash seeds, one clock B). One test cell carries
# the setup of the fixture it first asks for, and a cell has 180 s, so the nine run as two batches,
# each built by its own early test below; `full_capture` then only classifies their documents.


@pytest.fixture(scope="module")
def docs_low_seeds() -> list[dict[str, Any]]:
    return output_lock.gather([(output_lock.CLOCK_A, s) for s in output_lock.A_SEEDS[:4]])


@pytest.fixture(scope="module")
def docs_high_seeds_and_clock_b() -> list[dict[str, Any]]:
    jobs = [(output_lock.CLOCK_A, s) for s in output_lock.A_SEEDS[4:]]
    return output_lock.gather([*jobs, (output_lock.CLOCK_B, 0)])


@pytest.fixture(scope="module")
def full_capture(
    docs_low_seeds: list[dict[str, Any]], docs_high_seeds_and_clock_b: list[dict[str, Any]]
) -> dict[str, Any]:
    docs = [*docs_low_seeds, *docs_high_seeds_and_clock_b]
    return output_lock.classify(docs[:-1], docs[-1])


def _small_diff(baseline: dict[str, Any], stub: str) -> dict[str, list[str]]:
    observed = output_lock.capture(locales=SMALL, stub=stub)
    return output_lock.diff_locales(baseline, observed)


# --- static cells (no worker; ordinary sentry gate) --------------------------------------------


def test_lock_is_closed_and_strict() -> None:
    raw = LOCK_FILE.read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert output_lock.check_lock_shape(doc) == []
    assert raw == output_lock.canonical_text(doc), "output_lock.json is not canonical JSON"
    assert output_lock.check_lock_shape(_minimal_lock()) == []


# Argument descriptors accept several scalar types by design; AT-L18 tests them on their own.
_STORED_FIELDS = [p for p in _leaf_paths(_minimal_lock()) if "arguments" not in p]


@pytest.mark.parametrize("path", _STORED_FIELDS, ids=lambda p: ".".join(map(str, p)))
def test_every_stored_field_refuses_wrong_types(path: tuple[Any, ...]) -> None:
    good = _minimal_lock()
    for wrong in _WRONG_TYPES:
        bad = copy.deepcopy(good)
        node: Any = bad
        for key in path:
            node = node[key]
        if type(node) is type(wrong):
            continue  # the same type is not a wrong type; patterns are tested separately
        _set_at(bad, path, wrong)
        assert output_lock.check_lock_shape(bad), f"{path} accepted {type(wrong).__name__}"


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(extra=1),
        lambda d: d["locales"]["en_US"].update(extra=1),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(extra=1),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(per_seed="a" * 63),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(per_seed="a" * 64 + "\n"),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(sequential="raises:x y"),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(calendar=1),
        lambda d: d["locales"]["en_US"]["adapter"]["person_email"].update(calendar="yes"),
        lambda d: d.update(lock_version=True),
        lambda d: d.update(samples=8.0),
        lambda d: d.update(samples="8"),
        lambda d: d.update(clocks=["a", 1]),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(kwargs=[True]),
        lambda d: d["locales"]["en_US"]["reflected"]["first_name"].update(kwargs=[1]),
        lambda d: d["locales"]["en_US"].update(resolved=1),
    ],
)
def test_malformed_lock_copies_are_refused(edit: Any) -> None:
    doc = _minimal_lock()
    edit(doc)
    assert output_lock.check_lock_shape(doc)


def test_non_canonical_bytes_are_refused() -> None:
    doc = _minimal_lock()
    assert output_lock.canonical_text(doc) != json.dumps(doc, indent=2) + "\n"
    assert output_lock.canonical_text(doc).endswith("}\n")


def test_expected_unstable_equals_the_lock() -> None:
    locales = _load_lock()["locales"]
    assert _pairs(locales, _unstable) == _expand(locales, EXPECTED_UNSTABLE)


def test_a_new_locale_joining_an_everywhere_entry_is_caught() -> None:
    locales = copy.deepcopy(_load_lock()["locales"])
    locales["zz_ZZ"] = copy.deepcopy(locales["en_US"])
    with pytest.raises(AssertionError, match="now covers"):
        _expand(locales, EXPECTED_UNSTABLE)


def test_a_stable_pair_marked_unstable_is_caught() -> None:
    # Holds even if the real expected set were empty: the seeded copy differs from the list.
    locales = copy.deepcopy(_load_lock()["locales"])
    locales["en_US"]["reflected"]["first_name"]["per_seed"] = "unstable"
    assert _pairs(locales, _unstable) != _expand(locales, EXPECTED_UNSTABLE)


def test_expected_raises_equals_the_lock() -> None:
    locales = _load_lock()["locales"]
    assert _pairs(locales, _raises) == _expand(locales, EXPECTED_RAISES)


def test_expected_calendar_equals_the_lock() -> None:
    locales = _load_lock()["locales"]
    assert _pairs(locales, _calendar) == _expand(locales, EXPECTED_CALENDAR)


def test_anchors_and_floor() -> None:
    _check_anchors_and_floor(_load_lock()["locales"])


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


def _check_anchors_and_floor(locales: dict[str, Any]) -> None:
    for loc, surface, name in ANCHORS:
        cell = locales[loc][surface][name]
        assert all(len(cell[f]) == 64 for f in _fields(surface)), f"{loc} {surface} {name}"
    digests = [
        c
        for c in locales["en_US"]["reflected"].values()
        if all(len(c[f]) == 64 for f in _fields("reflected"))
    ]
    assert len(digests) >= EN_US_DIGEST_FLOOR


def test_diff_has_one_branch_per_kind() -> None:
    old = _minimal_lock()["locales"]
    new = copy.deepcopy(old)
    cell = new["en_US"]["reflected"]["first_name"]
    cell["per_seed"] = "b" * 64
    cell["sequential"] = "unstable"
    cell["calendar"] = True
    cell["kwargs"] = ["b"]
    new["en_US"]["reflected"]["extra"] = copy.deepcopy(cell)
    del new["en_US"]["adapter"]["person_email"]
    new["de_DE"] = copy.deepcopy(new["en_US"])
    diff = output_lock.diff_locales(old, new)
    assert diff["changed"] and diff["removed"] and diff["added"]
    assert diff["newly calendar-dependent"] and diff["newly unstable"]
    old["en_US"]["reflected"]["first_name"]["sequential"] = "unstable"
    assert output_lock.diff_locales(old, copy.deepcopy(old)) == {k: [] for k in output_lock.KINDS}
    old2 = copy.deepcopy(old)
    old2["en_US"]["reflected"]["first_name"]["sequential"] = "c" * 64
    assert output_lock.diff_locales(old, old2)["newly reproducible"]
    flipped = copy.deepcopy(old)
    flipped["en_US"]["adapter"]["person_email"]["calendar"] = False
    assert output_lock.diff_locales(old, flipped)["no longer calendar-dependent"]


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


def test_changelog_line_for_changed_and_no_longer_calendar() -> None:
    old = _minimal_lock()["locales"]
    new = copy.deepcopy(old)
    new["en_US"]["adapter"]["person_email"].update(batch="d" * 64, calendar=False)
    lines = output_lock.changelog_changed_lines(output_lock.diff_locales(old, new))
    assert lines == [
        "Changed: en_US adapter person_email: digest changed and no longer depends on the calendar"
    ]


def test_codec_scalar_forms_and_error_hygiene() -> None:
    import datetime as dt
    import decimal

    codec = sys.modules["digest_codec"]
    enc = codec._pool_digest
    aware = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    naive = dt.datetime(2026, 1, 1, 12, 0)
    assert enc([aware]) != enc([naive])
    assert enc([aware]) == enc([naive.replace(tzinfo=dt.timezone(dt.timedelta(0)))])
    assert enc([dt.date(2026, 1, 1)]) != enc([naive])
    assert enc([decimal.Decimal("1.50")]) != enc([decimal.Decimal("1.5")])
    with pytest.raises(codec.PoolDigestTypeError) as info:
        enc(["ok", ["SECRET-VALUE"]])
    assert "SECRET-VALUE" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None


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


# --- argument-bearing calls (AT-L16 to AT-L18) -------------------------------------------------

_ARG_STUBS = {
    # (a) the counterexample: output moves only when `start_date` is supplied.
    "date_between_start_date": (
        "import functools\n"
        "from faker.providers.date_time import Provider as P\n"
        "_orig = P.date_between\n"
        "@functools.wraps(_orig)\n"
        "def _w(self, *a, **k):\n"
        "    out = _orig(self, *a, **k)\n"
        "    return out.replace(year=out.year - 1) if 'start_date' in k else out\n"
        "P.date_between = _w\n"
    ),
    # (b) output moves only when a bound is a date object.
    "date_between_date_object": (
        "import datetime, functools\n"
        "from faker.providers.date_time import Provider as P\n"
        "_orig = P.date_between\n"
        "@functools.wraps(_orig)\n"
        "def _w(self, *a, **k):\n"
        "    out = _orig(self, *a, **k)\n"
        "    objs = [v for v in (*a, *k.values()) if isinstance(v, datetime.date)]\n"
        "    return out.replace(year=out.year - 1) if objs else out\n"
        "P.date_between = _w\n"
    ),
    # (c) anchored date of birth moves only for a non-default age bound.
    "anchored_dob_age_bounds": (
        "import datetime, functools\n"
        "import _engine_access as a\n"
        "_orig = a.anchored_date_of_birth\n"
        "@functools.wraps(_orig)\n"
        "def _w(fake, tzinfo=None, minimum_age=0, maximum_age=115):\n"
        "    out = _orig(fake, tzinfo, minimum_age, maximum_age)\n"
        "    if (minimum_age, maximum_age) == (0, 115):\n"
        "        return out\n"
        "    return out + datetime.timedelta(days=1)\n"
        "a.anchored_date_of_birth = _w\n"
    ),
}
_ARG_EXPECTED_CHANGED = {
    "date_between_start_date": {
        "date_between.relative",
        "date_between.absolute_strings",
        "date_between.date_objects",
        "date_between.equal_boundary",
    },
    "date_between_date_object": {"date_between.date_objects", "date_between.equal_boundary"},
    "anchored_dob_age_bounds": {
        "date_of_birth.adult_range",
        "date_of_birth.equal_age_boundary",
        "date_of_birth.adult_positional",
    },
}


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
@pytest.mark.parametrize("name", sorted(_ARG_STUBS))
def test_argument_only_changes_are_locked(
    name: str, small_baseline: dict[str, Any], tmp_path: Path
) -> None:
    diff = _small_diff(small_baseline, _stub(tmp_path, _ARG_STUBS[name]))
    moved = {
        n.split(" argumented ", 1)[1].split(" ", 1)[0]
        for n in diff["changed"]
        if " argumented " in n
    }
    assert {m for m in moved} == _ARG_EXPECTED_CHANGED[name]
    # No call without the argument moved: the reflected cells stay green (the lock's old blind spot).
    assert not [n for n in diff["changed"] if " reflected " in n]
    assert "SECRET" not in _names(diff)


def _formula_forwarding_methods(source: str) -> set[str]:
    """Faker methods the formula scope exposes with caller-supplied arguments, from its AST.

    A dict value `self.faker.<m>` binds the method itself; a lambda that takes `*args` or `**kwargs`
    forwards them, to `self.faker.<m>` or to the anchored date-of-birth helper (keyed by its name)."""
    import ast

    tree = ast.parse(source)
    scope = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_formula_scope"
    )
    table = next(
        n.value
        for n in ast.walk(scope)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)
    )
    out: set[str] = set()
    for key, value in zip(table.keys, table.values, strict=True):
        if isinstance(value, ast.Attribute) and ast.unparse(value.value) == "self.faker":
            out.add(value.attr)
        elif isinstance(value, ast.Lambda) and (value.args.vararg or value.args.kwarg):
            calls = [ast.unparse(c.func) for c in ast.walk(value.body) if isinstance(c, ast.Call)]
            if "anchored_date_of_birth" in calls and isinstance(key, ast.Constant):
                out.add(str(key.value))
            out.update(c.removeprefix("self.faker.") for c in calls if c.startswith("self.faker."))
    return out


_FORMULA_SOURCE = ROOT / "src" / "decoy_engine" / "generators" / "_formula.py"


def test_every_argument_forwarding_formula_helper_has_grid_cases() -> None:
    source = _FORMULA_SOURCE.read_text(encoding="utf-8")
    assert _formula_forwarding_methods(source) == {m for m, _ in output_lock.grid_cells()}
    # A new forwarding helper without a grid entry is caught (the seeded scratch copy).
    seeded = source.replace(
        '"date_between": self.faker.date_between,',
        '"date_between": self.faker.date_between,\n'
        '            "date_time_between": self.faker.date_time_between,',
        1,
    )
    assert seeded != source
    assert _formula_forwarding_methods(seeded) != {m for m, _ in output_lock.grid_cells()}


# Faker-forwarding call families the lock covers: a call that spreads `**kwargs` into a callee
# named like a provider. A file outside this table is a new family with no lock surface.
_FORWARDING_FAMILIES = {
    "generation/_column_streams.py": "reflected wrapper",
    "generation/_faker_pool.py": "reflected wrapper",
    "generation/_unique.py": "reflected wrapper",
    "generation/synthesize.py": "reflected wrapper",
    "generators/columns.py": "reflected wrapper",
    "internal/faker_setup.py": "reflected wrapper and its address override",
    "execution/native/_draw_site_providers_gen_pool.py": "reflected wrapper (native mirror)",
    "execution/native/protocol/providers_gen.py": "reflected wrapper (native mirror)",
    "providers_v2/_faker_adapter.py": "adapter",
}


def _forwarding_files(root: Path) -> set[str]:
    import ast
    import re

    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and any(k.arg is None for k in node.keywords)
                and re.search(r"(?i)faker|fake|provider|method", ast.unparse(node.func))
            ):
                found.add(path.relative_to(root).as_posix())
    return found


def test_a_new_faker_forwarding_family_is_reported(tmp_path: Path) -> None:
    found = _forwarding_files(ROOT / "src" / "decoy_engine")
    assert found <= set(_FORWARDING_FAMILIES), sorted(found - set(_FORWARDING_FAMILIES))
    (tmp_path / "new.py").write_text("def f(provider, kw):\n    return provider(**kw)\n")
    assert _forwarding_files(tmp_path) == {"new.py"}


_EXPECTED_GRID = {
    "date_between.relative": ([], {"start_date": "-30y", "end_date": "today"}),
    "date_between.absolute_strings": ([], {"start_date": "2000-01-01", "end_date": "2000-12-31"}),
    "date_between.date_objects": (
        [],
        {"start_date": {"date": "2000-01-01"}, "end_date": {"date": "2000-12-31"}},
    ),
    "date_between.equal_boundary": (
        [],
        {"start_date": {"date": "2000-01-01"}, "end_date": {"date": "2000-01-01"}},
    ),
    "future_date.relative": ([], {"end_date": "+30d"}),
    "future_date.absolute_string": ([], {"end_date": "2030-01-01"}),
    "future_date.date_object": ([], {"end_date": {"date": "2030-01-01"}}),
    "past_date.relative": ([], {"start_date": "-30d"}),
    "past_date.absolute_string": ([], {"start_date": "2000-01-01"}),
    "past_date.date_object": ([], {"start_date": {"date": "2000-01-01"}}),
    "date_of_birth.full_bounds": ([], {"minimum_age": 0, "maximum_age": 115}),
    "date_of_birth.adult_range": ([], {"minimum_age": 18, "maximum_age": 65}),
    "date_of_birth.equal_age_boundary": ([], {"minimum_age": 18, "maximum_age": 18}),
    "date_of_birth.adult_positional": ([None, 18, 65], {}),
}
for _m in ("date_this_decade", "date_this_year", "date_this_month"):
    for _case, _kw in (
        ("before_only", (True, False)),
        ("after_only", (False, True)),
        ("both_sides", (True, True)),
        ("neither_side", (False, False)),
    ):
        _EXPECTED_GRID[f"{_m}.{_case}"] = ([], {"before_today": _kw[0], "after_today": _kw[1]})


def test_argument_grid_is_fixed_and_strict() -> None:
    cells = {f"{m}.{c}": (a, k) for (m, c), (a, k) in output_lock.grid_cells().items()}
    assert cells == _EXPECTED_GRID
    methods = {m for m, _ in output_lock.grid_cells()}
    assert all(any(m == x for x, _ in output_lock.grid_cells()) for m in methods)
    # Decoding then re-encoding is byte-identical for every descriptor.
    for args, kwargs in cells.values():
        for d in (*args, *kwargs.values()):
            again = output_lock.encode_descriptor(output_lock.decode_descriptor(d))
            assert json.dumps(again, sort_keys=True) == json.dumps(d, sort_keys=True)
    good = _minimal_lock()
    assert output_lock.check_lock_shape(good) == []
    path = ("locales", "en_US", "argumented", "date_between.date_objects", "arguments")
    for bad in (
        {"args": [], "kwargs": {"start_date": {"date": 1}}},
        {"args": [], "kwargs": {"start_date": {"date": "2000-13-45"}}},
        {"args": [], "kwargs": {"start_date": {"date": "2000-01-01\n"}}},
        {"args": [], "kwargs": {"start_date": {"date": "2000-01-01", "x": 1}}},
        {"args": [], "kwargs": {"start_date": {"when": "2000-01-01"}}},
        {"args": [], "kwargs": {"start_date": 1.5}},
        {"args": [], "kwargs": {"start_date": [1]}},
        {"args": {}, "kwargs": {}},
        {"args": [], "kwargs": []},
        {"args": []},
        {"args": [], "kwargs": {}, "extra": 1},
    ):
        broken = copy.deepcopy(good)
        _set_at(broken, path, bad)
        assert output_lock.check_lock_shape(broken), bad
