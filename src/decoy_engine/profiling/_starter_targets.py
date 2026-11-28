"""Target-path allocation and relationship/destination checks for the starter config.

Split out of `_starter_config` to keep that module under the size budget. Same behavior,
no public surface: `_starter_config` imports these names.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from decoy_engine.config import (
    PipelineConfigError,
    TargetDescriptor,
    duplicate_target_groups,
    relationship_shape_error,
)
from decoy_engine.profiling.scan_set import ScanSet, TableScan
from decoy_engine.safe_output import ConfigProblem

_TARGETS: TypeAdapter[dict[str, TargetDescriptor]] = TypeAdapter(dict[str, TargetDescriptor])
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def check_relationship_shapes(scan: ScanSet, relationships: Sequence[Mapping[str, Any]]) -> None:
    columns = {t.name: [f.name for f in t.profile.fields] for t in scan.tables}
    for position, rel in enumerate(relationships):
        found = relationship_shape_error(rel, columns)
        if found is not None:
            code, path = found
            raise PipelineConfigError.from_problems(
                [
                    ConfigProblem(
                        code,
                        f"relationships[{position}]",
                        f"A declared relationship does not fit the scanned tables ({path}).",
                    )
                ],
                prefix="starter config input is invalid",
            )


def allocate_targets(scan: ScanSet, given: Mapping[str, Any]) -> dict[str, Any]:
    """The one place a target path is made. Raises ValueError (names only) on a bad input."""
    readers: dict[str, int] = {}
    for table in scan.tables:
        if table.descriptor["type"] == "file":
            readers[table.descriptor["path"]] = readers.get(table.descriptor["path"], 0) + 1
    out: dict[str, Any] = {}
    used_dirs: set[str] = set()
    for table in scan.tables:
        name = table.name
        if name in given:
            explicit = given[name]
            if not isinstance(explicit, Mapping) or not explicit:
                raise ValueError(f"the target given for table {name!r} is empty or not a mapping")
            out[name] = copy.deepcopy(dict(explicit))
        else:
            shared = table.descriptor["type"] == "file" and readers[table.descriptor["path"]] > 1
            out[name] = _default_target(table, used_dirs, shared)
    return out


def _default_target(table: TableScan, used_dirs: set[str], shared: bool) -> dict[str, Any]:
    descriptor = table.descriptor
    target: dict[str, Any] = {"type": "file", "format": descriptor["format"]}
    if descriptor["type"] == "file":
        path = Path(descriptor["path"])
        middle = f".{_UNSAFE_NAME.sub('_', table.name)}" if shared else ""
        target["path"] = str(path.with_name(f"{path.stem}{middle}.masked{path.suffix}"))
        if descriptor.get("layout"):
            target["layout"] = copy.deepcopy(descriptor["layout"])
    else:
        # Cloud inputs are written to a local folder; two table names must not share a file.
        base = _UNSAFE_NAME.sub("_", table.name)
        name, n = base, 1
        while name in used_dirs:
            n += 1
            name = f"{base}-{n}"
        used_dirs.add(name)
        target["path"] = f"masked/{name}.{descriptor['format']}"
    return target


def refuse_shared_destinations(targets: Mapping[str, Any], table_names: Sequence[str]) -> None:
    """Refuse two tables writing one destination before the full validation reports it generically."""
    try:
        validated = _TARGETS.validate_python(dict(targets))
    except ValidationError:
        return  # a malformed target is reported by `_check`
    groups = duplicate_target_groups(validated, table_names)
    if groups:
        first, second = groups[0][:2]
        raise ValueError(f"tables {first!r} and {second!r} share one target destination")
