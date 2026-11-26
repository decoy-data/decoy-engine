"""The impact map file: one writer model, one strict reader.

`ImpactMap.to_document` writes `format_version` 1 and `load_map` reads it back through the same
field list, so the two cannot drift (catalog class 4). The reader is the only code that opens a
map. It fails closed: any problem raises `MapRejectedError` with a fixed reason token, which the
selector turns into the D8 doubt and legacy selection. Tokens never carry a path, a value or the
original exception (catalog class 3), so a rejected map leaks nothing into logs."""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._atomic_write import atomic_write_bytes
from ._select_env import valid_fingerprint

FORMAT_VERSION = 1
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
OUTCOMES = frozenset({"passed", "skipped_some", "failed", "timeout", "not_collected"})
_SHA = re.compile(r"[0-9a-f]{40}")

# Fixed tokens; the selector prints one of these and nothing else about a bad map.
REASONS = frozenset(
    {"missing", "unreadable", "too_big", "not_json", "bad_version", "bad_shape", "bad_index"}
)


class MapRejectedError(Exception):
    """The map cannot be trusted. `reason` is one of `REASONS`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ImpactMap:
    repo: str
    map_sha: str
    fingerprint: dict[str, Any]
    built_at: str
    tests: list[str]
    paths: list[str]
    outcomes: list[str]
    skips: dict[int, tuple[list[str], bool]] = field(default_factory=dict)
    executors: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    reads: dict[int, list[int]] = field(default_factory=dict)
    lists: dict[int, list[int]] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "format_version": FORMAT_VERSION,
            "repo": self.repo,
            "map_sha": self.map_sha,
            "fingerprint": self.fingerprint,
            "built_at": self.built_at,
            "tests": self.tests,
            "paths": self.paths,
            "outcomes": self.outcomes,
            "skips": {
                str(i): {"ids": ids, "unclassified": u} for i, (ids, u) in self.skips.items()
            },
            "executors": self.executors,
            "reads": {str(i): v for i, v in self.reads.items()},
            "lists": {str(i): v for i, v in self.lists.items()},
        }


def dump_map(m: ImpactMap, dest: Path) -> None:
    raw = json.dumps(m.to_document(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    # mtime=0 keeps the bytes a pure function of the map, so two builds of one input compare equal.
    atomic_write_bytes(dest, gzip.compress(raw, mtime=0))


def _int(x: object) -> bool:
    return type(x) is int  # a bool is an int subclass and must not pass as an index


def _str_list(x: object) -> bool:
    return isinstance(x, list) and all(isinstance(s, str) for s in x)


def _index_list(x: object, bound: int) -> list[int]:
    if not isinstance(x, list) or not all(_int(i) for i in x):
        raise MapRejectedError("bad_shape")
    if any(i < 0 or i >= bound for i in x):
        raise MapRejectedError("bad_index")
    return list(x)


def _index_key(k: object, bound: int) -> int:
    if not isinstance(k, str) or not k.isascii() or not k.isdecimal():
        raise MapRejectedError("bad_shape")
    i = int(k)
    if i >= bound:
        raise MapRejectedError("bad_index")
    return i


def _read_document(path: Path) -> object:
    reason = ""
    raw = b""
    try:
        with gzip.open(path, "rb") as fh:
            raw = fh.read(MAX_UNCOMPRESSED_BYTES + 1)
    except FileNotFoundError:
        reason = "missing"
    except (OSError, EOFError):  # BadGzipFile is an OSError
        reason = "unreadable"
    if reason:
        raise MapRejectedError(reason)
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise MapRejectedError("too_big")
    doc: object = None
    try:
        doc = json.loads(raw)  # json only: no pickle, no eval
    except ValueError:
        reason = "not_json"
    if reason:
        raise MapRejectedError(reason)
    return doc


def load_map(path: Path) -> ImpactMap:
    """Read and validate a map once. Unknown extra keys are ignored; a missing or mistyped
    required key, an unknown `format_version` or an out-of-range index rejects the whole map."""
    doc = _read_document(path)
    if not isinstance(doc, dict):
        raise MapRejectedError("bad_shape")
    version = doc.get("format_version")
    if not _int(version):
        raise MapRejectedError("bad_shape")
    if version != FORMAT_VERSION:
        raise MapRejectedError("bad_version")
    required = ("repo", "map_sha", "fingerprint", "built_at", "tests", "paths", "outcomes")
    if any(k not in doc for k in (*required, "skips", "executors", "reads", "lists")):
        raise MapRejectedError("bad_shape")
    repo, sha, built = doc["repo"], doc["map_sha"], doc["built_at"]
    tests, paths, outcomes = doc["tests"], doc["paths"], doc["outcomes"]
    if not (isinstance(repo, str) and isinstance(built, str) and isinstance(sha, str)):
        raise MapRejectedError("bad_shape")
    if _SHA.fullmatch(sha) is None or not valid_fingerprint(doc["fingerprint"]):
        raise MapRejectedError("bad_shape")
    if not (_str_list(tests) and _str_list(paths) and _str_list(outcomes)):
        raise MapRejectedError("bad_shape")
    if len(outcomes) != len(tests):
        raise MapRejectedError("bad_index")
    if any(o not in OUTCOMES for o in outcomes):
        raise MapRejectedError("bad_shape")
    nt, np_ = len(tests), len(paths)
    skips: dict[int, tuple[list[str], bool]] = {}
    if not isinstance(doc["skips"], dict):
        raise MapRejectedError("bad_shape")
    for k, v in doc["skips"].items():
        if not (
            isinstance(v, dict)
            and _str_list(v.get("ids"))
            and isinstance(v.get("unclassified"), bool)
        ):
            raise MapRejectedError("bad_shape")
        skips[_index_key(k, nt)] = (list(v["ids"]), v["unclassified"])
    executors: dict[str, dict[str, list[int]]] = {}
    if not isinstance(doc["executors"], dict):
        raise MapRejectedError("bad_shape")
    for src, by_qual in doc["executors"].items():
        if not isinstance(src, str) or not isinstance(by_qual, dict):
            raise MapRejectedError("bad_shape")
        executors[src] = {}
        for qual, idx in by_qual.items():
            if not isinstance(qual, str):
                raise MapRejectedError("bad_shape")
            executors[src][qual] = _index_list(idx, nt)
    sections: list[dict[int, list[int]]] = []
    for name in ("reads", "lists"):
        if not isinstance(doc[name], dict):
            raise MapRejectedError("bad_shape")
        sections.append({_index_key(k, nt): _index_list(v, np_) for k, v in doc[name].items()})
    return ImpactMap(
        repo=repo,
        map_sha=sha,
        fingerprint=doc["fingerprint"],
        built_at=built,
        tests=list(tests),
        paths=list(paths),
        outcomes=list(outcomes),
        skips=skips,
        executors=executors,
        reads=sections[0],
        lists=sections[1],
    )
