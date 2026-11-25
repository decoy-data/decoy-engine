"""The NONFK-OOM S5 bench helpers (`scripts/bench-auto-chunk/bench_nonfk_fallthrough.py`).

The after-case reads three facts off a refused run: the registered code, that the error is cleanly
chained, and that no staging entry was left. These helpers hold the verdict, so a wrong one cannot
turn an OOM kill or a leaked directory into a "pass" in the record."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
CODE = "nonfk_full_frame_capacity_exceeded"


@pytest.fixture(scope="module")
def bench() -> Any:
    path = REPO / "scripts" / "bench-auto-chunk" / "bench_nonfk_fallthrough.py"
    spec = importlib.util.spec_from_file_location("bench_nonfk_fallthrough", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CodedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("text")
        self.code = code


def test_refusal_evidence_reports_code_and_clean_chaining(bench: Any) -> None:
    exc = _CodedError(CODE)
    assert bench.refusal_evidence(exc) == {"code": CODE, "clean_chaining": True}


def test_refusal_evidence_flags_a_chained_error(bench: Any) -> None:
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise _CodedError(CODE) from None
    except _CodedError as exc:
        # `from None` hides the cause but the context is still set: not clean.
        assert bench.refusal_evidence(exc)["clean_chaining"] is False


def test_new_entries_lists_only_what_appeared(bench: Any, tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    before = bench.snapshot_entries([tmp_path])
    (tmp_path / "staging-x").mkdir()
    assert bench.new_entries(before, bench.snapshot_entries([tmp_path])) == [
        str(tmp_path / "staging-x")
    ]


def test_new_entries_empty_when_nothing_appeared(bench: Any, tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    before = bench.snapshot_entries([tmp_path])
    assert bench.new_entries(before, bench.snapshot_entries([tmp_path])) == []


@pytest.mark.parametrize(
    ("exit_code", "stderr", "target", "staging", "expected"),
    [
        (5, f"error: {CODE}", False, [], True),
        (-9, "", False, [], False),  # killed for memory: the before-case
        (1, f"error: {CODE}", False, [], False),  # wrong exit class
        (5, "error: something else", False, [], False),  # not the registered code
        (5, f"error: {CODE}", True, [], False),  # a target file appeared
        (5, f"error: {CODE}", False, ["/x/.staging"], False),  # staging left behind
    ],
)
def test_e2e_refused_cleanly(
    bench: Any, exit_code: int, stderr: str, target: bool, staging: list[str], expected: bool
) -> None:
    assert bench.e2e_refused_cleanly(exit_code, stderr, target, staging) is expected
