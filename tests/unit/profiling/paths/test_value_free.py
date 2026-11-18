"""F07 82-E2b: the path text and every count are value-free (AT-E2-2, AT-E2-3)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.profiling import scan_set_to_dict

from ._support import by_path, dumps, observation, ref, scan_cells, warning_codes

LEAF = "CANARY-LEAF-9f3a71"
KEY = "CANARY KEY-9f3a71!"
MISS = "CANARY-MISS-9f3a71"


def test_at_e2_2_no_canary_reaches_the_record_or_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cells: list[dict[str, Any]] = []
    for i in range(10):
        email = f"{MISS}-{i}" if i < 3 else f"user{i}@example.com"
        cells.append({"email": email, "note": f"{LEAF}-{i}", KEY: f"{LEAF}-{i}"})
    with caplog.at_level(logging.DEBUG):
        scan = scan_cells(tmp_path, dumps(cells))
        document = json.dumps(scan_set_to_dict(scan, detail=False))
    obs = observation(scan)
    assert by_path(obs)["$.email"].detector_hits == ["email"]
    assert "$.*" in by_path(obs)
    assert "CANARY" not in document
    assert "CANARY" not in caplog.text
    assert "CANARY" not in repr(obs)


def test_at_e2_3_keys_that_fail_the_key_rule_become_a_wildcard(tmp_path: Path) -> None:
    cell = {"alice@example.com": 1, "name\n": 2, "123": 3, "status": 4}
    scan = scan_cells(tmp_path, dumps([cell] * 5))
    obs = observation(scan)
    assert set(by_path(obs)) == {"$.status", "$.*"}
    assert obs.key_suspect_collapsed == 15
    assert ref("NESTED_PATH_KEY_SUSPECT") in warning_codes(scan)
    assert "alice" not in json.dumps(scan_set_to_dict(scan, detail=False))


def test_a_data_key_that_repeats_in_every_cell_never_appears_by_name(tmp_path: Path) -> None:
    cell = {"alice@example.com": 1, "GB82WEST12345698765432": 2, "123-45-6789": 3, "note": "n"}
    scan = scan_cells(tmp_path, dumps([cell] * 30))
    document = json.dumps(scan_set_to_dict(scan, detail=False))
    assert set(by_path(observation(scan))) == {"$.note", "$.*"}
    for text in ("alice", "GB82", "123-45"):
        assert text not in document


def test_many_distinct_data_like_keys_collapse_the_level_with_bounded_detector_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine._canonical import SCAN_MAP_KEYS
    from decoy_engine.profiling.paths import _walk

    runs: list[int] = []
    real = _walk.run_all_detectors

    def spy(*args: Any, **kwargs: Any) -> Any:
        runs.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_walk, "run_all_detectors", spy)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    cell = {f"{c}{n:02d}": 1 for c in letters for n in range(100)}  # ICD-10 shaped: detector hits
    obs = observation(scan_cells(tmp_path, dumps([cell] * 3)))
    assert set(by_path(obs)) == {"$.*"} and obs.map_collapsed == 1
    assert 0 < len(runs) <= SCAN_MAP_KEYS + 1
