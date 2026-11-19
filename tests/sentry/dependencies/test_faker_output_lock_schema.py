"""Sentry: the Faker output lock is closed, strict and canonical (FAKER-MIGRATE, AT-L2, AT-L7,
AT-L8, AT-L10).

Static cells only: the stored schema at every level, the reviewed unstable, raises and calendar
lists against the lock, the anchors and floor, the names-only diff and the codec. No worker runs
here, so the whole file is in the ordinary sentry gate.
"""

from __future__ import annotations

import copy
import json
import sys
from typing import Any

import pytest

from tests.sentry.dependencies._faker_lock_lists import (
    EXPECTED_CALENDAR,
    EXPECTED_RAISES,
    EXPECTED_UNSTABLE,
)
from tests.sentry.dependencies._faker_output_lock_support import (
    _WRONG_TYPES,
    LOCK_FILE,
    _calendar,
    _check_anchors_and_floor,
    _expand,
    _leaf_paths,
    _load_lock,
    _minimal_lock,
    _pairs,
    _raises,
    _set_at,
    _unstable,
    output_lock,
)


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
        lambda d: d.update(argument_samples=3),
        lambda d: d.update(argument_samples=2.0),
        lambda d: d["argument_grid"]["reflected.random_int.min_max_equal"].update(family="nope"),
        lambda d: d["argument_grid"]["reflected.random_int.min_max_equal"].update(extra=1),
        lambda d: d["argument_grid"]["reflected.random_int.min_max_equal"].update(locales="en_US"),
        lambda d: d["argument_grid"]["reflected.random_int.min_max_equal"]["arguments"].update(
            kwargs={"min": {"date": 1}}
        ),
        lambda d: d["locales"]["en_US"]["argumented"]["reflected.random_int.min_max_equal"].update(
            arguments={}
        ),
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


def test_unstable_set_in_the_lock_is_not_compared_by_digest() -> None:
    old = _minimal_lock()["locales"]
    old["en_US"]["reflected"]["first_name"]["per_seed"] = "unstable"
    new = copy.deepcopy(old)
    assert not any(output_lock.diff_locales(old, new).values())
