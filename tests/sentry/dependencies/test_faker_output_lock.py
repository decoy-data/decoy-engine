"""Sentry: Faker output may not move unseen (FAKER-MIGRATE, AT-L1 to AT-L13).

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

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


@dataclass(frozen=True)
class Everywhere:
    """Every locale of the lock that has the provider, minus `except_`."""

    except_: tuple[str, ...] = field(default=())


Entry = tuple["Everywhere | tuple[str, ...]", str]

UNSTABLE_REASON = "differs between processes at one frozen clock; cause not traced (F-5)"
RAISES_REASON = "provider raises with no arguments in this locale"
CALENDAR_REASON = "reads the date or time (clock-reading provider)"

EXPECTED_UNSTABLE: dict[tuple[str, str], tuple[Everywhere | tuple[str, ...], str]] = {
    ("adapter", "address_city"): (("it_IT",), UNSTABLE_REASON),
    ("reflected", "cif"): (("es", "es_CA", "es_ES"), UNSTABLE_REASON),
    ("reflected", "city"): (("it_IT",), UNSTABLE_REASON),
    ("reflected", "curp"): (("es_MX",), UNSTABLE_REASON),
    ("reflected", "diplomatic_license_plate"): (("uk_UA",), UNSTABLE_REASON),
    ("reflected", "elector_code"): (("es_MX",), UNSTABLE_REASON),
    ("reflected", "license_plate"): (("uk_UA",), UNSTABLE_REASON),
    ("reflected", "nie"): (("es", "es_CA", "es_ES"), UNSTABLE_REASON),
    ("reflected", "nif"): (("es", "es_CA", "es_ES"), UNSTABLE_REASON),
    ("reflected", "nuss"): (("es", "es_CA", "es_ES"), UNSTABLE_REASON),
    ("reflected", "org_and_vat_id"): (("sv_SE",), UNSTABLE_REASON),
    ("reflected", "org_id"): (("sv_SE",), UNSTABLE_REASON),
    ("reflected", "passport_full"): (
        Everywhere(),
        "differs between processes at one frozen clock (hash seed); cause not traced (F-5)",
    ),
    ("reflected", "passport_gender"): (
        Everywhere(),
        "differs between processes at one frozen clock (hash seed); cause not traced (F-5)",
    ),
    ("reflected", "plate_letter_prefix"): (("uk_UA",), UNSTABLE_REASON),
    ("reflected", "plate_region_code"): (("uk_UA",), UNSTABLE_REASON),
    ("reflected", "rfc"): (("es_MX",), UNSTABLE_REASON),
    ("reflected", "ssn"): (("th", "th_TH", "uk_UA"), UNSTABLE_REASON),
    ("reflected", "tin"): (("el_GR",), UNSTABLE_REASON),
    ("reflected", "vat_id"): (("el_GR", "sv_SE", "th", "th_TH"), UNSTABLE_REASON),
}

EXPECTED_RAISES: dict[tuple[str, str], tuple[Everywhere | tuple[str, ...], str]] = {
    ("adapter", "address_state"): (
        (
            "ar_DZ",
            "az_AZ",
            "bn_BD",
            "de_CH",
            "el_GR",
            "en_BD",
            "en_CA",
            "en_GB",
            "en_IE",
            "en_NZ",
            "en_PH",
            "es_AR",
            "es_CL",
            "es_CO",
            "fil_PH",
            "fr_CA",
            "fr_CH",
            "fr_DZ",
            "fr_FR",
            "he_IL",
            "hu_HU",
            "ja_JP",
            "ka_GE",
            "ko_KR",
            "ne_NP",
            "nl_BE",
            "nl_NL",
            "no_NO",
            "pl_PL",
            "pt_PT",
            "ru_RU",
            "th",
            "th_TH",
            "tl_PH",
            "uk_UA",
            "zh_CN",
            "zh_TW",
            "zu_ZA",
        ),
        "no state list in this locale (adapter wraps AttributeError)",
    ),
    ("adapter", "person_phone"): (
        ("en_PH", "fil_PH", "tl_PH"),
        "no phone format in this locale (adapter wraps AttributeError)",
    ),
    ("reflected", "bank"): (
        (
            "bn_BD",
            "cs_CZ",
            "da_DK",
            "de",
            "de_AT",
            "de_DE",
            "en_IE",
            "en_PH",
            "es",
            "es_ES",
            "fi_FI",
            "fil_PH",
            "fr_FR",
            "it_IT",
            "nl_NL",
            "no_NO",
            "pl_PL",
            "pt_PT",
            "ro_RO",
            "sk_SK",
            "th",
            "th_TH",
            "tl_PH",
            "tr_TR",
        ),
        "no bank list in this locale (AttributeError)",
    ),
    ("reflected", "current_country"): (("en_MS",), "locale has no current country"),
    ("reflected", "del_arguments"): (
        Everywhere(),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "get_formatter"): (
        Everywhere(),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "is_leap_year"): (("it_IT",), "helper that needs an argument"),
    ("reflected", "name_female"): (("es_AR",), "locale has no female name list"),
    ("reflected", "name_male"): (("es_AR",), "locale has no male name list"),
    ("reflected", "pesel_compute_check_digit"): (("pl_PL",), "helper that needs an argument"),
    ("reflected", "pricetag"): (("bn_BD",), "locale has no currency symbol entry"),
    ("reflected", "provider"): (
        Everywhere(),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "pwz_doctor_compute_check_digit"): (("pl_PL",), "helper that needs an argument"),
    ("reflected", "xml"): (("fr_FR", "pl_PL"), "xml() rejects the default size in this locale"),
}

EXPECTED_CALENDAR: dict[tuple[str, str], tuple[Everywhere | tuple[str, ...], str]] = {
    ("reflected", "am_pm"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "ascii_company_email"): (("bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_email"): (("az_AZ", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_free_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "ascii_safe_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "birth_number"): (
        ("cs_CZ", "sk_SK"),
        "birth number reads today for the century digit",
    ),
    ("reflected", "company_email"): (("bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "credit_card_expire"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "credit_card_full"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_between"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_between_dates"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_object"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_this_century"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_this_decade"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_this_month"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_this_year"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_ad"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_between"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_between_dates"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_this_century"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_this_decade"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_this_month"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "date_time_this_year"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "day_of_month"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "day_of_week"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "day_of_week_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "email"): (("bg_BG",), "email local part reads the clock in this locale"),
    ("reflected", "free_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "future_date"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "future_datetime"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "iso8601"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "minguo_year"): (("zh_TW",), CALENDAR_REASON),
    ("reflected", "month"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "month_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "month_name"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "month_name_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "passport_dates"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "passport_dob"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "past_date"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "past_datetime"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "pesel"): (("pl_PL",), "check date reads today"),
    ("reflected", "rvnr"): (("de", "de_DE"), "insurance number reads today"),
    ("reflected", "safe_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "ssn"): (
        ("de_AT", "el_GR", "et_EE", "fi_FI", "lv_LV", "nl_BE", "no_NO", "pl_PL", "sv_SE", "zh_CN"),
        "national id embeds the birth date or age from today",
    ),
    ("reflected", "time"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "traditional_month_name"): (("ja_JP",), CALENDAR_REASON),
    ("reflected", "unix_time"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "user_name"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "uuid1"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "uuid7"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "xml"): (Everywhere(), CALENDAR_REASON),
    ("reflected", "year"): (Everywhere(), CALENDAR_REASON),
}

# Pairs that must be digests on both surfaces where they exist (the 2026-07-23 confusion was
# about names and addresses, so they are anchored).
ANCHORS: tuple[tuple[str, str, str], ...] = (
    ("en_US", "reflected", "first_name"),
    ("en_US", "reflected", "email"),
    ("en_US", "reflected", "address"),
    ("en_US", "reflected", "currency_code"),
    ("es_ES", "reflected", "bban"),
    ("en_GB", "reflected", "vat_id"),
    ("en_US", "adapter", "person_first_name"),
    ("en_US", "adapter", "person_email"),
)
EN_US_DIGEST_FLOOR = 253  # en_US reflected pairs whose two fields are digests, as captured


# --- helpers -----------------------------------------------------------------------------------


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def _fields(surface: str) -> tuple[str, ...]:
    return ("per_seed", "sequential") if surface == "reflected" else ("batch",)


def _pairs(locales: dict[str, Any], pred: Any) -> set[tuple[str, str, str]]:
    return {
        (loc, surface, name)
        for loc, entry in locales.items()
        for surface in ("reflected", "adapter")
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
            have = [loc for loc, e in locales.items() if name in e[surface]]
            out |= {(loc, surface, name) for loc in have if loc not in where.except_}
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
        "lock_version": 1,
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
    return output_lock.capture((0, 1, 2), locales=SMALL)


@pytest.fixture(scope="module")
def full_capture() -> dict[str, Any]:
    return output_lock.capture((0, 1), baseline=_load_lock()["locales"])


def _small_diff(baseline: dict[str, Any], stub: str) -> dict[str, list[str]]:
    observed = output_lock.capture((0, 1), locales=SMALL, stub=stub)
    return output_lock.diff_locales(baseline, observed)


# --- static cells (no worker; ordinary sentry gate) --------------------------------------------


def test_lock_is_closed_and_strict() -> None:
    raw = LOCK_FILE.read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert output_lock.check_lock_shape(doc) == []
    assert raw == output_lock.canonical_text(doc), "output_lock.json is not canonical JSON"
    assert output_lock.check_lock_shape(_minimal_lock()) == []


@pytest.mark.parametrize("path", _leaf_paths(_minimal_lock()), ids=lambda p: ".".join(map(str, p)))
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


def _fake_runner(by_seed: dict[int, str]) -> Any:
    """A worker stand-in: one locale, one provider whose digest depends on the hash seed."""

    def run(clock: str, seed: int, locales: Any = None, stub: Any = None, py: Any = None) -> Any:
        digest = by_seed.get(seed, "9" * 64)
        cell = {"kwargs": [], "per_seed": digest, "sequential": digest}
        return {
            "en_US": {
                "resolved": "en_US",
                "reflected": {"passport_gender": cell},
                "adapter": {},
            }
        }

    return run


def _unstable_baseline() -> dict[str, Any]:
    base = _minimal_lock()["locales"]
    base["en_US"]["reflected"] = {
        "passport_gender": {
            "kwargs": [],
            "per_seed": "unstable",
            "sequential": "unstable",
            "calendar": False,
        }
    }
    return base


def test_unstable_cell_that_agrees_on_two_seeds_is_rechecked() -> None:
    # Seeds 0 and 1 agree by chance; one of the recheck seeds disagrees, so it is still unstable.
    chance = _fake_runner({0: "1" * 64, 1: "1" * 64, 2: "1" * 64, 5: "2" * 64})
    seen = output_lock.capture((0, 1), baseline=_unstable_baseline(), runner=chance)["en_US"][
        "reflected"
    ]["passport_gender"]
    assert seen["per_seed"] == "unstable" and seen["calendar"] is False


def test_unstable_cell_that_agrees_on_every_seed_is_newly_reproducible() -> None:
    steady = _fake_runner({s: "1" * 64 for s in range(8)})
    observed = output_lock.capture((0, 1), baseline=_unstable_baseline(), runner=steady)
    diff = output_lock.diff_locales(_unstable_baseline(), observed)
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
    observed = output_lock.capture((0, 1), locales=SMALL)
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
    observed = output_lock.capture((0, 1), locales=SMALL, stub=stub)
    assert observed["en_US"]["reflected"]["first_name"]["per_seed"] == "unstable"
    diff = output_lock.diff_locales(small_baseline, observed)
    assert "en_US reflected first_name per_seed" in diff["newly unstable"]


@pytest.mark.faker_output_lock
@pytest.mark.timeout(180)
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
    observed = output_lock.capture((0, 1), locales=SMALL, stub=stub)
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
    observed = output_lock.capture((0, 1), locales=SMALL, stub=stub)
    import _engine_access as access

    for loc in SMALL:
        want = set(access.get_faker_providers(access.make_faker(loc), provider_snapshot={}))
        got = set(observed[loc]["reflected"])
        assert got == want
        assert "custom_probe_name" not in got
        assert not {"binary", "profile", "image"} & got
        assert got == set(small_baseline[loc]["reflected"])
