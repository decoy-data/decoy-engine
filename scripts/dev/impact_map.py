"""Build the impact map: which test files execute which src functions, and which repo files they read.

    python scripts/dev/impact_map.py build --gate-python <gates venv python> [--out FILE]

Run it with the build venv's interpreter (the gates venv plus the `mutation` extra, which carries
coverage). Every default-marker test file runs in its own process under `coverage run` (sysmon core
on 3.12, line data only, subprocesses patched in), so shared state such as `lru_cache` or session
fixtures cannot hide an executor. The map is written only after every file has an outcome, every
process proved that the audit hook and coverage ran in it, and the build venv's fingerprint equals
the gates venv's; any other result exits 1 and leaves the previous map in place.

The module is also the pytest plugin the child runs (`-p impact_map`): it installs the audit hook
before collection. The hook itself lives in `impact_select/_audit.py` (see there for the method).

Methods: per-test line coverage plus per-function attribution (pytest-testmon, coverage.py contexts);
module-scope lines go to the `<module>` pseudo-function because they run at import; file reads
come from PEP 578 audit events (Ekstazi, ISSTA 2015)."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # impact_select, also when run by path
from impact_select import _audit
from impact_select._atomic_write import atomic_write_text
from impact_select._select_env import classify_skips, fingerprint, hard_mismatches
from impact_select._select_map import ImpactMap, dump_map

MODULE = "<module>"
BOOT_NAME = "_decoy_impact_boot"
PTH_NAME = "a2_decoy_impact.pth"
DEFAULT_OUT = Path.home() / ".local/state/decoy-ci/engine-impact-map.json.gz"


def pytest_configure(config: object) -> None:
    """Plugin hook: install the audit hook before collection (idempotent with the .pth copy)."""
    _audit.install_audit()


class BuildFailedError(Exception):
    """A build precondition or evidence check failed. The text names a check, never a value."""


# ---- attribution -------------------------------------------------------------------------


def line_owners(source: str) -> list[tuple[int, int, str]]:
    """(first body line, last line, qualname) per def, outer before inner.

    The body starts at the first statement, so decorator, `def` and default-argument lines stay
    with the module: they run at import, not when the function is called."""
    out: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, prefix: str, in_def: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                end = child.end_lineno or child.body[-1].lineno
                out.append((child.body[0].lineno, end, qual))
                visit(child, f"{qual}.<locals>.", True)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", in_def)
            else:
                visit(child, prefix, in_def)

    visit(ast.parse(source), "", False)
    return out


def attribute(lines: Iterable[int], owners: list[tuple[int, int, str]]) -> set[str]:
    quals: set[str] = set()
    for ln in lines:
        best = MODULE
        span = None
        for lo, hi, qual in owners:
            if lo <= ln <= hi and (span is None or hi - lo <= span):
                best, span = qual, hi - lo
        quals.add(best)
    return quals


# ---- process evidence --------------------------------------------------------------------


@dataclass
class FileRun:
    index: int
    path: str
    outcome: str = "failed"
    skip_ids: list[str] = field(default_factory=list)
    unclassified: bool = False
    executed: dict[str, set[int]] = field(default_factory=dict)
    reads: set[str] = field(default_factory=set)
    lists: set[str] = field(default_factory=set)


def junit_outcome(xml_path: Path, returncode: int) -> tuple[str, list[str]]:
    """(outcome, skip reasons). A reason is classified and dropped by the caller (class 1)."""
    if returncode == 5:
        return "not_collected", []
    reasons: list[str] = []
    bad = 0
    try:
        root = ET.parse(xml_path).getroot()  # noqa: S314 -- the file is pytest's own output
    except (OSError, ET.ParseError):
        return "failed", []
    for case in root.iter("testcase"):
        bad += len(case.findall("failure")) + len(case.findall("error"))
        for sk in case.findall("skipped"):
            if sk.get("type") != "pytest.xfail":  # xfail ran the test
                reasons.append(sk.get("message") or "")
    if returncode != 0 or bad:
        return "failed", []
    return ("skipped_some" if reasons else "passed"), reasons


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
    proc.wait()


def _coverage_pids(cov_dir: Path) -> set[int]:
    pids = set()
    for p in cov_dir.glob(".coverage.*"):
        part = next((x for x in p.name.split(".") if x.startswith("pid")), "")
        if part[3:].isdigit():
            pids.add(int(part[3:]))
    return pids


def run_one(cfg: Config, index: int, test: str) -> FileRun:
    import coverage  # type: ignore[import-not-found,unused-ignore]  # build venv only

    work = cfg.work / str(index)
    shards, cov_dir = work / "audit", work / "cov"
    shards.mkdir(parents=True)
    cov_dir.mkdir()
    xml = work / "junit.xml"
    env = dict(os.environ)
    env.update(
        COVERAGE_FILE=str(cov_dir / ".coverage"),
        DECOY_IMPACT_CONTEXT=test,
        DECOY_IMPACT_SHARD_DIR=str(shards),
        DECOY_IMPACT_ROOT=str(cfg.repo),
        PYTHONPATH=os.pathsep.join(
            p for p in (str(Path(__file__).resolve().parent), env.get("PYTHONPATH", "")) if p
        ),
    )
    if sys.version_info >= (3, 12):
        env["COVERAGE_CORE"] = "sysmon"  # sees every thread; line data only
    cmd = [
        sys.executable, "-m", "coverage", "run", f"--rcfile={cfg.rcfile}", f"--context={test}",
        "-m", "pytest", test, "-p", "impact_map", "-p", "no:cacheprovider", "-q",
        f"--junitxml={xml}",
    ]  # fmt: skip
    run = FileRun(index, test)
    with subprocess.Popen(  # noqa: S603 -- argv is this interpreter plus a repo test path
        cmd, cwd=cfg.repo, env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) as proc:  # fmt: skip
        try:
            rc = proc.wait(timeout=cfg.file_timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            run.outcome = "timeout"
            return run
    run.outcome, reasons = junit_outcome(xml, rc)
    run.skip_ids, run.unclassified = classify_skips(reasons)
    run.reads, run.lists, starts, launches = _audit.read_shards(str(shards))
    roots = [s for s in starts if s["ppid"] == os.getpid()]
    children = [s for s in starts if s["ppid"] != os.getpid()]
    if len(roots) != 1 or launches > len(children):
        raise BuildFailedError(f"audit hook missing in a process of {test}")
    if {s["pid"] for s in starts} - _coverage_pids(cov_dir):
        raise BuildFailedError(f"coverage shard missing for a process of {test}")
    cov = coverage.Coverage(data_file=str(cov_dir / ".coverage"), config_file=str(cfg.rcfile))
    cov.combine([str(cov_dir)], strict=True, keep=True)
    data = cov.get_data()
    for fname in data.measured_files():
        rel = os.path.relpath(fname, cfg.repo) if os.path.isabs(fname) else fname
        if rel.endswith(".py") and rel in cfg.tracked:
            owners = line_owners((cfg.repo / rel).read_text(encoding="utf-8"))
            for qual in attribute(data.lines(fname) or (), owners):
                run.executed.setdefault(f"{rel}\0{qual}", set()).add(index)
    return run


# ---- build -------------------------------------------------------------------------------


@dataclass
class Config:
    repo: Path
    work: Path
    rcfile: Path
    tracked: frozenset[str]
    file_timeout: int


def _git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise BuildFailedError("git is not on PATH")
    return subprocess.run(  # noqa: S603 -- fixed git argv in the repo being mapped
        [git, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def write_rcfile(repo: Path, dest: Path) -> None:
    try:
        import tomllib  # type: ignore[import-not-found,unused-ignore]  # 3.11+
    except ImportError:
        raise BuildFailedError("the build needs Python 3.11+ to read pyproject.toml") from None
    cfg = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    run = cfg.get("tool", {}).get("coverage", {}).get("run", {})
    # Only branch and patch are overridden; source and omit stay what the repo configures.
    lines = ["[tool.coverage.run]"]
    for key in ("source", "omit"):
        if key in run:
            lines.append(f"{key} = {json.dumps(run[key])}")
    lines += [
        "branch = false", 'patch = ["subprocess"]', "parallel = true", "relative_files = true",
        'context = "${DECOY_IMPACT_CONTEXT}"',
    ]  # fmt: skip
    atomic_write_text(dest, "\n".join(lines) + "\n")


def interpreter_fingerprint(python: str, repo: Path) -> dict[str, object]:
    script = Path(__file__).resolve().parent / "impact_select" / "_select_env.py"
    out = subprocess.run(  # noqa: S603 -- the given interpreter runs the shared fingerprint module
        [python, str(script), "--repo", str(repo)], check=True, capture_output=True, text=True
    ).stdout
    parsed: dict[str, object] = json.loads(out)
    return parsed


def install_bootstrap() -> list[Path]:
    """Copy the audit module into this venv and add the `.pth` that loads it at startup."""
    site = Path(sysconfig.get_paths()["purelib"])
    boot, pth = site / f"{BOOT_NAME}.py", site / PTH_NAME
    boot.write_bytes((Path(_audit.__file__)).read_bytes())
    pth.write_text(f"import {BOOT_NAME}; {BOOT_NAME}.install_audit()\n", encoding="utf-8")
    return [boot, pth]


def discover_tests(repo: Path, order_file: Path | None) -> list[str]:
    found = sorted(p.relative_to(repo).as_posix() for p in (repo / "tests").rglob("test_*.py"))
    secs: dict[str, float] = {}
    if order_file and order_file.is_file():
        secs = json.loads(order_file.read_text(encoding="utf-8")).get("file_seconds", {})
    return sorted(found, key=lambda p: (-secs.get(p, 0.0), p))  # longest first


def build(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    gate_python = args.gate_python or (
        os.path.join(os.environ["DECOY_VENV"], "bin", "python")
        if os.environ.get("DECOY_VENV")
        else ""
    )
    if not gate_python:
        raise BuildFailedError(
            "pass --gate-python or set DECOY_VENV: the fingerprint check needs it"
        )
    if _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise BuildFailedError("tracked files differ from HEAD; the map must describe one commit")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    mine = fingerprint(repo)
    gate = interpreter_fingerprint(gate_python, repo)
    drift = hard_mismatches(mine, gate)
    if drift:
        raise BuildFailedError(f"build venv differs from the gates venv in: {', '.join(drift)}")
    tracked = frozenset(_git(repo, "ls-files", "-z").split("\0")) - {""}
    tests = args.tests or discover_tests(repo, args.order_file)
    if not tests:
        raise BuildFailedError("no test files found")
    installed: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="impact-map-") as tmp:
        work = Path(tmp)
        rc = work / "coveragerc.toml"
        write_rcfile(repo, rc)
        cfg = Config(repo, work / "runs", rc, tracked, args.file_timeout)
        try:
            installed = install_bootstrap()
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                runs = list(pool.map(lambda it: run_one(cfg, *it), enumerate(tests)))
        finally:
            for p in installed:
                p.unlink(missing_ok=True)  # the venv is shared; leave it as found
    dump_map(assemble(repo, sha, mine, runs, tracked), args.out)
    print(f"impact map: {len(tests)} test files, commit {sha[:8]}", file=sys.stderr)
    return 0


def assemble(
    repo: Path, sha: str, fp: dict[str, object], runs: list[FileRun], tracked: frozenset[str]
) -> ImpactMap:
    dirs = {"."} | {p for f in tracked for p in _parents(f)}
    paths: dict[str, int] = {}

    def pid(p: str) -> int:
        return paths.setdefault(p, len(paths))

    executors: dict[str, dict[str, list[int]]] = defaultdict(dict)
    reads: dict[int, list[int]] = {}
    lists: dict[int, list[int]] = {}
    skips: dict[int, tuple[list[str], bool]] = {}
    for r in runs:
        for key, idx in r.executed.items():
            src, qual = key.split("\0")
            executors[src].setdefault(qual, []).extend(idx)
        if r.reads & tracked:
            reads[r.index] = sorted(pid(p) for p in r.reads & tracked)
        if r.lists & dirs:
            lists[r.index] = sorted(pid(p) for p in r.lists & dirs)
        if r.outcome == "skipped_some":
            skips[r.index] = (r.skip_ids, r.unclassified)
    return ImpactMap(
        repo="decoy-engine",
        map_sha=sha,
        fingerprint=dict(fp),
        built_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        tests=[r.path for r in runs],
        paths=list(paths),
        outcomes=[r.outcome for r in runs],
        skips=skips,
        executors={
            s: {q: sorted(set(i)) for q, i in sorted(m.items())} for s, m in executors.items()
        },
        reads=reads,
        lists=lists,
    )


def _parents(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="run every test file once and write the map")
    b.add_argument("--repo", type=Path, default=Path.cwd())
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    b.add_argument(
        "--gate-python", default=None, help="gates venv python (default: $DECOY_VENV/bin/python)"
    )
    b.add_argument("--workers", type=int, default=int(os.environ.get("GATES_WORKERS", "4")))
    b.add_argument("--file-timeout", type=int, default=1800)
    b.add_argument("--order-file", type=Path, default=None, help="baseline json with file_seconds")
    b.add_argument(
        "--tests", nargs="*", default=None, help="repo-relative test files (default: all)"
    )
    args = ap.parse_args(argv)
    try:
        return build(args)
    except BuildFailedError as exc:
        print(f"impact_map: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"impact_map: {Path(str(exc.cmd[0])).name} failed (exit {exc.returncode})",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
