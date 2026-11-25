"""YAML loader for the detector name-hint library.

Reads ``v1/manifest.yaml`` to find the file load order, walks each
listed file, validates the entries, and returns a flat dict mapping
``detector_id`` to the list of column-name term strings whose presence
should boost that detector's confidence. The caller
(``decoy_engine.detection.detectors``) applies its existing ``_hint(terms)``
regex helper to build the actual ``re.Pattern`` objects; this loader
is intentionally a pure data layer so the regex-construction logic
lives in exactly one place.

Mirrors the established pattern in ``decoy_engine.disguises.loader``:
package-relative path lookup via ``Path(__file__).parent``, eager
validation at import time, hatchling ships the YAML files in the
wheel by default.

Failure modes (all raise ``NameHintLoaderError`` with a clear message):
  - ``manifest.yaml`` missing or unparseable
  - File listed in manifest does not exist
  - Same detector_id declared in two different files
  - Empty patterns list (a detector with no terms cannot hint anything)
  - YAML entry missing the required ``detector_id`` or ``patterns`` key
  - Pattern term is not a string

Loader is called once at engine import time
(``decoy_engine.detection.detectors`` module-level statement). The result
is cached for the lifetime of the process; reloading at runtime would
require restarting the engine.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from decoy_engine import fileaccess
from decoy_engine._config_text import (
    Expected,
    Member,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.errors import DecoyError
from decoy_engine.fileaccess import DirHandle, FileAccess, FileAccessDenied, FileRequest, FileRole
from decoy_engine.fileaccess.adapters import serial

_V1_DIR = Path(__file__).parent / "v1"
_MANIFEST_NAME = "manifest.yaml"


class NameHintLoaderError(DecoyError):
    """Raised when the name-hint library cannot be loaded.

    Names the offending file (its bare member name under `pre_scan.name_hints`), the field
    and a closed reason, never the directory, a path or a supplied value, so the operator can
    fix the YAML without grep-bisecting. A strict policy preserves a denial rather than
    translating it.
    """


def load_name_hint_terms(
    directory: Path | None = None, *, file_access: FileAccess | None = None
) -> dict[str, list[str]]:
    """Read the YAML library and return ``{detector_id: [terms]}``.

    The directory defaults to ``v1/`` next to this module, which is package data the engine
    owns. Tests pass a temp directory to exercise edge cases (malformed YAML, missing
    files, duplicate ids) without touching the shipped data; a directory a caller names is
    read through the file-access policy.

    Returns a fresh dict on each call; the caller owns it.
    """
    handle: DirHandle
    if directory is None:
        handle = fileaccess.engine_dir_handle(_V1_DIR)
    else:
        policy = fileaccess.capture(file_access)
        handle = policy.open_dir(
            FileRequest(FileRole.MODEL_PACK_ROOT, "read_dir", str(directory), "pre_scan.name_hints")
        )
    try:
        return _load_terms(handle)
    finally:
        handle.close()


def _refuse(refusal: Refusal) -> NameHintLoaderError:
    return NameHintLoaderError(refusal.text)


def _is_file(handle: DirHandle, name: str) -> bool:
    try:
        member = handle.open_file(name)
        try:
            return stat.S_ISREG(member.stat().st_mode)
        finally:
            member.close()
    except FileAccessDenied:
        # A strict policy's denial is a real refusal: an outside-root member, or (deny-by-default,
        # no existence oracle) an absent one. Preserve it instead of laundering it into an "absent"
        # result and a "does not exist" message built from a locator; it is already locator-free.
        if not fileaccess.is_ambient():
            raise
        return False
    except (FileNotFoundError, NotADirectoryError):
        return False


def _load_terms(handle: DirHandle) -> dict[str, list[str]]:
    if not _is_file(handle, _MANIFEST_NAME):
        raise_bare(
            _refuse(
                config_refusal(
                    config_position("pre_scan", "name_hints", Member(_MANIFEST_NAME)),
                    Problem.NOT_FOUND,
                    hint=(
                        "Every name-hint directory must contain a manifest.yaml "
                        "that lists the YAML files to load"
                    ),
                )
            )
        )

    manifest = _read_yaml(handle, _MANIFEST_NAME)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    at_files = config_position("pre_scan", "name_hints", Member(_MANIFEST_NAME), "files")
    if files is None:
        raise_bare(
            _refuse(config_refusal(at_files, Problem.MISSING, expected=Expected.NON_EMPTY_LIST))
        )
    if not isinstance(files, list):
        raise_bare(
            _refuse(
                config_refusal(
                    at_files, Problem.WRONG_TYPE, expected=Expected.NON_EMPTY_LIST, got=files
                )
            )
        )
    if not files:
        raise_bare(
            _refuse(config_refusal(at_files, Problem.EMPTY, expected=Expected.NON_EMPTY_LIST))
        )

    # Tracks which detector_ids were declared so a collision error names the later file (the
    # new one being added), not the first.
    detector_ids: set[str] = set()
    merged: dict[str, list[str]] = {}

    for idx, fname in enumerate(files):
        at_file = config_position("pre_scan", "name_hints", Member(_MANIFEST_NAME), "files", idx)
        if not isinstance(fname, str):
            raise_bare(
                _refuse(
                    config_refusal(at_file, Problem.WRONG_TYPE, expected=Expected.STRING, got=fname)
                )
            )
        if not _is_file(handle, fname):
            raise_bare(
                _refuse(
                    config_refusal(
                        config_position("pre_scan", "name_hints", Member(fname)),
                        Problem.NOT_FOUND,
                        expected=Expected.FILE,
                    )
                )
            )
        for det_id, terms in _read_detector_file(handle, fname).items():
            if det_id in detector_ids:
                raise_bare(
                    _refuse(
                        config_refusal(
                            config_position(
                                "pre_scan", "name_hints", Member(fname), "detectors", Name(det_id)
                            ),
                            Problem.DUPLICATE,
                            hint="Each detector_id may appear in exactly one file",
                        )
                    )
                )
            merged[det_id] = terms
            detector_ids.add(det_id)

    return merged


def _read_detector_file(handle: DirHandle, name: str) -> dict[str, list[str]]:
    """Parse one YAML file's ``detectors:`` list into {detector_id: [terms]}.

    A file with no detectors (empty list or missing key) is permitted
    -- it's a no-op contribution. A file with an entry that lacks
    ``detector_id`` or ``patterns`` is an error.
    """
    data = _read_yaml(handle, name)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_bare(
            _refuse(
                config_refusal(
                    config_position("pre_scan", "name_hints", Member(name)),
                    Problem.WRONG_TYPE,
                    expected=Expected.MAPPING,
                    got=data,
                )
            )
        )
    raw_entries = data.get("detectors")
    if raw_entries is None:
        return {}
    if not isinstance(raw_entries, list):
        raise_bare(
            _refuse(
                config_refusal(
                    config_position("pre_scan", "name_hints", Member(name), "detectors"),
                    Problem.WRONG_TYPE,
                    expected=Expected.LIST,
                    got=raw_entries,
                )
            )
        )

    out: dict[str, list[str]] = {}
    for idx, entry in enumerate(raw_entries):
        at_entry = config_position("pre_scan", "name_hints", Member(name), "detectors", idx)
        if not isinstance(entry, dict):
            raise_bare(
                _refuse(
                    config_refusal(
                        at_entry, Problem.WRONG_TYPE, expected=Expected.MAPPING, got=entry
                    )
                )
            )
        det_id = entry.get("detector_id")
        patterns = entry.get("patterns")
        if not isinstance(det_id, str) or not det_id:
            raise_bare(
                _refuse(
                    config_refusal(
                        config_position(
                            "pre_scan", "name_hints", Member(name), "detectors", idx, "detector_id"
                        ),
                        (
                            Problem.MISSING
                            if det_id is None
                            else Problem.EMPTY
                            if det_id == ""
                            else Problem.WRONG_TYPE
                        ),
                        expected=Expected.NON_EMPTY_STRING,
                        got=det_id,
                    )
                )
            )
        at_patterns = config_position(
            "pre_scan", "name_hints", Member(name), "detectors", Name(det_id), "patterns"
        )
        if not isinstance(patterns, list) or not patterns:
            raise_bare(
                _refuse(
                    config_refusal(
                        at_patterns,
                        (
                            Problem.MISSING
                            if patterns is None
                            else Problem.EMPTY
                            if patterns == []
                            else Problem.WRONG_TYPE
                        ),
                        expected=Expected.NON_EMPTY_LIST,
                        got=patterns,
                    )
                )
            )
        cleaned_terms: list[str] = []
        for t_idx, term in enumerate(patterns):
            if not isinstance(term, str) or not term:
                raise_bare(
                    _refuse(
                        config_refusal(
                            config_position(
                                "pre_scan",
                                "name_hints",
                                Member(name),
                                "detectors",
                                Name(det_id),
                                "patterns",
                                t_idx,
                            ),
                            Problem.EMPTY if term == "" else Problem.WRONG_TYPE,
                            expected=Expected.NON_EMPTY_STRING,
                            got=term,
                        )
                    )
                )
            cleaned_terms.append(term)
        if det_id in out:
            raise_bare(
                _refuse(
                    config_refusal(
                        config_position(
                            "pre_scan", "name_hints", Member(name), "detectors", Name(det_id)
                        ),
                        Problem.DUPLICATE,
                        hint="Each detector_id may appear at most once per file",
                    )
                )
            )
        out[det_id] = cleaned_terms
    return out


def _read_yaml(handle: DirHandle, name: str) -> Any:
    """yaml.safe_load, refusing any parse or read failure with a position and no exception text."""
    member = handle.open_file(name)
    try:
        return read_config(
            lambda: serial.yaml_safe_load(member),
            config_position("pre_scan", "name_hints", Member(name)),
            _refuse,
            passes=(FileAccessDenied,),
        )
    finally:
        member.close()
