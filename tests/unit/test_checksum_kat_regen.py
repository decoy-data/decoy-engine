"""The committed check-digit KAT is exactly what the Python oracle produces today.

`decoy-engine-native/tests/kat_checksum.rs` trusts `vectors/checksum_kat.json`. This test
regenerates the corpus with the generator and compares every field except the engine commit in
the provenance block, so the file cannot drift from `decoy_engine.checksums` or be edited by hand.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_VECTORS = Path(__file__).resolve().parents[2] / "decoy-engine-native" / "vectors"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_checksum_kat", _VECTORS / "generate_checksum_kat.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed() -> dict:
    return json.loads((_VECTORS / "checksum_kat.json").read_text(encoding="utf-8"))


def test_the_committed_corpus_equals_a_fresh_regeneration() -> None:
    committed = _committed()
    fresh = _generator().build_corpus(committed["provenance"]["engine_commit"])
    assert fresh == committed


def test_the_corpus_is_versioned_and_names_its_provenance() -> None:
    committed = _committed()
    assert committed["format_version"] == 1
    assert set(committed["provenance"]) == {"generator", "python_stdnum", "engine_commit", "seed"}


def test_the_corpus_covers_every_scheme_with_at_least_200_bodies() -> None:
    counts: dict[str, int] = {}
    for row in _committed()["bodies"]:
        counts[row["scheme"]] = counts.get(row["scheme"], 0) + 1
    assert set(counts) == {"luhn", "npi", "ean13", "gtin", "isbn13", "vin"}
    assert min(counts.values()) >= 200
