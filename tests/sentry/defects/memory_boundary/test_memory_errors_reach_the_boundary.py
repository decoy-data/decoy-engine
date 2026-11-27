"""A `MemoryError` reaches `memory_boundary` through every handler of the commit windows.

A memory error caught by `except Exception`, `except BaseException` or `except ArrowException`
becomes a data verdict (a failed receipt, a malformed vault segment, `unexpected_error`), and the
boundary can no longer pick the right reserved result. Inner handlers in `SCOPE` take one of
three shapes: a preceding `except MemoryError: raise`, a final bare `raise` with no `return`,
`break` or `continue`, or a registered classifier. `tests/unit/execution/publication/
test_memory_boundary_window.py` (A19) checks `SCOPE` against a trace of both routes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sentry.defects import _defect_scan as scan
from tests.sentry.defects.memory_boundary import _memory_scan as ms


def test_every_handler_in_the_windows_lets_a_memory_error_through() -> None:
    found = ms.scan_scope(scan.ModuleIndex())
    assert not found, "a MemoryError can be hidden here:\n" + "\n".join(found)


def test_the_scope_names_files_that_exist() -> None:
    index = scan.ModuleIndex()
    assert len(ms.scope_paths(index)) > 13


def _seeded(
    tmp_path: Path,
    source: str,
    *,
    classifiers: dict[tuple[str, str], str] | None = None,
    extra_source: str | None = None,
) -> list[str]:
    pkg = tmp_path / "decoy_engine"
    pkg.mkdir(exist_ok=True)
    (pkg / "x.py").write_text(source)
    extra = ()
    if extra_source is not None:
        (pkg / "y.py").write_text(extra_source)
        extra = ("y.py",)
    return ms.scan_scope(scan.ModuleIndex(pkg), ("x.py",), classifiers or {}, extra)


IMPORTS = "from pyarrow import ArrowException as AE\nimport contextlib as cl\nfrom contextlib import suppress as ignore\n"

BYPASSES = {
    "isinstance_check": "def f():\n try:\n  g()\n except Exception as e:\n  if isinstance(e, MemoryError):\n   raise\n  return None\n",
    "tuple_with_memory": "def f():\n try:\n  g()\n except (Exception, MemoryError):\n  return None\n",
    "memory_returns": "def f():\n try:\n  g()\n except MemoryError:\n  return None\n",
    "clause_after_broad": "def f():\n try:\n  g()\n except Exception:\n  return None\n except MemoryError:\n  raise\n",
    "arrow_clause_only": "def f():\n try:\n  g()\n except ArrowMemoryError:\n  raise\n except Exception:\n  return None\n",
    "helper_call_only": "def f():\n try:\n  g()\n except Exception as e:\n  reraise_memory(e)\n  return e\n",
    "conditional_raise": "def f():\n try:\n  g()\n except BaseException:\n  cleanup()\n  if flag:\n   raise\n",
    "bare_except": "def f():\n try:\n  g()\n except:\n  pass\n",
    "dotted_arrow": "def f():\n try:\n  g()\n except pa.lib.ArrowException:\n  pass\n",
    "aliased_arrow": IMPORTS + "def f():\n try:\n  g()\n except AE:\n  pass\n",
    "conditional_swallow": "def f():\n try:\n  g()\n except Exception:\n  if cond:\n   return None\n  raise\n",
    "raise_other_then_raise": "def f():\n try:\n  g()\n except Exception as e:\n  if cond:\n   raise Other() from e\n  raise\n",
    "suppress_exception": "import contextlib\ndef f():\n with contextlib.suppress(Exception):\n  g()\n",
    "suppress_memory": "from contextlib import suppress\ndef f():\n with suppress(MemoryError):\n  g()\n",
    "suppress_module_alias": IMPORTS + "def f():\n with cl.suppress(Exception):\n  g()\n",
    "suppress_name_alias": IMPORTS + "def f():\n with ignore(Exception):\n  g()\n",
    "return_in_finally": "def f():\n try:\n  g()\n finally:\n  return 1\n",
    "break_in_finally": "def f():\n for i in x:\n  try:\n   g()\n  finally:\n   break\n",
    "rmtree_ignoring_errors": "import shutil\ndef f():\n shutil.rmtree(p, ignore_errors=True)\n",
    "rmtree_bare": "import shutil\ndef f():\n shutil.rmtree(p)\n",
    "rmtree_from_alias": "from shutil import rmtree as rm\ndef f():\n rm(p)\n",
    "rmtree_module_alias": "import shutil as sh\ndef f():\n sh.rmtree(p)\n",
    "module_constant_tuple": "ERRS = (OSError, Exception)\ndef f():\n try:\n  g()\n except ERRS:\n  return None\n",
    "unresolved_variable": "def f(errs):\n try:\n  g()\n except errs:\n  pass\n",
    "classifier_shape_unregistered": "def f():\n try:\n  g()\n except MemoryError:\n  return RESERVED\n",
}


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_the_scan_sees_each_seeded_bypass(tmp_path: Path, name: str) -> None:
    assert _seeded(tmp_path, BYPASSES[name]), name


ACCEPTED = {
    "clause_before_broad": "def f():\n try:\n  g()\n except MemoryError:\n  raise\n except Exception:\n  return None\n",
    "cleanup_then_raise": "def f():\n try:\n  g()\n except BaseException:\n  cleanup()\n  raise\n",
    "unrelated_types": "def f():\n try:\n  g()\n except (OSError, ValueError):\n  pass\n",
    "finalizer": "class C:\n def __del__(self):\n  try:\n   g()\n  except Exception:\n   pass\n",
}


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_the_scan_accepts_the_allowed_shapes(tmp_path: Path, name: str) -> None:
    assert _seeded(tmp_path, ACCEPTED[name]) == []


def test_a_registered_classifier_is_accepted_once_and_only_once(tmp_path: Path) -> None:
    registry = {("x.py", "f"): "arm"}
    one = "def f():\n try:\n  return g()\n except MemoryError:\n  return RESERVED\n except Exception:\n  return OTHER\n"
    two = one.replace("return OTHER", "return OTHER\n except MemoryError:\n  return AGAIN")
    broad_first = "def f():\n try:\n  return g()\n except Exception:\n  return OTHER\n except MemoryError:\n  return RESERVED\n"
    assert _seeded(tmp_path, one, classifiers=registry) == []
    assert _seeded(tmp_path, two, classifiers=registry)
    assert _seeded(tmp_path, broad_first, classifiers=registry)


def test_the_run_classifier_protects_the_run_call_alone(tmp_path: Path) -> None:
    registry = {("x.py", "f"): "run"}
    ok = "def f():\n try:\n  r = run_pipeline(a)\n except BaseException as e:\n  return fail(e)\n"
    moved = "def f():\n try:\n  r = run_pipeline(a)\n  out = build(r)\n except BaseException as e:\n  return fail(e)\n"
    assert _seeded(tmp_path, ok, classifiers=registry) == []
    assert _seeded(tmp_path, moved, classifiers=registry)


def test_a_missing_classifier_is_reported(tmp_path: Path) -> None:
    found = _seeded(tmp_path, "def g():\n pass\n", classifiers={("x.py", "f"): "arm"})
    assert any("no longer exists" in line for line in found)


def test_a_scope_entry_that_matches_nothing_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "decoy_engine"
    pkg.mkdir()
    with pytest.raises(AssertionError, match="matches no file"):
        ms.scan_scope(scan.ModuleIndex(pkg), ("gone.py",), {})


ADAPTER = "def f():\n try:\n  return g()\n except MemoryError:\n  return _OUT_OF_MEMORY\n except Exception:\n  return OTHER\n"


def test_the_adapter_classifier_is_checked_exactly(tmp_path: Path) -> None:
    registry = {("x.py", "f"): "adapter"}
    assert _seeded(tmp_path, ADAPTER, classifiers=registry) == []
    wrong_record = ADAPTER.replace("return _OUT_OF_MEMORY", "return _OTHER_RECORD")
    no_fallback = ADAPTER.replace(" except Exception:\n  return OTHER\n", "")
    assert _seeded(tmp_path, wrong_record, classifiers=registry)
    assert _seeded(tmp_path, no_fallback, classifiers=registry)


def test_a_fourth_classifier_is_a_finding() -> None:
    assert ms.registry_problems(ms.CLASSIFIERS) == []
    assert ms.registry_problems({**ms.CLASSIFIERS, ("x.py", "f"): "arm"})
    assert ms.registry_problems(
        {k: v for k, v in ms.CLASSIFIERS.items() if k[1] != "memory_boundary"}
    )


def test_ignoring_errors_is_a_finding_in_the_extra_cleanup_modules(tmp_path: Path) -> None:
    ignoring = "import shutil\ndef g(p):\n shutil.rmtree(p, ignore_errors=True)\n"
    plain = "import shutil\ndef g(p):\n shutil.rmtree(p)\n"
    assert _seeded(tmp_path, "def f():\n pass\n", extra_source=ignoring)
    assert _seeded(tmp_path, "def f():\n pass\n", extra_source=plain) == []
