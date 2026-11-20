"""Fast, CI-safe tests for the faker pool determinism harness driver
(`scripts/faker-determinism/check_determinism.py`,
plan_faker_determinism_harness_v2.md C3/C4).

Loaded by file path, not package import (`scripts/faker-determinism` has a
hyphen), mirroring `tests/physical/test_bench_gen_pool_harness.py`'s pattern
for its sibling `bench_compare_gen.py`.

Covers: the pure verdict logic for every status branch (no subprocess), the
candidate matrix builder, golden load/write round-tripping (tmp_path, never
the repo's own `golden_digests.json`), CLI arg validation, and the C4
MANDATORY synthetic fail-control -- a driver unit test that two distinct
digests are reported as divergence (no subprocess), plus a real subprocess
run against `hash_order_probe_worker.py` proving the driver catches a
genuinely hash-seed-dependent worker. The full candidate matrix against the
committed golden lives in `tests/generation/test_faker_pool_determinism.py`
and its slower, explicitly-marked full-sweep counterpart -- this module
only proves the driver's own machinery is correct, cheaply.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = ENGINE_ROOT / "scripts" / "faker-determinism"

_spec = importlib.util.spec_from_file_location(
    "check_determinism", HARNESS_DIR / "check_determinism.py"
)
assert _spec is not None and _spec.loader is not None
check_determinism = importlib.util.module_from_spec(_spec)
sys.modules["check_determinism"] = check_determinism
_spec.loader.exec_module(check_determinism)

Candidate = check_determinism.Candidate
verdict_from_records = check_determinism.verdict_from_records
build_matrix = check_determinism.build_matrix
load_golden = check_determinism.load_golden
write_golden = check_determinism.write_golden
parse_and_validate_args = check_determinism.parse_and_validate_args
build_arg_parser = check_determinism.build_arg_parser
main = check_determinism.main


def _record(
    *,
    pool_digest: str = "p",
    output_digest: str = "o",
    exact: bool = True,
    custom: bool = False,
    resolved_locale: str = "en_US",
) -> dict[str, Any]:
    return {
        "pool_digest": pool_digest,
        "output_digest": output_digest,
        "exact_name_available": exact,
        "custom_override_present": custom,
        "meta": {"resolved_locale": resolved_locale, "requested_locale": resolved_locale},
    }


# ---------------------------------------------------------------------------
# Pure verdict logic -- every status branch, no subprocess.
# ---------------------------------------------------------------------------


def test_verdict_certified_when_everything_agrees() -> None:
    candidate = Candidate("first_name", "en_US", {})
    records = [_record() for _ in range(8)]
    result = verdict_from_records(candidate, records)
    assert result.status == "certified"
    assert result.pool_digest == "p"
    assert result.output_digest == "o"


def test_verdict_not_available_when_exact_name_unavailable() -> None:
    candidate = Candidate("state", "ja_JP", {})
    records = [_record(exact=False, pool_digest="x", output_digest="y") for _ in range(3)]
    result = verdict_from_records(candidate, records)
    assert result.status == "not_available"


def test_verdict_custom_override_takes_priority_over_digest_agreement() -> None:
    candidate = Candidate("city", "en_US", {})
    records = [_record(custom=True) for _ in range(3)]
    result = verdict_from_records(candidate, records)
    assert result.status == "custom_override"


def test_verdict_locale_fallback_rejected_even_with_agreeing_digests() -> None:
    candidate = Candidate("first_name", "xx_XX", {})
    records = [_record(resolved_locale="en_US") for _ in range(3)]
    result = verdict_from_records(candidate, records)
    assert result.status == "locale_fallback"


def test_verdict_divergent_when_pool_digest_disagrees() -> None:
    """The C4 driver-unit synthetic fail-control (plan's requirement (i)):
    feed two distinct digests directly, with no subprocess involved, and
    confirm the driver reports divergence -- proving the check CAN fail,
    not merely that it agrees on identical inputs."""
    candidate = Candidate("city", "en_US", {})
    records = [
        _record(pool_digest="aaa", output_digest="o"),
        _record(pool_digest="bbb", output_digest="o"),
    ]
    result = verdict_from_records(candidate, records)
    assert result.status == "divergent"
    assert result.pool_digest is None


def test_verdict_divergent_when_output_digest_disagrees_but_pool_agrees() -> None:
    candidate = Candidate("city", "en_US", {})
    records = [
        _record(pool_digest="same", output_digest="aaa"),
        _record(pool_digest="same", output_digest="bbb"),
    ]
    result = verdict_from_records(candidate, records)
    assert result.status == "divergent"
    assert result.pool_digest == "same"
    assert result.output_digest is None


def test_verdict_inconsistent_when_eligibility_itself_flaps() -> None:
    """exact_name_available disagreeing across K identical-input runs is a
    stronger, distinct signal than an ordinary non-certification -- the
    resolver itself is not process-stable."""
    candidate = Candidate("weird_type", "en_US", {})
    records = [_record(exact=True), _record(exact=False)]
    result = verdict_from_records(candidate, records)
    assert result.status == "inconsistent"


def test_verdict_does_not_mutate_len_after_popping_a_representative_value() -> None:
    """Regression guard for the set.pop()-mutates-before-length-check bug
    found during manual verification: 8 agreeing records must certify, not
    report divergence because the representative-value pop emptied the set
    the length check then re-read."""
    candidate = Candidate("first_name", "en_US", {})
    records = [_record() for _ in range(8)]
    result = verdict_from_records(candidate, records)
    assert result.status == "certified"


# ---------------------------------------------------------------------------
# Candidate + matrix
# ---------------------------------------------------------------------------


def test_candidate_key_is_stable_and_kwargs_order_independent() -> None:
    a = Candidate("city", "en_US", {"x": 1, "y": 2})
    b = Candidate("city", "en_US", {"y": 2, "x": 1})
    assert a.key == b.key


def test_candidate_key_distinguishes_kwargs() -> None:
    a = Candidate("country_code", "en_US", {})
    b = Candidate("country_code", "en_US", {"representation": "alpha-3"})
    assert a.key != b.key


def test_build_matrix_is_the_cross_product() -> None:
    matrix = build_matrix(["a", "b"], ["en_US", "fr_FR"], {})
    assert len(matrix) == 4
    assert {(c.faker_type, c.locale) for c in matrix} == {
        ("a", "en_US"),
        ("a", "fr_FR"),
        ("b", "en_US"),
        ("b", "fr_FR"),
    }


# ---------------------------------------------------------------------------
# Golden load/write round-trip (tmp_path only -- never the repo's own file).
# ---------------------------------------------------------------------------


def test_golden_round_trip(tmp_path: Path) -> None:
    golden_path = tmp_path / "golden.json"
    assert load_golden(golden_path) == {}
    payload = {"city|en_US|{}": {"pool_digest": "p", "output_digest": "o"}}
    write_golden(golden_path, payload)
    assert load_golden(golden_path) == payload


# ---------------------------------------------------------------------------
# CLI arg validation
# ---------------------------------------------------------------------------


def test_args_reject_k_exceeding_hash_seed_count() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parse_and_validate_args(["--k", "20", "--hash-seeds", "0,1,2"], parser)


def test_args_reject_duplicate_hash_seeds() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parse_and_validate_args(["--hash-seeds", "0,1,1"], parser)


def test_args_reject_bad_kwargs_json() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parse_and_validate_args(["--kwargs-json", "not json"], parser)


def test_args_reject_missing_worker_path() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parse_and_validate_args(["--worker", "/no/such/worker.py"], parser)


def test_args_default_worker_and_golden_paths_resolve_under_harness_dir() -> None:
    args = parse_and_validate_args([])
    assert args.worker_path == (HARNESS_DIR / "pool_determinism_worker.py").resolve()
    assert args.golden_path == (HARNESS_DIR / "golden_digests.json").resolve()


# ---------------------------------------------------------------------------
# C4 mandatory synthetic fail-control (ii): real subprocess run against the
# hash-order probe worker, proving the driver flags a genuinely
# hash-seed-dependent worker as divergent -- not a hand-fed unit test.
# ---------------------------------------------------------------------------


def test_driver_flags_hash_order_probe_worker_as_divergent(tmp_path: Path) -> None:
    probe_worker = HARNESS_DIR / "hash_order_probe_worker.py"
    certified_out = tmp_path / "certified.json"
    report_out = tmp_path / "report.json"
    golden_path = tmp_path / "golden.json"  # empty: no regression comparison possible

    exit_code = main(
        [
            "--types",
            "word",
            "--locales",
            "en_US",
            "--k",
            "4",
            "--hash-seeds",
            "0,1,2,3",
            "--jobs",
            "1",
            "--worker",
            str(probe_worker),
            "--certified-out",
            str(certified_out),
            "--report-out",
            str(report_out),
            "--golden-path",
            str(golden_path),
        ]
    )
    # The candidate itself failing to certify is not a driver-infrastructure
    # failure, so the overall exit code stays 0; what this test asserts is
    # the PER-CANDIDATE status, which is what proves the check can fail.
    assert exit_code == 0
    report = json.loads(report_out.read_text())
    assert len(report["results"]) == 1
    assert report["results"][0]["status"] == "divergent"
    assert certified_out.exists()
    assert json.loads(certified_out.read_text()) == []


# ---------------------------------------------------------------------------
# --write-golden may only regenerate the baseline over the exact canonical
# full-matrix workload: any weakening (esp. reduced K) would bake an
# under-verified pair into the committed golden the addition slice trusts.
# ---------------------------------------------------------------------------


def _write_golden_rejects(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_and_validate_args(["--write-golden", *argv])


def test_write_golden_accepts_canonical_full_matrix() -> None:
    args = parse_and_validate_args(["--write-golden"])
    assert args.write_golden is True
    assert tuple(args.hash_seeds) == check_determinism.DEFAULT_HASH_SEEDS


def test_write_golden_rejects_reduced_k_single_seed() -> None:
    # The dangerous case: K=1 means one worker trivially "agrees" with itself.
    _write_golden_rejects(["--k", "1", "--hash-seeds", "0"])


def test_write_golden_rejects_narrowed_types() -> None:
    _write_golden_rejects(["--types", "first_name"])


def test_write_golden_rejects_narrowed_locales() -> None:
    _write_golden_rejects(["--locales", "en_US"])


def test_write_golden_rejects_nonempty_kwargs() -> None:
    _write_golden_rejects(["--kwargs-json", '{"length": 3}'])


def test_write_golden_rejects_reordered_seeds() -> None:
    _write_golden_rejects(["--hash-seeds", "7,6,5,4,3,2,1,0"])


def test_write_golden_rejects_nondefault_worker() -> None:
    # digest_codec.py exists but is not the default worker path.
    alt = str(HARNESS_DIR / "digest_codec.py")
    _write_golden_rejects(["--worker", alt])


def test_assert_mode_still_allows_narrowed_workload() -> None:
    # WITHOUT --write-golden, a narrowed run (e.g. the marked fast-subset test)
    # is legitimate: it only asserts against the golden, never rewrites it.
    args = parse_and_validate_args(["--types", "first_name", "--k", "1", "--hash-seeds", "0"])
    assert args.write_golden is False


# ---------------------------------------------------------------------------
# FAKER-MIGRATE (AT-L14, AT-L15): one worker environment, one engine-internal access module.
# ---------------------------------------------------------------------------

import ast  # noqa: E402

_TOOLS = ("check_determinism.py", "pool_determinism_worker.py", "output_lock.py")


def _imports(source: str) -> list[tuple[str, tuple[str, ...]]]:
    """Every import in `source` as (module, imported names), `import a.b` giving ("a.b", ())."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [(a.name, ()) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            out.append((node.module or "", tuple(a.name for a in node.names)))
    return out


def _reaches_engine_internal(source: str) -> bool:
    for module, names in _imports(source):
        if module == "decoy_engine.internal" or module.startswith("decoy_engine.internal."):
            return True
        if module == "decoy_engine" and "internal" in names:
            return True
    return False


def _internal_importers(directory: Path) -> list[str]:
    return sorted(
        p.name
        for p in directory.glob("*.py")
        if _reaches_engine_internal(p.read_text(encoding="utf-8"))
    )


def test_worker_env_matches_the_prior_contract() -> None:
    env_mod = _load_sibling("worker_env")
    assert env_mod.worker_env(Path("/r"), 3, "abc") == {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": "/r/src",
        "PYTHONHASHSEED": "3",
        "TZ": "UTC",
        "LC_ALL": "C",
        "LANG": "C",
        "DECOY_ENGINE_COMMIT": "abc",
    }


def test_worker_env_helper_has_no_engine_edge() -> None:
    source = (HARNESS_DIR / "worker_env.py").read_text(encoding="utf-8")
    assert not [m for m, _ in _imports(source) if m.split(".")[0] == "decoy_engine"]


@pytest.mark.parametrize("tool", ["check_determinism.py", "output_lock.py"])
def test_both_tools_use_the_shared_env_builder(tool: str) -> None:
    source = (HARNESS_DIR / tool).read_text(encoding="utf-8")
    assert ("worker_env", ("worker_env",)) in _imports(source)
    assert '"LC_ALL"' not in source, "a second copy of the worker environment"


def _load_sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"_sib_{name}", HARNESS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_engine_access_is_only_internal_import() -> None:
    assert _internal_importers(HARNESS_DIR) == ["_engine_access.py"]


@pytest.mark.parametrize("tool", _TOOLS)
def test_tools_take_engine_names_from_the_access_module(tool: str) -> None:
    source = (HARNESS_DIR / tool).read_text(encoding="utf-8")
    assert any(module == "_engine_access" for module, _ in _imports(source)), tool


@pytest.mark.parametrize(
    "line",
    [
        "from decoy_engine.internal.faker_setup import make_faker",
        "from decoy_engine.internal.faker_setup import make_faker as mk",
        "import decoy_engine.internal.faker_setup as fs",
        "import decoy_engine.internal",
        "from decoy_engine import internal",
    ],
)
def test_a_seeded_direct_internal_import_is_seen(line: str, tmp_path: Path) -> None:
    (tmp_path / "scratch.py").write_text(f"{line}\n", encoding="utf-8")
    assert _internal_importers(tmp_path) == ["scratch.py"]


def test_public_engine_imports_are_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "from decoy_engine.providers_v2 import get_default_registry\nimport decoy_engine\n",
        encoding="utf-8",
    )
    assert _internal_importers(tmp_path) == []


# ---------------------------------------------------------------------------
# FAKER-MIGRATE (AT-L21): the output-lock sentries are split by concern and stay below the size rule.
# ---------------------------------------------------------------------------

_DEPENDENCY_SENTRIES = ENGINE_ROOT / "tests" / "sentry" / "dependencies"
_LOCK_SENTRIES = (
    "test_faker_output_lock.py",
    "test_faker_output_lock_schema.py",
    "test_faker_output_lock_arguments.py",
)


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_output_lock_sentries_are_split_and_bounded() -> None:
    # The manifest is a glob (tests/sentry/**/test_*.py), so a sentry is registered by
    # existing under that glob, not by being listed by path.
    globbed = {p.name for p in (ENGINE_ROOT / "tests" / "sentry").rglob("test_*.py")}
    for name in _LOCK_SENTRIES:
        path = _DEPENDENCY_SENTRIES / name
        assert path.is_file(), name
        assert _physical_lines(path) < 600, name
        assert name in globbed, name
    assert _physical_lines(_DEPENDENCY_SENTRIES / "_faker_lock_lists.py") < 600
    support = _DEPENDENCY_SENTRIES / "_faker_output_lock_support.py"
    assert _physical_lines(support) < 250
    assert "def test_" not in support.read_text(encoding="utf-8")
