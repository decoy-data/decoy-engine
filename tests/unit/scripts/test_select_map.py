"""The impact map reader, the shared fingerprint and the atomic writer (ENGINE-SELECT S1).

A map the reader cannot trust must never narrow a selection, so every cell here feeds the reader
one defect and expects a refusal with a fixed token (the selector turns that into D8 and legacy)."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any

import pytest
from scripts.dev.impact_select import _select_env, _select_map
from scripts.dev.impact_select._atomic_write import atomic_write_bytes
from scripts.dev.impact_select._select_map import ImpactMap, MapRejectedError, dump_map, load_map

SHA = "0123456789abcdef0123456789abcdef01234567"


def _fp() -> dict[str, Any]:
    return {
        "platform": "linux-x86_64",
        "python": "3.12",
        "uv_lock_sha256": "a" * 64,
        "dists_sha256": "b" * 64,
        "companion": "absent",
        "env": {"DECOY_REQUIRE_PG": {"set": False, "sha256": ""}},
    }


def _doc() -> dict[str, Any]:
    return {
        "format_version": 1,
        "repo": "decoy-engine",
        "map_sha": SHA,
        "fingerprint": _fp(),
        "built_at": "2026-11-26T00:00:00+00:00",
        "tests": ["tests/a.py", "tests/b.py"],
        "paths": ["src/x.py", "src"],
        "outcomes": ["passed", "skipped_some"],
        "skips": {"1": {"ids": [], "unclassified": True}},
        "executors": {"src/x.py": {"f": [0, 1], "<module>": [0]}},
        "reads": {"0": [0]},
        "lists": {"1": [1]},
    }


def _write(tmp_path: Path, doc: object, *, raw: bytes | None = None) -> Path:
    dest = tmp_path / "impact-map.json.gz"
    dest.write_bytes(gzip.compress(raw if raw is not None else json.dumps(doc).encode()))
    return dest


def _reason(path: Path) -> str:
    with pytest.raises(MapRejectedError) as info:
        load_map(path)
    exc = info.value
    # Class 3: the token is all a rejected map reveals; no cause or context can carry a path.
    assert exc.__cause__ is None and exc.__context__ is None
    assert exc.reason in _select_map.REASONS
    return exc.reason


def test_a_valid_map_round_trips_through_the_one_writer_model(tmp_path: Path) -> None:
    dest = tmp_path / "m.json.gz"
    original = ImpactMap(
        repo="decoy-engine", map_sha=SHA, fingerprint=_fp(), built_at="t",
        tests=["tests/a.py", "tests/b.py"], paths=["src/x.py"], outcomes=["passed", "skipped_some"],
        skips={1: (["id1"], False)}, executors={"src/x.py": {"f": [0, 1]}},
        reads={0: [0]}, lists={1: [0]},
    )  # fmt: skip
    dump_map(original, dest)
    assert load_map(dest) == original
    twin = tmp_path / "m2.json.gz"
    dump_map(original, twin)
    assert dest.read_bytes() == twin.read_bytes()  # the bytes are a pure function of the map


def test_unknown_extra_keys_are_ignored(tmp_path: Path) -> None:
    doc = _doc() | {"future_field": {"x": 1}}
    assert load_map(_write(tmp_path, doc)).map_sha == SHA


@pytest.mark.parametrize("what", ["missing", "not_gzip", "not_json", "truncated"])
def test_unreadable_maps_are_refused(tmp_path: Path, what: str) -> None:
    dest = tmp_path / "m.json.gz"
    if what == "not_gzip":
        dest.write_bytes(b'{"format_version": 1}')
    elif what == "not_json":
        dest = _write(tmp_path, None, raw=b"not json{")
    elif what == "truncated":
        dest.write_bytes(gzip.compress(json.dumps(_doc()).encode())[:-12])
    expected = {"missing": "missing", "not_json": "not_json"}.get(what, "unreadable")
    assert _reason(dest) == expected


def test_a_next_major_or_missing_version_is_refused(tmp_path: Path) -> None:
    assert _reason(_write(tmp_path, _doc() | {"format_version": 2})) == "bad_version"
    doc = _doc()
    del doc["format_version"]
    assert _reason(_write(tmp_path, doc)) == "bad_shape"
    assert _reason(_write(tmp_path, _doc() | {"format_version": True})) == "bad_shape"


@pytest.mark.parametrize("key", ["repo", "map_sha", "fingerprint", "built_at", "tests", "paths",
                                 "outcomes", "skips", "executors", "reads", "lists"])  # fmt: skip
def test_every_required_key_is_required(tmp_path: Path, key: str) -> None:
    doc = _doc()
    del doc[key]
    assert _reason(_write(tmp_path, doc)) == "bad_shape"


def test_the_fingerprint_must_carry_every_field(tmp_path: Path) -> None:
    for field in _select_env.REQUIRED_KEYS:
        doc = _doc()
        del doc["fingerprint"][field]
        assert _reason(_write(tmp_path, doc)) == "bad_shape"
    doc = _doc()
    doc["fingerprint"]["env"]["DECOY_REQUIRE_PG"]["set"] = "yes"
    assert _reason(_write(tmp_path, doc)) == "bad_shape"


@pytest.mark.parametrize("sha", [SHA + "\n", SHA.upper(), SHA[:-1], "g" * 40, 5])
def test_map_sha_is_anchored_lowercase_hex(tmp_path: Path, sha: object) -> None:
    assert _reason(_write(tmp_path, _doc() | {"map_sha": sha})) == "bad_shape"


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("executors", {"src/x.py": {"f": [0, 2]}}),
        ("executors", {"src/x.py": {"f": [-1]}}),
        ("reads", {"0": [5]}),
        ("reads", {"7": [0]}),
        ("lists", {"1": [-1]}),
        ("skips", {"9": {"ids": [], "unclassified": False}}),
    ],
)
def test_an_index_out_of_range_is_refused_not_clamped(
    tmp_path: Path, section: str, value: object
) -> None:
    assert _reason(_write(tmp_path, _doc() | {section: value})) == "bad_index"


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("executors", {"src/x.py": {"f": ["0"]}}),  # a string where an index belongs
        ("executors", {"src/x.py": {"f": [True]}}),  # a bool is not an index
        ("executors", {"src/x.py": ["f"]}),
        ("reads", {"zero": [0]}),
        ("reads", {"-1": [0]}),
        ("lists", {"1": "0"}),
        ("skips", {"1": {"ids": "id", "unclassified": True}}),
        ("skips", {"1": {"ids": [], "unclassified": "no"}}),
        ("tests", ["tests/a.py", 3]),
        ("outcomes", ["passed", "exploded"]),
    ],
)
def test_map_types_are_checked(tmp_path: Path, section: str, value: object) -> None:
    assert _reason(_write(tmp_path, _doc() | {section: value})) in {"bad_shape", "bad_index"}


def test_outcomes_must_line_up_with_tests(tmp_path: Path) -> None:
    assert _reason(_write(tmp_path, _doc() | {"outcomes": ["passed"]})) == "bad_index"


def test_an_oversized_map_is_refused_before_it_is_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = _write(tmp_path, _doc())
    monkeypatch.setattr(_select_map, "MAX_UNCOMPRESSED_BYTES", 100)
    assert _reason(dest) == "too_big"


def test_the_map_is_opened_once_per_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = _write(tmp_path, _doc())
    opened: list[object] = []
    real = gzip.open

    def counting(*a: Any, **k: Any) -> Any:
        opened.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(_select_map.gzip, "open", counting)
    load_map(dest)
    assert opened == [dest]


def test_a_bad_map_does_not_echo_its_path_or_text(tmp_path: Path) -> None:
    secret = tmp_path / "canary-dir-name"
    secret.mkdir()
    dest = secret / "m.json.gz"
    dest.write_bytes(gzip.compress(b'{"canary-key": '))
    with pytest.raises(MapRejectedError) as info:
        load_map(dest)
    assert "canary" not in str(info.value) and str(dest) not in repr(info.value)


# ---- fingerprint ---------------------------------------------------------------------------


def test_fingerprint_has_every_field_and_no_env_values() -> None:
    fp = _select_env.fingerprint(
        Path(__file__).resolve().parents[3], {"DECOY_REQUIRE_PG": "canary-value"}
    )
    assert set(fp) == set(_select_env.REQUIRED_KEYS)
    assert _select_env.valid_fingerprint(fp)
    assert fp["env"]["DECOY_REQUIRE_PG"]["set"] is True
    assert "canary-value" not in json.dumps(fp)
    assert fp["env"]["DECOY_REQUIRE_NER"] == {"set": False, "sha256": ""}


def test_fingerprint_tracks_the_lock_file_and_each_env_var(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("one")
    first = _select_env.fingerprint(tmp_path, {})
    (tmp_path / "uv.lock").write_text("two")
    assert _select_env.hard_mismatches(first, _select_env.fingerprint(tmp_path, {})) == [
        "uv_lock_sha256"
    ]
    other = _select_env.fingerprint(tmp_path, {"DECOY_SUBSTRATE": "x"})
    assert other["env"] != _select_env.fingerprint(tmp_path, {})["env"]
    assert _select_env.fingerprint(tmp_path / "none", {})["uv_lock_sha256"] == "absent"


def test_a_skip_reason_is_classified_and_never_kept() -> None:
    registry = {"needs-pg": (r"set DECOY_REQUIRE_PG for .*", ("DECOY_REQUIRE_PG",))}
    ids, unclassified = _select_env.classify_skips(["set DECOY_REQUIRE_PG for pg\n"], registry)
    assert (ids, unclassified) == ([], True)  # fullmatch: a trailing newline is not a match
    ids, unclassified = _select_env.classify_skips(
        ["set DECOY_REQUIRE_PG for pg", "other"], registry
    )
    assert (ids, unclassified) == (["needs-pg"], True)
    assert _select_env.classify_skips(["anything"]) == ([], True)  # the shipped registry is empty


# ---- atomic write ----------------------------------------------------------------------------


def test_a_failed_atomic_write_keeps_the_old_file_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "out.bin"
    atomic_write_bytes(dest, b"old")

    def boom(*_a: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk"):
        atomic_write_bytes(dest, b"new")
    assert dest.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]


def test_atomic_write_replaces_whole_content(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / "out.bin"
    atomic_write_bytes(dest, b"a" * 1000)
    atomic_write_bytes(dest, b"b")
    assert dest.read_bytes() == b"b"
    assert list(dest.parent.iterdir()) == [dest]
