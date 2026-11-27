"""`scripts/dev/impact_map.py build` on tiny repos with real coverage (ENGINE-SELECT S1, AT-B1..B10).

The build needs coverage (the `mutation` extra, absent from the gates venv) and Python 3.12 for the
sysmon core, so the cells that run it provision a throwaway build venv with `uv`. Cells that need
no venv (attribution, outcomes, ordering) always run. A node without `uv` and a 3.12 skips the
build cells with that reason named; the nightly map build job runs them."""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.dev import impact_map
from scripts.dev.impact_select._select_map import ImpactMap, load_map

REPO = Path(__file__).resolve().parents[3]
BUILDER = REPO / "scripts" / "dev" / "impact_map.py"
GIT = shutil.which("git")
UV = shutil.which("uv")


# ---- attribution without a venv ------------------------------------------------------------

SOURCE = '''\
import functools

X = compute(1)


def deco(fn):
    return fn


class K:
    attr = X + 1

    def meth(self, d=compute(2)):
        def inner():
            return 1

        return inner()


@deco
def decorated(
    a,
    b=3,
):
    """doc"""
    return a


async def coro():
    return 2
'''


def _owner_of(source: str, line: int) -> str:
    return next(iter(impact_map.attribute([line], impact_map.line_owners(source))))


@pytest.mark.parametrize(
    ("line", "owner"),
    [
        (1, "<module>"),  # import
        (3, "<module>"),  # module binding
        (7, "deco"),
        (11, "<module>"),  # class-body statement runs at import
        (13, "<module>"),  # the def line and its default value run at import
        (14, "K.meth"),  # only a def's body belongs to the function ...
        (15, "K.meth.<locals>.inner"),  # ... and the innermost def wins
        (17, "K.meth"),
        (20, "<module>"),  # decorator line
        (21, "<module>"),  # def line
        (23, "<module>"),  # signature continuation with a default
        (26, "decorated"),
        (29, "<module>"),
        (30, "coro"),
    ],
)
def test_def_decorator_default_and_class_body_lines_belong_to_the_module(
    line: int, owner: str
) -> None:
    assert _owner_of(SOURCE, line) == owner


def test_a_def_line_is_not_a_body_line() -> None:
    owners = impact_map.line_owners(SOURCE)
    assert all(lo > 13 for lo, _hi, q in owners if q == "K.meth")  # mutation: count the def line


def test_outcomes_come_from_junit_and_the_exit_code(tmp_path: Path) -> None:
    def run(body: str, rc: int) -> tuple[str, list[str]]:
        xml = tmp_path / "j.xml"
        xml.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
        return impact_map.junit_outcome(xml, rc)

    ok = '<testcase name="a"/>'
    xfail = '<testcase name="b"><skipped type="pytest.xfail" message="known"/></testcase>'
    skip = '<testcase name="c"><skipped message="canary reason"/></testcase>'
    fail = '<testcase name="d"><failure message="x"/></testcase>'
    assert run(ok + xfail, 0) == ("passed", [])  # xfail counts as run
    assert run(ok + skip, 0) == ("skipped_some", ["canary reason"])
    assert run(ok + fail, 1)[0] == "failed"
    assert run(ok, 1)[0] == "failed"  # an exit code with no failure record is still a failure
    assert run("", 5)[0] == "not_collected"
    assert impact_map.junit_outcome(tmp_path / "missing.xml", 0)[0] == "failed"


def test_files_run_longest_first(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    for n in ("test_a.py", "test_b.py", "test_c.py"):
        (tmp_path / "tests" / n).write_text("")
    order = tmp_path / "base.json"
    order.write_text(json.dumps({"file_seconds": {"tests/test_b.py": 9, "tests/test_c.py": 3}}))
    assert impact_map.discover_tests(tmp_path, order) == [
        "tests/test_b.py", "tests/test_c.py", "tests/test_a.py",
    ]  # fmt: skip


# ---- build venvs ---------------------------------------------------------------------------


def _locked(name: str) -> str:
    m = re.search(rf'name = "{name}"\nversion = "([^"]+)"', (REPO / "uv.lock").read_text())
    assert m, f"{name} is not in uv.lock"
    return m.group(1)


def _venv(root: Path, *packages: str) -> Path:
    if UV is None:
        pytest.skip("needs uv to provision the Python 3.12 build venv")
    made = subprocess.run(  # noqa: S603 -- uv with fixed arguments
        [UV, "venv", "-q", "--python", "3.12", str(root)], capture_output=True, timeout=300
    )
    if made.returncode != 0:
        pytest.skip("needs a Python 3.12 for the sysmon core")
    py = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    got = subprocess.run(  # noqa: S603
        [UV, "pip", "install", "-q", "--python", str(py), *packages],
        capture_output=True, timeout=600,
    )  # fmt: skip
    if got.returncode != 0:
        pytest.skip("the build venv could not install its packages (offline?)")
    return py


@pytest.fixture(scope="module")
def venvs(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("venvs")
    pytest_pin = f"pytest=={pytest.__version__}"
    return SimpleNamespace(
        build=_venv(root / "build", f"coverage=={_locked('coverage')}", pytest_pin),
        gate=_venv(root / "gate", pytest_pin),  # no coverage, as in the gates venv
        other=_venv(root / "other", pytest_pin, "six"),
    )


PYPROJECT = """\
[tool.pytest.ini_options]
pythonpath = ["src"]
addopts = "-m 'not slow'"
markers = ["slow: excluded from the default run"]

[tool.coverage.run]
source = ["src"]
"""


def _tiny_repo(root: Path, files: dict[str, str]) -> Path:
    assert GIT
    root.mkdir()
    for rel, text in {"pyproject.toml": PYPROJECT, **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    for args in (["init", "-q"], ["add", "-A"], [*ident, "commit", "-qm", "init"]):
        subprocess.run([GIT, *args], cwd=root, check=True, capture_output=True)  # noqa: S603
    return root


def _build(
    py: Path,
    repo: Path,
    out: Path,
    *extra: str,
    gate: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COVERAGE", "DECOY_IMPACT", "PYTEST"))
    }
    clean.pop("VIRTUAL_ENV", None)
    clean.pop("PYTHONPATH", None)
    return subprocess.run(  # noqa: S603 -- the build venv's python running the builder under test
        [str(py), str(BUILDER), "build", "--repo", str(repo), "--out", str(out),
         "--gate-python", str(gate or py), "--workers", "2", *extra],
        env=clean | (env or {}), capture_output=True, text=True, timeout=580,
    )  # fmt: skip


def _executors(m: ImpactMap, src: str, qual: str) -> set[str]:
    return {m.tests[i] for i in m.executors.get(src, {}).get(qual, [])}


def _site_packages(py: Path) -> Path:
    out = subprocess.run(  # noqa: S603
        [str(py), "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return Path(out.stdout.strip())


MOD = """\
import functools


def deco(fn):
    return fn


X = 1


class K:
    attr = X + 1

    def meth(self):
        return 7


def f():
    return 1


def g():
    return 2


@deco
def decorated_never_called():
    return 3


def never_called():
    return 4


@functools.lru_cache(maxsize=None)
def cached():
    return 5


def threaded():
    return 6


def fixture_fn():
    return 8
"""

BASE_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/mod.py": MOD,
    "tests/conftest.py": (
        "import pytest\nfrom pkg import mod\n\n\n"
        "@pytest.fixture(scope='session')\ndef shared():\n    return mod.fixture_fn()\n"
    ),
    "tests/test_a.py": (
        "from pkg import mod\n\n\ndef test_a():\n"
        "    assert mod.f() == 1\n    assert mod.cached() == 5\n    assert mod.K().meth() == 7\n"
    ),
    "tests/test_b.py": (
        "from pkg import mod\n\n\ndef test_b():\n    assert mod.g() == 2\n    assert mod.cached() == 5\n\n\n"
        "def test_b_fixture(shared):\n    assert shared == 8\n"
    ),
    "tests/test_c.py": "from pkg import mod\n\n\ndef test_c():\n    assert True\n",
    "tests/test_thread.py": (
        "import threading\nfrom pkg import mod\n\n\ndef test_t():\n"
        "    t = threading.Thread(target=mod.threaded)\n    t.start()\n    t.join()\n"
    ),
}


@pytest.fixture(scope="module")
def base_map(venvs: SimpleNamespace, tmp_path_factory: pytest.TempPathFactory) -> ImpactMap:
    root = tmp_path_factory.mktemp("base")
    repo = _tiny_repo(root / "repo", BASE_FILES)
    out = root / "map.json.gz"
    done = _build(venvs.build, repo, out)
    assert done.returncode == 0, done.stderr
    return load_map(out)


MOD_PATH = "src/pkg/mod.py"
T = {n: f"tests/test_{n}.py" for n in "abc"} | {"thread": "tests/test_thread.py"}


def test_b1_each_function_has_exactly_its_callers_and_def_lines_are_module_scope(
    base_map: ImpactMap,
) -> None:
    assert _executors(base_map, MOD_PATH, "f") == {T["a"]}
    assert _executors(base_map, MOD_PATH, "g") == {T["b"]}
    assert _executors(base_map, MOD_PATH, "K.meth") == {T["a"]}
    # Never called: the def and decorator lines ran at import, which is module scope, not the body.
    assert "decorated_never_called" not in base_map.executors[MOD_PATH]
    assert "never_called" not in base_map.executors[MOD_PATH]


def test_b2_a_cached_function_is_executed_by_every_file_that_calls_it(base_map: ImpactMap) -> None:
    assert _executors(base_map, MOD_PATH, "cached") == {T["a"], T["b"]}


def test_b3_a_session_fixture_runs_in_every_file_that_uses_it(base_map: ImpactMap) -> None:
    assert _executors(base_map, MOD_PATH, "fixture_fn") == {T["b"]}


def test_b6_importing_a_module_makes_a_test_a_module_scope_executor(base_map: ImpactMap) -> None:
    assert _executors(base_map, MOD_PATH, impact_map.MODULE) == set(T.values())
    c = base_map.tests.index(T["c"])
    for qual in ("f", "g", "K.meth", "cached", "threaded", "fixture_fn"):
        assert c not in base_map.executors[MOD_PATH][qual]
    # A decorator applied at import runs its body in every importer; that is module-time work too.
    assert _executors(base_map, MOD_PATH, "deco") == set(T.values())


def test_b10_a_function_run_only_in_a_thread_is_attributed(base_map: ImpactMap) -> None:
    assert _executors(base_map, MOD_PATH, "threaded") == {T["thread"]}


def test_the_map_lists_every_test_file_with_an_outcome(base_map: ImpactMap) -> None:
    assert sorted(base_map.tests) == sorted(["tests/test_a.py", "tests/test_b.py", "tests/test_c.py",
                                              "tests/test_thread.py"])  # fmt: skip
    assert set(base_map.outcomes) == {"passed"}
    assert base_map.repo == "decoy-engine" and re.fullmatch(r"[0-9a-f]{40}", base_map.map_sha)


# ---- outcomes, canaries, fingerprint -------------------------------------------------------

OUTCOME_FILES = {
    "src/pkg/__init__.py": "",
    "tests/test_pass.py": "def test_p():\n    assert True\n",
    "tests/test_fail.py": "def test_f():\n    assert False\n",
    "tests/test_xfail.py": "import pytest\n\n\n@pytest.mark.xfail\ndef test_x():\n    assert False\n",
    "tests/test_slow.py": "import pytest\n\npytestmark = pytest.mark.slow\n\n\ndef test_s():\n    assert True\n",
    "tests/test_skip.py": (
        "import pytest\n\n\ndef test_a():\n    print('canary-stdout')\n    assert True\n\n\n"
        "def test_b():\n    pytest.skip('canary-skip-reason')\n"
    ),
}


def test_b5_b7_b9_outcomes_canaries_and_fingerprint(venvs: SimpleNamespace, tmp_path: Path) -> None:
    repo = _tiny_repo(tmp_path / "repo", OUTCOME_FILES)
    out = tmp_path / "map.json.gz"
    # The gate venv has no coverage; the build venv's fingerprint must still equal it.
    done = _build(
        venvs.build, repo, out, gate=venvs.gate, env={"DECOY_REQUIRE_PG": "canary-env-value"}
    )
    assert done.returncode == 0, done.stderr
    m = load_map(out)
    got = dict(zip(m.tests, m.outcomes, strict=True))
    assert got == {
        "tests/test_pass.py": "passed",
        "tests/test_fail.py": "failed",
        "tests/test_xfail.py": "passed",
        "tests/test_slow.py": "not_collected",
        "tests/test_skip.py": "skipped_some",
    }
    skip_idx = m.tests.index("tests/test_skip.py")
    assert m.skips == {
        skip_idx: ([], True)
    }  # unclassified: the shipped ENV_SKIPS registry is empty
    # B9: every fingerprint field is recorded.
    assert set(m.fingerprint) == {
        "platform",
        "python",
        "uv_lock_sha256",
        "dists_sha256",
        "companion",
        "env",
    }
    assert m.fingerprint["python"] == "3.12"
    assert m.fingerprint["env"]["DECOY_REQUIRE_PG"]["set"] is True
    # B7: no value from a test, a skip reason or the environment reaches the map.
    raw = gzip.decompress(out.read_bytes()).decode()
    for canary in ("canary-stdout", "canary-skip-reason", "canary-env-value"):
        assert canary not in raw
        assert canary not in done.stdout + done.stderr


def test_b9_a_build_venv_whose_distributions_differ_from_the_gate_venv_exits_1(
    venvs: SimpleNamespace, tmp_path: Path
) -> None:
    repo = _tiny_repo(tmp_path / "repo", OUTCOME_FILES)
    out = tmp_path / "map.json.gz"
    out.write_bytes(b"PRIOR")
    done = _build(venvs.build, repo, out, "--tests", "tests/test_pass.py", gate=venvs.other)
    assert done.returncode == 1
    assert "dists_sha256" in done.stderr
    assert out.read_bytes() == b"PRIOR"  # the old map stays


def test_b5_a_file_that_runs_too_long_is_recorded_as_a_timeout(
    venvs: SimpleNamespace, tmp_path: Path
) -> None:
    repo = _tiny_repo(
        tmp_path / "repo",
        {"tests/test_hang.py": "import time\n\n\ndef test_h():\n    time.sleep(120)\n",
         "tests/test_fast.py": "def test_f():\n    assert True\n"},
    )  # fmt: skip
    out = tmp_path / "map.json.gz"
    done = _build(venvs.build, repo, out, "--file-timeout", "20")
    assert done.returncode == 0, done.stderr
    m = load_map(out)
    assert dict(zip(m.tests, m.outcomes, strict=True)) == {
        "tests/test_hang.py": "timeout",
        "tests/test_fast.py": "passed",
    }


# ---- subprocess evidence ---------------------------------------------------------------------

CHILD = (
    "import sys; sys.path.insert(0, {src!r}); from pkg import mod; mod.{fn}(); "
    "open({data!r}).read()"
)
CHILD_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/mod.py": "def child_ordinary():\n    return 1\n\n\ndef child_isolated():\n    return 2\n",
    "data/ord.txt": "o",
    "data/iso.txt": "i",
}


def _child_test(flag: str, fn: str, data: str) -> str:
    return (
        "import subprocess, sys\nfrom pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parents[1]\n\n\n"
        "def test_child():\n"
        f"    code = {CHILD!r}.format(src=str(ROOT / 'src'), fn={fn!r}, data=str(ROOT / {data!r}))\n"
        f"    subprocess.run([sys.executable, *{[flag] if flag else []!r}, '-c', code], check=True)\n"
    )


def test_b4_a_child_process_is_measured_under_ordinary_and_isolated_python(
    venvs: SimpleNamespace, tmp_path: Path
) -> None:
    files = CHILD_FILES | {
        "tests/test_ordinary.py": _child_test("", "child_ordinary", "data/ord.txt"),
        "tests/test_isolated.py": _child_test("-I", "child_isolated", "data/iso.txt"),
    }
    repo = _tiny_repo(tmp_path / "repo", files)
    out = tmp_path / "map.json.gz"
    done = _build(venvs.build, repo, out)
    assert done.returncode == 0, done.stderr
    m = load_map(out)
    mod = "src/pkg/mod.py"
    assert _executors(m, mod, "child_ordinary") == {"tests/test_ordinary.py"}
    assert _executors(m, mod, "child_isolated") == {"tests/test_isolated.py"}
    reads = {m.tests[i]: {m.paths[p] for p in ps} for i, ps in m.reads.items()}
    assert "data/ord.txt" in reads["tests/test_ordinary.py"]
    assert "data/iso.txt" in reads["tests/test_isolated.py"]
    assert "data/iso.txt" not in reads["tests/test_ordinary.py"]
    # The build leaves the shared venv as it found it.
    site = _site_packages(venvs.build)
    assert not (site / impact_map.PTH_NAME).exists()
    assert not (site / f"{impact_map.BOOT_NAME}.py").exists()


@pytest.mark.parametrize("launcher", ["-S", "base"])
def test_b4_a_child_that_skips_the_hook_fails_the_build_and_keeps_the_old_map(
    venvs: SimpleNamespace, tmp_path: Path, launcher: str
) -> None:
    exe = "sys._base_executable" if launcher == "base" else "sys.executable"
    flag = ", '-S'" if launcher == "-S" else ""
    body = (
        "import subprocess, sys\n\n\ndef test_unmeasured():\n"
        f"    subprocess.run([{exe}{flag}, '-c', 'pass'], check=True)\n"
    )
    repo = _tiny_repo(tmp_path / "repo", {"tests/test_unmeasured.py": body})
    out = tmp_path / "out" / "map.json.gz"
    out.parent.mkdir()
    out.write_bytes(b"PRIOR")
    done = _build(venvs.build, repo, out)
    assert done.returncode == 1
    assert "audit hook missing" in done.stderr
    assert out.read_bytes() == b"PRIOR"
    assert [p.name for p in out.parent.iterdir()] == ["map.json.gz"]  # no temp file left behind
    site = _site_packages(venvs.build)
    assert not (site / impact_map.PTH_NAME).exists()


# ---- file reads ------------------------------------------------------------------------------

READ_FILES = {
    "data/a.txt": "a",
    "data/b/x.txt": "x",
    "data/b/y.txt": "y",
    "data/c.txt": "c",
    "data/d.txt": "never read",
    "src/pkg/__init__.py": "",
    "src/pkg/other.py": "VALUE = 1\n",
    "src/pkg/loader.py": (
        "from pathlib import Path\n\nfrom pkg import other\n\n"
        "TEXT = (Path(__file__).resolve().parents[2] / 'data' / 'c.txt').read_text()\n"
    ),
    "src/pkg/mod.py": "from pkg import other\n\n\ndef f():\n    return other.VALUE\n",
    "tests/test_reads.py": (
        "import inspect\nfrom pathlib import Path\n\nimport pytest\n\nfrom pkg import loader, mod\n\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "TOP = (ROOT / 'data' / 'a.txt').read_text()\n"
        "NAMES = sorted(p.name for p in (ROOT / 'data' / 'b').rglob('*.txt'))\n\n\n"
        "@pytest.mark.parametrize('name', NAMES)\n"
        "def test_x(name):\n"
        "    assert 'def f' in inspect.getsource(mod.f)\n"
        "    scratch = ROOT / 'untracked_scratch.txt'\n"
        "    scratch.write_text('t')\n    assert scratch.read_text() == 't'\n    assert loader.TEXT\n"
    ),
}


def test_b8_reads_and_listings_are_the_tracked_files_and_dirs_the_test_touched(
    venvs: SimpleNamespace, tmp_path: Path
) -> None:
    repo = _tiny_repo(tmp_path / "repo", READ_FILES)
    out = tmp_path / "map.json.gz"
    done = _build(venvs.build, repo, out)
    assert done.returncode == 0, done.stderr
    m = load_map(out)
    assert m.tests == ["tests/test_reads.py"]
    i = m.tests.index("tests/test_reads.py")
    reads = {m.paths[p] for p in m.reads[i]}
    lists = {m.paths[p] for p in m.lists.get(i, [])}
    watched = ("data/", "src/")
    assert {r for r in reads if r.startswith(watched)} == {
        "data/a.txt",  # test-module top-level read
        "data/c.txt",  # a src module reading data while it is imported
        "src/pkg/mod.py",  # inspect.getsource in the test body
    }
    # The import loader's opens (other.py, loader.py, mod.py as an import) and the untracked file
    # are not dependencies; neither are coverage's own listings of the source dirs.
    assert "untracked_scratch.txt" not in reads
    # `src` itself is listed by pytest's own plugin discovery on sys.path, a real read of that dir.
    assert {d for d in lists if d.startswith(("data", "src/"))} == {"data/b"}
    assert not any("__pycache__" in p for p in m.paths)
