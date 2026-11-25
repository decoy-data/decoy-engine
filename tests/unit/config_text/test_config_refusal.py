"""The config refusal builder and `read_config` (F31 AE5)."""

from __future__ import annotations

import errno
import json
from pathlib import Path

import pyarrow as pa
import pytest
import yaml

from decoy_engine import fileaccess
from decoy_engine._config_text import (
    Expected,
    Kind,
    Member,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    kind_of,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.reasons import approve_name


def _pos(*segments: object) -> str:
    return config_position(*segments).key  # type: ignore[arg-type]


# ── the kind table ───────────────────────────────────────────────────────────


class _Str(str):
    def __repr__(self) -> str:
        return "PRIVATE_REPR"


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (True, Kind.BOOLEAN),
        (1, Kind.INTEGER),
        (1.5, Kind.FLOATING_POINT),
        ("x", Kind.STRING),
        ([1], Kind.LIST),
        ({"a": 1}, Kind.DICT),
        (None, Kind.NULL),
        (b"x", Kind.BINARY),
        ({1}, Kind.SET),
        (_Str("x"), Kind.OTHER),
        (object(), Kind.OTHER),
    ],
)
def test_kind_table_is_by_exact_type(value: object, kind: Kind) -> None:
    assert kind_of(value) is kind


def test_kind_of_a_date_and_a_datetime() -> None:
    import datetime

    assert kind_of(datetime.date(2024, 1, 1)) is Kind.DATE
    assert kind_of(datetime.datetime(2024, 1, 1)) is Kind.TIMESTAMP


# ── names and members ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value", ["https://user:PRIVATEPW@host/x", "/etc/PRIVATE/path", "p" * 200, "a;b", "a=b"]
)
def test_name_that_approve_name_refuses_is_a_placeholder(value: str) -> None:
    assert approve_name(value) is None
    key = _pos("cfg", Name(value))
    assert key == "cfg.<name>"


@pytest.mark.parametrize("value", [["x"], {"x": 1}, _Str("fine"), 5, None])
def test_name_with_a_non_plain_string_is_a_placeholder(value: object) -> None:
    assert _pos("cfg", Name(value)) == "cfg.<name>"


def test_an_approved_name_is_shown() -> None:
    assert _pos("cfg", Name("detector_a")) == "cfg.detector_a"


@pytest.mark.parametrize(("value", "shown"), [("../x.yaml", "x.yaml"), ("/etc/x.yaml", "x.yaml")])
def test_member_shows_the_bare_name(value: str, shown: str) -> None:
    assert _pos("pre_scan", Member(value)) == f"pre_scan/{shown}"


def test_member_with_a_non_string_is_a_placeholder() -> None:
    assert _pos("pre_scan", Member(["x"])) == "pre_scan/<file>"


def test_index_segments_render_in_brackets() -> None:
    assert _pos("files", 3, "name") == "files[3].name"


# ── builder text ─────────────────────────────────────────────────────────────


def test_text_has_position_problem_expected_got_choices_hint() -> None:
    r = config_refusal(
        config_position("a", "b"),
        Problem.WRONG_TYPE,
        expected=Expected.STRING,
        got=["PRIVATE"],
        choices=("one", "https://user:PRIVATEPW@host/x", "two"),
        hint="Fix it",
    )
    assert r.detail == "wrong type; expected a string, got list. Allowed: one, two. Fix it"
    assert r.text == f"a.b: {r.detail}"
    assert r.key == "a.b"
    assert "PRIVATE" not in r.text


def test_got_and_got_kind_together_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        config_refusal(config_position("a"), Problem.MISSING, got=1, got_kind=Kind.INTEGER)


def test_got_kind_timestamp_renders_timestamp() -> None:
    r = config_refusal(config_position("a"), Problem.WRONG_TYPE, got_kind=Kind.TIMESTAMP)
    assert r.detail == "wrong type, got timestamp"


def test_builder_never_reads_repr_or_type_name() -> None:
    r = config_refusal(config_position("a"), Problem.WRONG_TYPE, got=_Str("x"))
    assert "PRIVATE_REPR" not in r.text
    assert "_Str" not in r.text
    assert r.detail.endswith("got other")


def test_at_position_binds_the_table_and_column() -> None:
    with fileaccess.at_position("tables.orders.columns.zip"):
        r = config_refusal(config_position("joint_masks", "reference"), Problem.MISSING)
    assert r.key == "tables.orders.columns.zip.joint_masks.reference"
    assert r.text.startswith("tables.orders.columns.zip.joint_masks.reference: ")


def test_plan_compile_error_from_detail_and_key_renders_the_position_once() -> None:
    r = config_refusal(config_position("x", "y"), Problem.MISSING, expected=Expected.STRING)
    err = PlanCompileError("code_x", r.key, r.detail)
    assert str(err) == "[code_x] x.y: missing; expected a string"
    assert str(err).count("x.y") == 1


def test_refusal_is_a_frozen_value() -> None:
    r = config_refusal(config_position("a"), Problem.MISSING)
    assert isinstance(r, Refusal)
    with pytest.raises(AttributeError):
        r.text = "changed"  # type: ignore[misc]


# ── raise_bare ───────────────────────────────────────────────────────────────


def test_raise_bare_clears_the_chain_also_inside_an_outer_except() -> None:
    with pytest.raises(ValueError) as info:
        try:
            raise RuntimeError("OUTERCANARY")
        except RuntimeError as outer:
            try:
                raise KeyError("INNERCANARY") from outer
            except KeyError:
                raise_bare(ValueError("fixed"))
    err = info.value
    assert err.__cause__ is None
    assert err.__context__ is None
    assert err.__suppress_context__ is True
    assert err.__traceback__ is not None


# ── read_config ──────────────────────────────────────────────────────────────


def _refuse(r: Refusal) -> ValueError:
    return ValueError(r.text)


def _run(read, passes=()):  # type: ignore[no-untyped-def]
    return read_config(read, config_position("cfg"), _refuse, passes=passes)


def test_value_error_becomes_a_refusal_with_no_chain() -> None:
    def read() -> object:
        raise ValueError("PRIVATE_TEXT")

    with pytest.raises(ValueError) as info:
        _run(read)
    assert str(info.value) == "cfg: could not be parsed"
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_os_error_becomes_an_unreadable_refusal() -> None:
    def read() -> object:
        raise OSError(errno.EIO, "PRIVATE_TEXT", "PRIVATE_FILE")

    with pytest.raises(ValueError) as info:
        _run(read)
    assert str(info.value) == "cfg: could not be read"


def test_yaml_error_keeps_only_line_and_column() -> None:
    with pytest.raises(ValueError) as info:
        _run(lambda: yaml.safe_load("a: [unclosed\nPRIVATE_LINE"))
    text = str(info.value)
    assert text.startswith("cfg: could not be parsed at line ")
    assert "PRIVATE_LINE" not in text


def test_json_error_keeps_only_line_and_column() -> None:
    with pytest.raises(ValueError) as info:
        _run(lambda: json.loads('{"a": PRIVATE_TOKEN}'))
    assert str(info.value) == "cfg: could not be parsed at line 1, column 7"


def test_a_failure_while_materializing_is_a_refusal() -> None:
    class Cell:
        def as_py(self) -> object:
            raise RuntimeError("Unknown zone PRIVATE_ZONE")

    with pytest.raises(ValueError) as info:
        _run(lambda: Cell().as_py())
    assert "PRIVATE_ZONE" not in str(info.value)


def test_the_handle_is_closed_after_a_parse_refusal() -> None:
    closed: list[bool] = []

    class Handle:
        def close(self) -> None:
            closed.append(True)

    handle = Handle()
    try:
        _run(lambda: yaml.safe_load("a: [unclosed"))
    except ValueError:
        pass
    finally:
        handle.close()
    assert closed == [True]


@pytest.mark.parametrize("strict", [False, True])
def test_explicit_route_errors_pass_by_identity(tmp_path: Path, strict: bool) -> None:
    injected = fileaccess.FileAccessReadError("field")

    def read() -> object:
        raise injected

    from tests.fileaccess.support import RootRelative

    root = tmp_path / "root"
    root.mkdir()
    policy = RootRelative(root) if strict else None
    try:
        import contextlib

        with fileaccess.scope(policy) if policy else contextlib.nullcontext():
            with pytest.raises(fileaccess.FileAccessReadError) as info:
                _run(read, passes=(fileaccess.FileAccessReadError,))
    finally:
        if policy:
            policy.close()
    assert info.value is injected


def test_ambient_builtin_memory_error_passes_unchanged() -> None:
    injected = MemoryError("PRIVATE_TEXT")

    def read() -> object:
        raise injected

    with pytest.raises(MemoryError) as info:
        _run(read)
    assert info.value is injected


def test_ambient_disk_error_becomes_a_refusal() -> None:
    def read() -> object:
        raise OSError(errno.ENOSPC, "No space", "PRIVATE_FILE")

    with pytest.raises(ValueError) as info:
        _run(read)
    assert "PRIVATE_FILE" not in str(info.value)


def test_strict_policy_errors_and_resource_failures(tmp_path: Path) -> None:
    from tests.fileaccess.support import RootRelative

    root = tmp_path / "root"
    root.mkdir()
    policy = RootRelative(root)
    denial = fileaccess.FileAccessDenied("field")

    def deny() -> object:
        raise denial

    def full() -> object:
        raise OSError(errno.ENOSPC, "No space", "PRIVATE_FILE")

    def memory() -> object:
        raise pa.ArrowException("Unknown error: Wrapping PRIVATE_CELL failed")

    try:
        with fileaccess.scope(policy):
            with pytest.raises(fileaccess.FileAccessDenied) as d:
                _run(deny)
            with pytest.raises(OSError) as o:
                _run(full)
            with pytest.raises(pa.ArrowException) as m:
                _run(memory)
    finally:
        policy.close()
    assert d.value is denial
    assert o.value.errno == errno.ENOSPC and o.value.filename is None
    assert fileaccess.is_memory_failure(m.value)
    assert str(m.value) == fileaccess.MEMORY_TEXT
    assert m.value.__cause__ is None and m.value.__context__ is None


def test_recognized_memory_failure_whose_constructor_rejects_the_text(tmp_path: Path) -> None:
    from tests.fileaccess.support import RootRelative

    class PickyError(Exception):
        def __init__(self, a: object, b: object) -> None:
            super().__init__(a, b)

    root = tmp_path / "root"
    root.mkdir()
    policy = RootRelative(root)

    def read() -> object:
        raise PickyError("Unknown error: Wrapping PRIVATE_CELL failed", 1)

    try:
        with fileaccess.scope(policy):
            with pytest.raises(MemoryError) as info:
                _run(read)
    finally:
        policy.close()
    assert fileaccess.is_memory_failure(info.value)
    assert "PRIVATE_CELL" not in "".join(map(str, [info.value, info.value.args]))
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_yaml_error_text_has_one_owner_and_safe_output_re_exports_it() -> None:
    from decoy_engine import _config_text, safe_output

    assert safe_output.yaml_error_text is _config_text.yaml_error_text
