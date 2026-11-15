"""Write or check the committed JSON schemas of the engine's two frozen document models.

`PipelineConfig` is read from YAML, so its schema is the validation one; `RunResult` is written,
so its schema is the serialization one. The files are meant to be read in review, hence the
indented sorted form rather than the compact digest bytes of `_canonical`.

`--check` prints one line per file that differs: the file name and the RFC 6901 pointer of the
first difference in sorted key order. It never prints a value, so a schema that picked up a
default or example cannot leak it into a CI log.

    python scripts/release/frozen_schemas.py --write
    python scripts/release/frozen_schemas.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "tests" / "snapshots" / "frozen_schemas"


def schemas() -> dict[str, dict[str, Any]]:
    from decoy_engine import PipelineConfig, RunResult

    return {
        "pipeline-config.schema.json": PipelineConfig.model_json_schema(mode="validation"),
        "run-result.schema.json": RunResult.model_json_schema(mode="serialization"),
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def first_difference(expected: Any, actual: Any, pointer: str = "") -> str | None:
    """The pointer of the first place ``actual`` differs from ``expected``, or None when equal.

    Types are compared exactly, so `1` and `true` differ although Python calls them equal.
    """
    if type(expected) is not type(actual):
        return pointer
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return f"{pointer}/{_escape(key)}"
            found = first_difference(expected[key], actual[key], f"{pointer}/{_escape(key)}")
            if found is not None:
                return found
        return None
    if isinstance(expected, list):
        for index in range(max(len(expected), len(actual))):
            if index >= len(expected) or index >= len(actual):
                return f"{pointer}/{index}"
            found = first_difference(expected[index], actual[index], f"{pointer}/{index}")
            if found is not None:
                return found
        return None
    return None if expected == actual else pointer


def check(directory: Path) -> list[str]:
    """One `<file>: <pointer>` line per file that is missing or differs from the models."""
    problems = []
    for name, document in schemas().items():
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        if text == render(document):
            continue
        try:
            stored = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"{name}: not JSON")
            continue
        pointer = first_difference(stored, document)
        problems.append(f"{name}: {'layout' if pointer is None else pointer or '(root)'}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the schema files")
    mode.add_argument("--check", action="store_true", help="exit 1 if a file differs")
    parser.add_argument("--dir", type=Path, default=SNAPSHOT_DIR, help="snapshot directory")
    args = parser.parse_args(argv)
    if args.write:
        args.dir.mkdir(parents=True, exist_ok=True)
        for name, document in schemas().items():
            (args.dir / name).write_text(render(document), encoding="utf-8")
        return 0
    problems = check(args.dir)
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
