"""AT-E2-1 to AT-E2-6, AT-E2-8, AT-E2-11 to AT-E2-13: the synthetic probe (slice 78-E2).

The probe runs fixed public inputs through the engine's Python reference code for the keyed
hash, FF1 and the seeded Faker pool, and digests the answers. A host that does not reproduce the
golden for its seed protocol is `mismatch`, never `ok`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import keyprovider, providers_v2, reasons
from decoy_engine.providers_v2._faker_adapter import _unregister_faker_provider_v2
from decoy_engine.support import ProbeError, _probe, probe_status, run_probe

ROOT = Path(__file__).resolve().parents[3]
HEX64 = re.compile(r"[0-9a-f]{64}")


def test_probe_equals_the_golden_for_the_current_protocol() -> None:
    digest = run_probe()
    assert HEX64.fullmatch(digest)
    assert digest == _probe.PROBE_GOLDEN[_probe.SEED_PROTOCOL_VERSION]
    assert probe_status(digest) == "ok"
    assert probe_status(None) == "mismatch"


def test_probe_is_equal_across_processes_with_different_hash_seeds() -> None:
    code = "import sys\nfrom decoy_engine.support import run_probe\nsys.stdout.write(run_probe())\n"
    outputs = set()
    for seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(  # noqa: S603 -- fixed argv, own interpreter
            [sys.executable, "-c", code], capture_output=True, env=env, check=True, timeout=120
        )
        outputs.add(done.stdout.decode())
    assert outputs == {run_probe()}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HASH_NAMESPACE", "probe/hash2"),
        ("FPE_TWEAK_IDENTITY", "probe.fpe2"),
        ("PROBE_JOB_SEED", b"\x00" * 8),
    ],
)
def test_each_probe_part_feeds_the_digest(
    monkeypatch: pytest.MonkeyPatch, name: str, value: Any
) -> None:
    before = run_probe()
    monkeypatch.setattr(_probe, name, value)
    assert run_probe() != before


def test_a_missing_or_changed_golden_row_is_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = run_probe()
    assert probe_status(digest) == "ok"
    monkeypatch.setattr(_probe, "SEED_PROTOCOL_VERSION", 9999)
    assert probe_status(digest) == "mismatch"
    monkeypatch.undo()
    monkeypatch.setattr(_probe, "PROBE_GOLDEN", {_probe.SEED_PROTOCOL_VERSION: "0" * 64})
    assert probe_status(digest) == "mismatch"


def test_the_probe_never_reads_a_key_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = run_probe()
    monkeypatch.setenv("DECOY_MASK_SECRET", "ab" * 32)

    def spy(*_: Any, **__: Any) -> Any:
        raise AssertionError("the probe touched a key provider")

    for owner, name in (
        (keyprovider.SecretKeyProvider, "mask_key"),
        (keyprovider.SeedKeyProvider, "mask_key"),
        (keyprovider, "key_provider_from_ref"),
        (keyprovider, "resolve_mask_key"),
        (keyprovider, "require_mask_key"),
        (keyprovider, "mask_key_from_provider"),
    ):
        monkeypatch.setattr(owner, name, spy)
    assert run_probe() == expected


_IO_GUARD = {"on": False}


def _io_audit(event: str, args: tuple[Any, ...]) -> None:
    # An audit hook cannot be removed, so it stays installed and only acts while the flag is on.
    if _IO_GUARD["on"] and (event == "open" or event.startswith("socket.")):
        raise AssertionError(f"the probe did I/O: {event}")


sys.addaudithook(_io_audit)


def test_the_probe_opens_no_file_and_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas
    import pyarrow.parquet

    run_probe()  # first-use imports are not the probe's own I/O

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("the probe read a parquet file")

    # Audit events cover open(), io.open, os.open, pathlib and socket; the Arrow readers open
    # files in C++, so they are patched by name.
    monkeypatch.setattr(pyarrow.parquet, "read_table", refuse)
    monkeypatch.setattr(pandas, "read_parquet", refuse)
    _IO_GUARD["on"] = True
    try:
        digest = run_probe()
    finally:
        _IO_GUARD["on"] = False
    assert HEX64.fullmatch(digest)


def test_a_failing_part_raises_a_value_free_probe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = "/home/x/secret"

    def boom() -> list[str]:
        raise ValueError(marker)

    monkeypatch.setattr(_probe, "_fpe_part", boom)
    with pytest.raises(ProbeError) as caught:
        run_probe()
    err = caught.value
    assert err.code == "probe_failed"
    assert err.__cause__ is None
    assert err.__context__ is None
    assert marker not in str(err)
    assert marker not in err.message


def test_the_probe_reason_is_cataloged_as_unreleased() -> None:
    spec = reasons.get_reason("runtime", "probe_failed")
    assert spec.since == "1.30.0"


def test_the_ci_import_smoke_job_runs_the_probe_step() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = re.search(r"^  import-smoke:\n(.*?)(?=^  \S)", text, re.S | re.M)
    assert job is not None
    steps = job.group(1)
    assert 'python -c "import decoy_engine"' in steps
    assert "run_probe" in steps
    assert 'probe_status(run_probe()) == "ok"' in steps


# AT-E2-13 --------------------------------------------------------------------------------------


@pytest.fixture
def custom_first_name() -> Any:
    calls: list[int] = []

    def fn(_fake: Any) -> str:
        calls.append(1)
        return "custom"

    providers_v2.register_faker_provider_v2("person_first_name", fn)
    try:
        yield calls
    finally:
        _unregister_faker_provider_v2("person_first_name")


def test_a_custom_person_first_name_provider_is_refused_before_any_draw(
    custom_first_name: list[int],
) -> None:
    assert "person_first_name" in providers_v2.custom_provider_names()
    with pytest.raises(ProbeError) as caught:
        run_probe()
    assert caught.value.code == "probe_failed"
    assert custom_first_name == []
    _unregister_faker_provider_v2("person_first_name")
    assert "person_first_name" not in providers_v2.custom_provider_names()
    assert HEX64.fullmatch(run_probe())


# V1-1: the pool part is a Faker pool on every install ----------------------------------------


def test_the_pool_part_pins_the_faker_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.providers_v2 import FakerAdapter

    # `person_first_name` is a Mimesis adoption candidate; the pin is what keeps the answer a
    # Faker one on a host with the extra installed.
    seen: list[type] = []
    real = providers_v2.ProviderRegistry.override

    def spy(self: Any, provider: str, adapter: Any, caps: Any) -> Any:
        seen.append(type(adapter))
        return real(self, provider, adapter, caps)

    monkeypatch.setattr(providers_v2.ProviderRegistry, "override", spy)
    run_probe()
    assert seen == [FakerAdapter]


def test_a_mimesis_style_binding_does_not_change_the_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = run_probe()
    registry = providers_v2.get_default_registry()
    caps = registry.get_capabilities(_probe.POOL_PROVIDER)

    class Other:
        """Stands in for the Mimesis adapter: same provider name, other values."""

        def generate_batch(self, provider: str, *, spec: Any, count: int) -> list[str]:
            return [f"other-{n}" for n in range(count)]

        def capability_matrix(self, provider: str) -> Any:
            return caps

    rebound = registry.override(_probe.POOL_PROVIDER, Other(), caps)  # type: ignore[arg-type]
    monkeypatch.setattr(providers_v2, "get_default_registry", lambda: rebound)
    assert run_probe() == expected
