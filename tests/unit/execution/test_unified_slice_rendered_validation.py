"""EXPECT-OFF-ROUTE S2: the unified slice validates the bytes it renders, as full-frame does.

Full-frame runs validators after declared casting formats the outputs and after post-mask row
quarantine drops rows. The unified slice must judge the same rows: a format-sensitive check sees
the rendered text, and failing row indices count rows after the drop.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.errors import ValidatorFailedError
from decoy_engine.execution.native._companion_status import native_companion_status
from tests.acceptance._f06_support import (
    INT64,
    PROTECTED_QUARANTINE,
    column,
    config,
    run,
    text_table,
    write_csv,
    zero_pad,
)

pytestmark = pytest.mark.skipif(
    not native_companion_status().ok, reason="compiled decoy-engine-native companion unavailable"
)

_LANE = "unified_slice_activation"
# "x" fails the parse; 1000 does not fit the 3-wide output, so post-mask quarantine drops it.
_AGES = ["042", "7", "x", "1000", "5", "12", "0", "9"]
# Rendered ages are zero-padded to three digits; the typed integer before the render is not.
_RENDERED = r"^[0-9]{3}$"
_LEADING_TWO_ZEROS = r"^00"


def _cfg(tmp_path: Path, policy: str, pattern: str) -> dict[str, Any]:
    src = write_csv(tmp_path / "g.csv", ["id", "age"], [["1", "1"]])
    cols = [
        column("id"),
        column(
            "age",
            logical_type="integer",
            parse_format=INT64,
            error_policy=policy,
            output_format=zero_pad(3),
        ),
    ]
    check = {"name": "regex_match", "columns": {"people": ["age"]}, "params": {"pattern": pattern}}
    top: dict[str, Any] = {"validators": [check]}
    if policy == "quarantine":
        top["protected_quarantine"] = PROTECTED_QUARANTINE
    return config(cols, source_path=src, top=top)


def _runtime(root: Path) -> Any:
    from decoy_engine.declared_casting import (
        LocalProtectedQuarantineSink,
        ProtectedQuarantineRuntime,
    )
    from decoy_engine.keyprovider import SecretKeyProvider

    sink = LocalProtectedQuarantineSink(root, key_provider=SecretKeyProvider(secret=b"q" * 32))
    return ProtectedQuarantineRuntime(sink=sink, owner="tenant-1", run_id="run-A")


def _verdict(tmp_path: Path, policy: str, pattern: str, *, unified: bool) -> dict[str, Any]:
    """The run's validation report without timings, and whether the lane took the job."""
    tag = "uni" if unified else "full"
    kwargs: dict[str, Any] = {"auto_chunk": False, "unified_slice_enabled": unified}
    if policy == "quarantine":
        kwargs["quarantine_runtime"] = _runtime(tmp_path / f"q-{tag}")
    source = text_table(id=[str(i) for i in range(len(_AGES))], age=_AGES)
    try:
        result = run(_cfg(tmp_path, policy, pattern), {"people": source}, **kwargs)
    except ValidatorFailedError as exc:
        verdict: dict[str, Any] = {"raised": True, "report": dataclasses.asdict(exc.report)}
    else:
        report = dict(result.quality_metrics["validation"]["validators"])
        verdict = {"raised": False, "report": report, "lane": _LANE in result.quality_metrics}
    verdict["report"].pop("elapsed_ms", None)
    for item in verdict["report"].get("results", ()):
        item.pop("elapsed_ms", None)
    return verdict


@pytest.mark.parametrize("policy", ["null", "quarantine"])
def test_a_format_sensitive_check_passes_on_the_rendered_bytes_as_full_frame(
    tmp_path: Path, policy: str
) -> None:
    full = _verdict(tmp_path, policy, _RENDERED, unified=False)
    uni = _verdict(tmp_path, policy, _RENDERED, unified=True)
    assert full["raised"] is False and full["report"]["passed"] is True
    assert full.pop("lane") is False
    assert uni["raised"] is False, "the unified slice judged the typed value, not the render"
    assert uni.pop("lane") is True, "the unified slice did not take the job"
    assert uni == full


def test_failing_rows_count_after_post_mask_quarantine_as_full_frame(tmp_path: Path) -> None:
    full = _verdict(tmp_path, "quarantine", _LEADING_TWO_ZEROS, unified=False)
    uni = _verdict(tmp_path, "quarantine", _LEADING_TWO_ZEROS, unified=True)
    assert full["raised"] is True
    assert uni == full
