"""REL-GATE RG-F1 (plan 5.2, AT-F1d): `frozen_schemas.py --check` names a file and a JSON pointer, never a value."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.release import frozen_schemas

MARKER = "zz-planted-marker-7f3a"
RUN_RESULT = "run-result.schema.json"


def _write(tmp_path: Path) -> Path:
    assert frozen_schemas.main(["--write", "--dir", str(tmp_path)]) == 0
    return tmp_path


def _edit(path: Path, change) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_a_fresh_write_checks_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert sorted(p.name for p in _write(tmp_path).iterdir()) == [
        "pipeline-config.schema.json",
        RUN_RESULT,
    ]
    assert frozen_schemas.main(["--check", "--dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_check_prints_the_first_differing_pointer_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _write(tmp_path)
    capsys.readouterr()
    doc = json.loads((directory / RUN_RESULT).read_text(encoding="utf-8"))
    first = min(doc["properties"])

    def plant(doc: dict) -> None:
        doc["properties"][first]["description"] = MARKER  # the first difference in key order
        doc["title"] = MARKER  # a later one, which must not be reported

    _edit(directory / RUN_RESULT, plant)
    assert frozen_schemas.main(["--check", "--dir", str(directory)]) == 1
    captured = capsys.readouterr()
    assert captured.out == f"{RUN_RESULT}: /properties/{first}/description\n"
    assert MARKER not in captured.out + captured.err


def test_a_missing_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (_write(tmp_path) / RUN_RESULT).unlink()
    capsys.readouterr()
    assert frozen_schemas.main(["--check", "--dir", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"{RUN_RESULT}: missing\n"


def test_same_json_in_another_layout_is_a_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _edit(_write(tmp_path) / RUN_RESULT, lambda doc: None)  # compact, not the indented form
    capsys.readouterr()
    assert frozen_schemas.main(["--check", "--dir", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"{RUN_RESULT}: layout\n"


@pytest.mark.parametrize(
    ("expected", "actual", "pointer"),
    [
        ({"a": 1}, {"a": 1}, None),
        ({"a/b": {"m~n": 1}}, {"a/b": {"m~n": 2}}, "/a~1b/m~0n"),
        ({"a": [1, 2]}, {"a": [1, 2, 3]}, "/a/2"),
        ({"a": 1, "c": 1}, {"b": 1, "c": 1}, "/a"),
        ([1], {"a": 1}, ""),
        (1, True, ""),
    ],
)
def test_first_difference_uses_rfc_6901_pointers(expected, actual, pointer) -> None:
    assert frozen_schemas.first_difference(expected, actual) == pointer
