"""R1-1: a filesystem failure on a loader's probe or first read is value-free too.

A path under a directory the process cannot read makes the OS raise `PermissionError` with the
full path in its text. The loaders probed or read the file before `read_config` ran, so a
credential in a URL-shaped locator leaked through `str(exc)`. Each route must give a refusal
that shows no part of the locator, under the ambient and a strict policy.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from decoy_engine.detection.name_hints.loader import load_name_hint_terms
from decoy_engine.profiling.model_pack.loader import ModelPackLoader
from decoy_engine.transforms._codeset_loader import load_corpus, load_corpus_provenance
from tests.unit.safe_output.test_loader_outcomes_value_free import _caught, _surfaces, _world

CANARY = "CANARYhunter2secret"

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[Path]:
    """A URL-shaped locator whose parent directory the process cannot read."""
    outer = root / "locked"
    inner = outer / f"https:/user:{CANARY}@host"
    inner.mkdir(parents=True)
    outer.chmod(0o000)
    try:
        yield inner
    finally:
        outer.chmod(0o700)


def _corpus(inner: Path) -> object:
    return _caught(lambda: load_corpus("mine", inner / "c.parquet"))


def _corpus_provenance(inner: Path) -> object:
    return _caught(lambda: load_corpus_provenance("mine", inner / "c.parquet"))


def _name_hints(inner: Path) -> object:
    return _caught(lambda: load_name_hint_terms(inner))


def _model_pack(inner: Path) -> object:
    return _caught(lambda: ModelPackLoader(inner).load())


_ROUTES: dict[str, Callable[[Path], object]] = {
    "load_corpus": _corpus,
    "load_corpus_provenance": _corpus_provenance,
    "load_name_hint_terms": _name_hints,
    "model_pack_load": _model_pack,
}


@pytest.mark.parametrize("strict", [False, True], ids=["ambient", "strict"])
@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_unreadable_directory_error_shows_no_locator(route: str, strict: bool) -> None:
    with _world(strict) as root, _locked(root) as inner:
        outcome = _ROUTES[route](inner)
    assert isinstance(outcome, BaseException), outcome
    assert not isinstance(outcome, PermissionError), outcome
    for surface in _surfaces(outcome):
        assert CANARY not in surface, (route, strict, surface)
