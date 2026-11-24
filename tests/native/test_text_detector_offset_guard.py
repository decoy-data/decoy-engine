"""TEXT-REDACT-RUST-SPLICE S0: the Rust detector offset guard.

`is_eligible` (the one predicate behind `text_redact_candidates` and `text_mask_detect_splice`)
declines a cell whose byte length exceeds `DETECTOR_OFFSET_LIMIT`, so no end offset is narrowed to
a wrapped u32. A wheel built with the test-only crate feature `test-detector-offset-limit` lowers
the limit to 64 bytes, which lets a 65-byte email stand in for a 4 GiB cell.

AT-3 (detector offsets, S0 part) calls both legacy exports of that wheel directly.
AT-11 runs the core as it was before S0 (`OLD_CORE_SHA`) against the same wheel.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.native._c6c_ii_support import NEEDS_TR_KERNEL
from tests.native._detector_offset_support import (
    CRATE,
    OVERSIZED_EMAIL,
    SHORT_EMAIL,
    build_tooling_missing,
    build_wheel_dir,
    export_old_core_src,
    run_snippet,
)

_NEEDS_BUILD = pytest.mark.skipif(
    build_tooling_missing() is not None,
    reason=f"cannot build the test-limit wheel: {build_tooling_missing()}",
)

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(scope="module")
def limit_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_wheel_dir(
        tmp_path_factory.mktemp("limit-wheel"), features="test-detector-offset-limit"
    )


@pytest.fixture(scope="module")
def old_core_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    src = export_old_core_src(tmp_path_factory.mktemp("old-core"))
    if src is None:
        pytest.skip("the pre-S0 commit is not in this checkout's history")
    return src


_DIRECT_EXPORTS = f"""
from decoy_engine_native import _kernel as k
ids = k.text_redact_supported_ids()
version = k.text_redact_catalog_version()
cands = k.text_redact_candidates([{OVERSIZED_EMAIL!r}, {SHORT_EMAIL!r}], ids, version)
splice = k.text_mask_detect_splice(
    [{OVERSIZED_EMAIL!r}, {SHORT_EMAIL!r}], ids, [False] * len(ids), "<X>", False, version
)
print(json.dumps({{"cands": cands, "splice": splice, "email": ids.index("email")}}))
"""


@_NEEDS_BUILD
def test_at3_both_legacy_exports_decline_an_oversized_cell(limit_wheel: Path) -> None:
    got = run_snippet(_DIRECT_EXPORTS, wheel_dir=limit_wheel, core_src=SRC)
    email = got["email"]
    assert got["cands"] == [None, [[email, 0, len(SHORT_EMAIL)]]]
    assert got["splice"] == [None, "<X>"]


_OLD_CORE_CALLS = f"""
from unittest import mock
import pyarrow as pa
from decoy_engine.execution.native import _kernels_scalar, _text_mask_native_splice as spl
from decoy_engine.execution.native._text_redact_kernel import (
    CATALOG_VERSION, load_text_redact_kernel, requested_rust_ids,
)
from decoy_engine.execution._strategies._text_redact import _splice

values = [{OVERSIZED_EMAIL!r}, None, {SHORT_EMAIL!r}]
kernel = load_text_redact_kernel()
assert kernel is not None, "the old core did not load the new wheel"
ids = requested_rust_ids(["email"])
declined = kernel.text_redact_candidates(values, ids, CATALOG_VERSION)[0] is None

with mock.patch.object(_kernels_scalar, "iter_spans", wraps=_kernels_scalar.iter_spans) as spy:
    redact = _kernels_scalar.native_text_redact(
        pa.array(values, type=pa.string()), detectors=("email",), token="<X>", label_token=False
    ).to_pylist()
redact_oracle_calls = spy.call_count

plan = spl.plan_native_splice(["email"], {{"email": "redact"}}, "passthrough", "<X>")
splice_kernel = spl.load_splice_kernel()
with mock.patch.object(spl, "iter_spans", wraps=spl.iter_spans) as spy:
    mask = spl.splice_batch(
        values, plan=plan, splice=splice_kernel, kernel=kernel, detector_ids=["email"],
        rust_ids=ids, fallback=lambda text, spans: _splice(text, spans, "<X>", False),
    )
mask_oracle_calls = spy.call_count
print(json.dumps({{
    "declined": declined, "redact": redact, "redact_oracle_calls": redact_oracle_calls,
    "mask": mask, "mask_oracle_calls": mask_oracle_calls,
}}))
"""


@_NEEDS_BUILD
def test_at11_old_core_with_new_wheel_keeps_oversized_email_redacted(
    limit_wheel: Path, old_core_src: Path
) -> None:
    got = run_snippet(_OLD_CORE_CALLS, wheel_dir=limit_wheel, core_src=old_core_src)
    assert got["declined"] is True
    assert got["redact"] == ["<X>", None, "<X>"]
    assert got["redact_oracle_calls"] == 1
    assert got["mask"] == ["<X>", None, "<X>"]
    assert got["mask_oracle_calls"] == 1


@_NEEDS_BUILD
def test_parity_smoke_refuses_a_wheel_built_with_the_test_feature(limit_wheel: Path) -> None:
    smoke = CRATE / "scripts" / "parity_smoke.py"
    env = {**os.environ, "PYTHONPATH": str(limit_wheel)}
    done = subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
        [sys.executable, str(smoke)], env=env, capture_output=True, text=True, timeout=120
    )
    assert done.returncode != 0
    assert "test-detector-offset-limit" in (done.stdout + done.stderr)


@NEEDS_TR_KERNEL
def test_a_release_wheel_passes_parity_smoke_and_keeps_a_65_byte_email() -> None:
    smoke = CRATE / "scripts" / "parity_smoke.py"
    done = subprocess.run([sys.executable, str(smoke)], capture_output=True, text=True, timeout=120)  # noqa: S603 - fixed argument lists, no untrusted input
    assert done.returncode == 0, done.stdout + done.stderr
    from decoy_engine_native import _kernel

    ids = _kernel.text_redact_supported_ids()
    got = _kernel.text_redact_candidates(
        [OVERSIZED_EMAIL], ids, _kernel.text_redact_catalog_version()
    )
    assert got == [[(ids.index("email"), 0, len(OVERSIZED_EMAIL))]]
