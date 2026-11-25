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

import decoy_engine
from decoy_engine import fileaccess
from decoy_engine.detection.name_hints.loader import NameHintLoaderError, load_name_hint_terms
from decoy_engine.generation.statistical import StatisticalSpecError, load_spec
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.quality import dp_provenance as prov
from decoy_engine.quality.dp_provenance import ProvenanceError, validate_recorded_provenance
from decoy_engine.quality.snapshot import compute_distribution_snapshot
from decoy_engine.reference_tables._loader import load_table
from decoy_engine.transforms._codeset_loader import _check_source_version_pin
from decoy_engine.transforms.joint_mask import apply_joint_mask, validate_joint_mask_config

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
    assert "got timestamp" in str(exc.value)


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
    text = str(exc.value)
    assert "PRIVATE_KEY" not in text
    assert "dict" in text


def test_name_hint_yaml_parse_error_omits_the_directory(tmp_path: Path) -> None:
    root = _name_hint_dir(tmp_path, "detectors: [unclosed\n")
    with pytest.raises(NameHintLoaderError) as exc:
        load_name_hint_terms(root)
    assert "PRIVATE_DIR" not in str(exc.value)
    assert "bad.yaml" in str(exc.value)
    assert "could not be parsed at line" in str(exc.value)


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
    src = Path(decoy_engine.__file__).parent
    # A wrong root would scan nothing and pass, so the scanned tree must hold the new package.
    assert (src / "_config_text" / "__init__.py").is_file()
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
        # Real categories opted in, so the load reaches the other_mode check.
        (["x", "y", "z"], {"other_mode": "PRIVATE_MODE", "allow_real_categories": True}),
    ],
)
def test_statistical_config_values_are_not_echoed(
    values: list[object], field: dict[str, object]
) -> None:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": values}))
    col = {"name": "a", "type": "statistical", "snapshot_file": "s.json", **field}
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec(col, snapshot=json.loads(json.dumps(snap)))
    assert "real_categories_not_allowed" not in exc.value.code
    assert "PRIVATE" not in str(exc.value)


def test_joint_mask_unsupported_mode_is_not_echoed() -> None:
    with pytest.raises(ValueError) as exc:
        apply_joint_mask(
            pd.DataFrame({"k": [1]}),
            None,  # type: ignore[arg-type]
            mode="PRIVATE_MODE",
            job_seed=b"\x00" * 32,
            table="t",
        )
    assert "unsupported mode" in str(exc.value)
    assert "PRIVATE_MODE" not in str(exc.value)


def test_dp_duplicate_install_omits_both_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    dists = [
        SimpleNamespace(metadata={"Name": "foo"}, version=v)
        for v in ("1.0.PRIVATE_A", "2.0.PRIVATE_B")
    ]
    monkeypatch.setattr(prov.importlib.metadata, "distributions", lambda: dists)
    with pytest.raises(ProvenanceError) as exc:
        prov.installed_distribution_set()
    assert exc.value.code == "dp_provenance_duplicate_distribution"
    assert "PRIVATE" not in str(exc.value)


# ── F31 AE5 amendment: acceptance tests A1-A10 ───────────────────────────────


def _surfaces(exc: BaseException) -> list[str]:
    """Every string a reader of `exc` can see, on the unmodified exception."""
    out = [str(exc), repr(exc), *(str(a) for a in exc.args)]
    out += [v for v in vars(exc).values() if isinstance(v, str)]
    return out


def _assert_value_free(exc: BaseException, *canaries: str) -> None:
    for surface in _surfaces(exc):
        for canary in canaries:
            assert canary not in surface
    assert exc.__cause__ is None
    assert exc.__context__ is None


def _hint_dir(root: Path, body: str, *, manifest: str = "files:\n  - bad.yaml\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(manifest, encoding="utf-8")
    (root / "bad.yaml").write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize("tag", ["!!int", "!!float", "!!timestamp"])
def test_yaml_scalar_conversion_error_is_value_free(tmp_path: Path, tag: str) -> None:
    root = _hint_dir(tmp_path / "hints", f"x: {tag} PRIVATEMARKER\n")
    with pytest.raises(NameHintLoaderError) as exc:
        load_name_hint_terms(root)
    _assert_value_free(exc.value, "PRIVATEMARKER")
    # The constructor `ValueError` has no YAML mark, so there is no line or column.
    assert str(exc.value) == "pre_scan.name_hints/bad.yaml: could not be parsed"


def test_yaml_syntax_error_keeps_line_and_column(tmp_path: Path) -> None:
    root = _hint_dir(tmp_path / "hints", "detectors: [unclosed\n")
    with pytest.raises(NameHintLoaderError) as exc:
        load_name_hint_terms(root)
    assert str(exc.value).startswith("pre_scan.name_hints/bad.yaml: could not be parsed at line ")
    assert ", column " in str(exc.value)


def _strict_policy(root: Path):  # type: ignore[no-untyped-def]
    from tests.fileaccess.support import RootRelative

    return RootRelative(root)


def test_name_hint_validation_omits_the_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    folder = _hint_dir(
        root / "PRIVATE_CANARY_DIR", "detectors:\n  - detector_id: foo\n    patterns: {k: v}\n"
    )
    with pytest.raises(NameHintLoaderError) as ambient:
        load_name_hint_terms(folder)
    policy = _strict_policy(root)
    try:
        with fileaccess.scope(policy), pytest.raises(NameHintLoaderError) as strict:
            load_name_hint_terms(folder, file_access=policy)
    finally:
        policy.close()
    for exc in (ambient.value, strict.value):
        _assert_value_free(exc, "PRIVATE_CANARY_DIR", str(root))
        text = str(exc)
        assert text.startswith("pre_scan.name_hints/bad.yaml.")
        assert "list" in text
        assert "dict" in text


def test_code_set_list_pin_is_value_free() -> None:
    from decoy_engine.transforms.code_set import CodeSetConfig

    with pytest.raises(PlanCompileError) as exc:
        CodeSetConfig.from_dict({"code_set": "icd10", "corpus_source_version": ["PRIVATE_RELEASE"]})
    _assert_value_free(exc.value, "PRIVATE_RELEASE")
    text = str(exc.value)
    assert "corpus_source_version" in text
    assert "release id" in text
    assert "got list" in text


def test_code_set_url_corpus_is_value_free() -> None:
    from decoy_engine.transforms._codeset_provenance import CODESET_REGISTRY
    from decoy_engine.transforms.code_set import CodeSetConfig

    with pytest.raises(PlanCompileError) as exc:
        CodeSetConfig.from_dict({"code_set": "https://user:PRIVATEPW@host/x"})
    _assert_value_free(exc.value, "PRIVATEPW", "user:", "host")
    for name in CODESET_REGISTRY:
        assert name in str(exc.value)


def test_joint_mask_missing_reference_binds_the_position() -> None:
    cfg = {"columns": ["city"], "key_by": "k"}
    with fileaccess.at_position("tables.orders.columns.zip"):
        with pytest.raises(PlanCompileError) as exc:
            validate_joint_mask_config(cfg)
    path = "tables.orders.columns.zip.joint_masks.reference"
    assert exc.value.path == path
    assert exc.value.message == "missing; expected a shipped or customer-provided reference table"
    # The stock render prints the path once.
    assert str(exc.value) == f"[{exc.value.code}] {path}: {exc.value.message}"


def test_loader_refusals_have_no_chain(tmp_path: Path) -> None:
    syntax = _hint_dir(tmp_path / "a", "detectors: [unclosed\n")
    scalar = _hint_dir(tmp_path / "b", "x: !!int PRIVATEMARKER\n")
    unlisted = _hint_dir(tmp_path / "c", "detectors: []\n", manifest="files:\n  - ghost.yaml\n")
    cases = [
        (NameHintLoaderError, lambda: load_name_hint_terms(syntax)),
        (NameHintLoaderError, lambda: load_name_hint_terms(scalar)),
        (NameHintLoaderError, lambda: load_name_hint_terms(unlisted)),
        (PlanCompileError, lambda: validate_joint_mask_config(_joint_cfg("no_such_shipped_table"))),
    ]
    for error, call in cases:
        with pytest.raises(error) as plain:
            call()
        assert plain.value.__cause__ is None and plain.value.__context__ is None
        assert plain.value.__suppress_context__ is True
        # An outer exception being handled must not become the context (Dennis V1-3).
        with pytest.raises(error) as outer:
            try:
                raise RuntimeError("OUTERCANARY")
            except RuntimeError:
                call()
        assert outer.value.__context__ is None
        assert "OUTERCANARY" not in "".join(_surfaces(outer.value))


# A7 lives in tests/unit/reference_tables/test_type_kinds.py.


def _tz_corpus(path: Path, *, with_code: bool) -> Path:
    import datetime

    stamp = pa.array([datetime.datetime(2024, 1, 1)], pa.timestamp("us", tz="PRIVATE_ZONE_CANARY"))
    cols: dict[str, object] = {"ts": stamp}
    if with_code:
        cols["code"] = pa.array(["A1"], pa.string())
    else:
        cols["other"] = pa.array([1], pa.int64())
    pq.write_table(pa.table(cols), path)
    return path


@pytest.mark.parametrize("strict", [False, True])
def test_corpus_materialization_is_value_free(tmp_path: Path, strict: bool) -> None:
    from decoy_engine.transforms._codeset_loader import load_corpus, verify_corpus

    root = tmp_path / "root"
    root.mkdir()
    ok = _tz_corpus(root / "tz.parquet", with_code=True)
    nocode = _tz_corpus(root / "nocode.parquet", with_code=False)
    policy = _strict_policy(root) if strict else None
    try:
        with fileaccess.scope(policy) if policy else _null():
            with pytest.raises(PlanCompileError) as raised:
                load_corpus("mine", ok)
            report = verify_corpus(ok)
            with pytest.raises(PlanCompileError) as missing:
                load_corpus("mine", nocode)
            missing_report = verify_corpus(nocode)
    finally:
        if policy:
            policy.close()
    assert raised.value.code == "code_set_corpus_read_error"
    _assert_value_free(raised.value, "PRIVATE_ZONE_CANARY")
    assert report.ok is False
    assert report.problems and report.problems[0].startswith("code_set_corpus_read_error: ")
    assert "PRIVATE_ZONE_CANARY" not in "".join(report.problems)
    # A corpus without `code` is refused on its own fault, before the unrelated cell converts.
    assert missing.value.code == "code_set_corpus_missing_code_column"
    assert missing_report.ok is False
    assert missing_report.problems[0].startswith("code_set_corpus_missing_code_column: ")
    assert "'code' string column" in missing_report.problems[0]
    # A `PlanCompileError` prints its `path` itself, so the message must not repeat the position.
    assert not missing.value.message.startswith(missing.value.path)
    assert "PRIVATE_ZONE_CANARY" not in "".join(missing_report.problems)


def _null():  # type: ignore[no-untyped-def]
    import contextlib

    return contextlib.nullcontext()


def _stat_snapshot(values: list[object]) -> dict[str, object]:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": values}))
    return json.loads(json.dumps(snap))


def test_list_valued_name_is_not_shown() -> None:
    from decoy_engine.reasons import approve_name

    snap = _stat_snapshot(["x", "y", "z"])
    # Proves the test depends on the type check, not on `approve_name`.
    assert approve_name(str(["PRIVATE_RELEASE"])) is not None
    col = {
        "name": "a",
        "type": "statistical",
        "snapshot_file": "s.json",
        "allow_real_categories": True,
    }
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec({**col, "source_column": ["PRIVATE_RELEASE"]}, snapshot=snap)
    assert exc.value.code == "statistical_column_not_in_snapshot"
    _assert_value_free(exc.value, "PRIVATE_RELEASE")
    assert "wrong type" in str(exc.value)
    assert "got list" in str(exc.value)
    # A valid string source column is still shown.
    with pytest.raises(StatisticalSpecError) as named:
        load_spec({**col, "source_column": "ghost_col"}, snapshot=snap)
    assert "ghost_col" in str(named.value)


def test_list_valued_condition_on_is_not_shown() -> None:
    snap = _stat_snapshot(["x", "y", "z"])
    col = {
        "name": "a",
        "type": "statistical",
        "snapshot_file": "s.json",
        "allow_real_categories": True,
    }
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec({**col, "condition_on": ["PRIVATE_RELEASE"]}, snapshot=snap)
    assert exc.value.code == "statistical_joint_missing"
    _assert_value_free(exc.value, "PRIVATE_RELEASE")
    assert "condition_on" in str(exc.value)
    assert "wrong type" in str(exc.value)
    assert "got list" in str(exc.value)
    # None still selects the unconditional path.
    assert load_spec({**col, "condition_on": None}, snapshot=snap).condition_on is None


def test_approved_condition_on_still_resolves_a_joint() -> None:
    frame = pd.DataFrame({"p": ["a", "b", "a", "b"], "a": ["x", "y", "x", "y"]})
    snap = json.loads(json.dumps(compute_distribution_snapshot(frame, joint_columns=[("p", "a")])))
    col = {
        "name": "a",
        "type": "statistical",
        "snapshot_file": "s.json",
        "allow_real_categories": True,
        "condition_on": "p",
    }
    assert load_spec(col, snapshot=snap).condition_on == "p"


def _read_error(code: str = "FileAccessReadError"):  # type: ignore[no-untyped-def]
    return fileaccess.FileAccessReadError("tables.t.columns.c")


def _ref_parquet(root: Path) -> Path:
    path = root / "ref.parquet"
    pq.write_table(pa.table({"id": pa.array([1], pa.int64()), "city": ["x"]}), path)
    return path


@pytest.mark.parametrize("strict", [False, True])
def test_load_table_passes_typed_file_access_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strict: bool
) -> None:
    from decoy_engine.reference_tables import _loader

    root = tmp_path / "root"
    root.mkdir()
    path = _ref_parquet(root)
    injected = fileaccess.FileAccessReadError("tables.t.columns.c")

    def boom(handle: object) -> object:
        raise injected

    monkeypatch.setattr(_loader.arrow_adapter, "read_table", boom)
    policy = _strict_policy(root) if strict else None
    try:
        with fileaccess.scope(policy) if policy else _null():
            with pytest.raises(fileaccess.FileAccessReadError) as info:
                load_table(f"customer:{path}")
    finally:
        if policy:
            policy.close()
    assert info.value is injected


def test_resource_failures_by_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import errno

    from decoy_engine.plan import _generation
    from decoy_engine.reference_tables import _loader

    root = tmp_path / "root"
    root.mkdir()
    path = _ref_parquet(root)

    def full_disk(*_a: object, **_k: object) -> object:
        raise OSError(errno.ENOSPC, "No space left on device", "PRIVATE_FILENAME")

    monkeypatch.setattr(_loader.arrow_adapter, "read_table", full_disk)
    monkeypatch.setattr(_generation.fileaccess, "read_all", full_disk)
    # Ambient: each route gives its own refusal.
    with pytest.raises(ValueError) as ambient:
        load_table(f"customer:{path}")
    _assert_value_free(ambient.value, "PRIVATE_FILENAME")
    pinned = _generation.read_pinned_artifact(
        fileaccess.FileRole.SNAPSHOT, "s.json", "snapshot_file", None, 1024
    )
    assert pinned.raw is None and pinned.cause_type
    # Strict: the errno survives, the filename does not.
    policy = _strict_policy(root)
    try:
        with fileaccess.scope(policy):
            with pytest.raises(OSError) as table_exc:
                load_table(f"customer:{path}")
            with pytest.raises(OSError) as pin_exc:
                _generation.read_pinned_artifact(
                    fileaccess.FileRole.SNAPSHOT, "s.json", "snapshot_file", None, 1024
                )
    finally:
        policy.close()
    for raised in (table_exc.value, pin_exc.value):
        assert raised.errno == errno.ENOSPC
        assert raised.filename is None
        assert "PRIVATE_FILENAME" not in "".join(_surfaces(raised))


def test_strict_materialization_failures_keep_class_and_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from decoy_engine.transforms import _codeset_loader

    root = tmp_path / "root"
    root.mkdir()
    corpus = root / "c.parquet"
    pq.write_table(pa.table({"code": pa.array(["A1"], pa.string())}), corpus)

    class Cell:
        def __init__(self, error: BaseException) -> None:
            self.error = error

        def as_py(self) -> object:
            raise self.error

    class Column:
        """The real column, except that reading one cell raises."""

        def __init__(self, real: object, error: BaseException) -> None:
            self.real = real
            self.error = error

        def __getattr__(self, attr: str) -> object:
            return getattr(self.real, attr)

        def __getitem__(self, _i: int) -> Cell:
            return Cell(self.error)

    real_read = _codeset_loader.arrow_adapter.read_table

    def tabled(error: BaseException):  # type: ignore[no-untyped-def]
        def read(handle: object) -> object:
            table = real_read(handle)  # type: ignore[arg-type]

            class Wrapped:
                schema = table.schema
                num_rows = table.num_rows

                def column(self, name: str) -> object:
                    return Column(table.column(name), error)

            return Wrapped()

        return read

    policy = _strict_policy(root)
    try:
        with fileaccess.scope(policy):
            memory = pa.ArrowException("Unknown error: Wrapping PRIVATE_CELL failed")
            monkeypatch.setattr(_codeset_loader.arrow_adapter, "read_table", tabled(memory))
            with pytest.raises(pa.ArrowException) as mem:
                _codeset_loader.load_corpus("mine", corpus)
            disk = OSError(errno.ENOSPC, "No space left on device", "PRIVATE_FILENAME")
            monkeypatch.setattr(_codeset_loader.arrow_adapter, "read_table", tabled(disk))
            with pytest.raises(OSError) as full:
                _codeset_loader._read_corpus_record("mine", corpus, is_shipped=False)
    finally:
        policy.close()
    assert type(mem.value) is type(memory)
    assert fileaccess.is_memory_failure(mem.value)
    assert str(mem.value) == fileaccess.MEMORY_TEXT
    _assert_value_free(mem.value, "PRIVATE_CELL")
    assert full.value.errno == errno.ENOSPC
    assert full.value.filename is None
    assert "PRIVATE_FILENAME" not in "".join(_surfaces(full.value))
