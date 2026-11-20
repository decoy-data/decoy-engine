"""Shared loader, fixtures and helpers for the Faker output-lock sentries (no tests here).

The three sentry modules (`test_faker_output_lock.py`, `..._schema.py`, `..._arguments.py`) import
from here, so the lock tool is loaded once and the worker fixtures are defined once.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.sentry.dependencies._faker_lock_lists import (
    ANCHORS,
    EN_US_DIGEST_FLOOR,
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
    row = {
        "family": "reflected",
        "target": "random_int",
        "method": "random_int",
        "locales": ["en_US"],
        "covers": ["max", "min"],
        "arguments": {"args": [], "kwargs": {"min": 7, "max": 7}},
    }
    return {
        "lock_version": 2,
        "faker_version": "40.23.0",
        "codec_version": 1,
        "samples": 8,
        "argument_samples": 2,
        "clocks": ["2026-10-16T12:00:00Z", "2030-01-16T12:00:00Z"],
        "argument_grid": {"reflected.random_int.min_max_equal": row},
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
                    "reflected.random_int.min_max_equal": {"draws": digest, "calendar": False}
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


_WRONG_TYPES: tuple[Any, ...] = (True, 7, 8.0, "7", "x", None, [], {})


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


@functools.cache
def derived_surface() -> tuple[dict[str, Any], dict[tuple[str, str, str], set[str]]]:
    """The grid and provenance derived from the runtime callables of every locale, once."""
    import _engine_access as access
    from faker.config import AVAILABLE_LOCALES

    return output_lock.argument_grid.analyze(access, sorted(AVAILABLE_LOCALES))
