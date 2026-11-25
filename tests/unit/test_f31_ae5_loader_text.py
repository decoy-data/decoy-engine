"""F31 AE5 round 2: loader and validator errors carry no config or data value.

Each test plants a distinctive literal in a config, a Parquet schema, a lockfile or an artifact,
then asserts the literal never reaches the raised text. The model-pack canaries sit in
`tests/unit/test_ml_model_pack.py` beside the pack-building helper they need.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import fileaccess
from decoy_engine.detection.name_hints.loader import NameHintLoaderError, load_name_hint_terms
from decoy_engine.generation.statistical import StatisticalSpecError, load_spec
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.quality import dp_provenance as prov
from decoy_engine.quality.dp_provenance import ProvenanceError, validate_recorded_provenance
from decoy_engine.quality.snapshot import compute_distribution_snapshot
from decoy_engine.reference_tables._loader import load_table
from decoy_engine.transforms._codeset_loader import _check_source_version_pin
from decoy_engine.transforms.joint_mask import validate_joint_mask_config

_SECRET = "DEMO_PRIVATE_ZONE"


def _tz_id_table(tmp_path: Path) -> Path:
    path = tmp_path / "ref.parquet"
    ids = pa.array([1], pa.timestamp("ns", tz=_SECRET))
    pq.write_table(pa.table({"id": ids, "city": ["x"]}), path)
    return path


def _joint_cfg(reference: str) -> dict[str, object]:
    return {"columns": ["city"], "reference": reference, "key_by": "k"}


# ── item 1: joint-mask reference ─────────────────────────────────────────────


def test_reference_id_type_names_the_kind_not_the_timezone(tmp_path: Path) -> None:
    path = _tz_id_table(tmp_path)
    with pytest.raises(ValueError) as exc:
        load_table(f"customer:{path}")
    assert _SECRET not in str(exc.value)
    assert "'id' column" in str(exc.value)
    assert "timestamp" in str(exc.value)


def test_joint_mask_invalid_reference_does_not_copy_the_loader_text(tmp_path: Path) -> None:
    path = _tz_id_table(tmp_path)
    with pytest.raises(PlanCompileError) as exc:
        validate_joint_mask_config(_joint_cfg(f"customer:{path}"))
    assert exc.value.code == "joint_mask_reference_invalid"
    assert _SECRET not in str(exc.value)
    assert "timestamp" not in str(exc.value)


def test_unknown_shipped_name_is_not_echoed_under_the_ambient_policy() -> None:
    name = "https://user:PRIVATE_TOKEN@example.invalid/ref.parquet"
    with pytest.raises(FileNotFoundError) as exc:
        load_table(name)
    assert "PRIVATE_TOKEN" not in str(exc.value)
    assert "no shipped reference table" in str(exc.value)


@pytest.mark.parametrize(
    ("reference", "code"),
    [
        ("no_such_shipped_table", "joint_mask_reference_not_found"),
        ("customer:{tz}", "joint_mask_reference_invalid"),
    ],
)
def test_joint_mask_reference_refusal_binds_table_and_column(
    tmp_path: Path, reference: str, code: str
) -> None:
    ref = reference.format(tz=_tz_id_table(tmp_path))
    with fileaccess.at_position("tables.orders.columns.zip"):
        with pytest.raises(PlanCompileError) as exc:
            validate_joint_mask_config(_joint_cfg(ref))
    assert exc.value.code == code
    assert exc.value.path == "tables.orders.columns.zip.joint_masks.reference"


# ── item 2: code-set version pin ─────────────────────────────────────────────


def test_code_set_version_pin_names_the_field_not_the_values() -> None:
    record = SimpleNamespace(provenance=SimpleNamespace(source_version="ACTUAL_PRIVATE_URL"))
    with pytest.raises(PlanCompileError) as exc:
        _check_source_version_pin("icd10", None, record, "PINNED_PRIVATE_URL")  # type: ignore[arg-type]
    text = str(exc.value)
    assert "ACTUAL_PRIVATE_URL" not in text
    assert "PINNED_PRIVATE_URL" not in text
    assert "corpus_source_version" in text


# ── item 4: DP provenance ────────────────────────────────────────────────────


def test_dp_lock_drift_names_distributions_without_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        prov, "installed_distribution_set", lambda: (("foo", "9.9.PRIVATE"), ("bar", "7.7"))
    )
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "foo"\nversion = "1.1.LOCKPRIVATE"\n', encoding="utf-8")
    with pytest.raises(ProvenanceError) as exc:
        prov.assert_lock_matches_installed(lock_path=lock)
    text = str(exc.value)
    assert "PRIVATE" not in text
    assert "7.7" not in text
    assert "foo" in text
    assert "bar" in text


@pytest.mark.parametrize(
    "recorded",
    [
        {
            "platform": ("Linux", "PRIVATE_MACHINE", "CPython", "glibc"),
            "cpython": "3.12",
            "fingerprint": "f",
        },
        {
            "platform": tuple(prov.CERTIFIED_PLATFORM),
            "cpython": "PRIVATE_CPY",
            "fingerprint": "PRIVATE_FP",
        },
    ],
)
def test_recorded_provenance_refusal_omits_recorded_values(recorded: dict[str, object]) -> None:
    with pytest.raises(ProvenanceError) as exc:
        validate_recorded_provenance(recorded)
    assert "PRIVATE" not in str(exc.value)


# ── item 5: other loader errors ──────────────────────────────────────────────


def _name_hint_dir(tmp_path: Path, detector_body: str) -> Path:
    root = tmp_path / "PRIVATE_DIR"
    root.mkdir()
    (root / "manifest.yaml").write_text("files:\n  - bad.yaml\n", encoding="utf-8")
    (root / "bad.yaml").write_text(detector_body, encoding="utf-8")
    return root


def test_name_hint_non_string_pattern_is_named_by_type(tmp_path: Path) -> None:
    root = _name_hint_dir(
        tmp_path, "detectors:\n  - detector_id: foo\n    patterns: [{PRIVATE_KEY: v}]\n"
    )
    with pytest.raises(NameHintLoaderError) as exc:
        load_name_hint_terms(root)
    text = str(exc.value).replace(str(root), "<dir>")
    assert "PRIVATE_KEY" not in text
    assert "dict" in text


def test_name_hint_yaml_parse_error_omits_the_directory(tmp_path: Path) -> None:
    root = _name_hint_dir(tmp_path, "detectors: [unclosed\n")
    with pytest.raises(NameHintLoaderError) as exc:
        load_name_hint_terms(root)
    assert "PRIVATE_DIR" not in str(exc.value)
    assert "bad.yaml" in str(exc.value)
    assert "could not parse YAML" in str(exc.value)


def test_statistical_unknown_snapshot_kind_is_not_echoed() -> None:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": [1, 2, 3]}))
    snap["columns"]["a"]["kind"] = "PRIVATE_KIND"
    col = {"name": "a", "type": "statistical", "snapshot_file": "s.json"}
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec(col, snapshot=json.loads(json.dumps(snap)))
    assert exc.value.code == "statistical_kind_unsupported"
    assert "PRIVATE_KIND" not in str(exc.value)


# ── should-fix: one text-mask fail-closed builder ────────────────────────────


def test_text_mask_fail_closed_text_is_written_once() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
    hits = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "a text span is outside the FPE domain" in p.read_text(encoding="utf-8")
    ]
    assert hits == ["execution/_errors.py"]


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ([1, 2, 3], {"high_cardinality": "PRIVATE_FLAG"}),
        ([1, 2, 3], {"allow_real_categories": "PRIVATE_FLAG"}),
        (["x", "y", "z"], {"other_mode": "PRIVATE_MODE"}),
    ],
)
def test_statistical_config_values_are_not_echoed(
    values: list[object], field: dict[str, object]
) -> None:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": values}))
    col = {"name": "a", "type": "statistical", "snapshot_file": "s.json", **field}
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec(col, snapshot=json.loads(json.dumps(snap)))
    assert "PRIVATE" not in str(exc.value)
