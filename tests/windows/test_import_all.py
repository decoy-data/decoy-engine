"""AT-EW1-1: every engine module imports, on every OS (Windows plan EW1).

Today `import decoy_engine` fails on Windows: module-scope `os.O_DIRECTORY`, `os.O_CLOEXEC`
and `import resource` raise before any code runs. The walk imports each module in a fresh
interpreter-level state (one process) and reports every failure with its exception class and
the missing name, never a path or a value.
"""

from __future__ import annotations

import importlib
import pkgutil

import decoy_engine

# Entry scripts run code on import; a module with `__main__` in its name is not a library module.
SKIPPED_LEAVES = frozenset({"__main__"})
# A module that refuses to import without its optional extra says so in a typed ImportError.
OPTIONAL_EXTRA_LEAVES = frozenset({"mimesis"})


def _walk() -> list[str]:
    names = ["decoy_engine"]
    for info in pkgutil.walk_packages(decoy_engine.__path__, "decoy_engine."):
        if info.name.rsplit(".", 1)[-1] not in SKIPPED_LEAVES:
            names.append(info.name)
    return names


def test_every_engine_module_imports() -> None:
    failures: list[str] = []
    names = _walk()
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            if name.rsplit(".", 1)[-1] in OPTIONAL_EXTRA_LEAVES and "optional" in str(exc):
                continue
            failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")
    assert not failures, "modules that fail to import:\n" + "\n".join(failures)
    assert len(names) > 300, "the walk found too few modules"
