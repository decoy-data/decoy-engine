"""Faker output lock: a committed, reviewed record of what Faker gives the engine.

`output_lock.json` holds, for every Faker locale, the keyword-argument names, a per-seed digest and
a sequential-draw digest of every reflected provider (the `faker_type` surface), and a batch digest
of every adapter provider (the masking `faker` strategy surface). It holds digests and exception
class names only: never a generated value, never exception text.

    python scripts/faker-determinism/output_lock.py --write     # the reviewed baseline operation
    python scripts/faker-determinism/output_lock.py --worker --clock ISO [--locales L ...]

The worker is one process with a frozen process-wide clock (`time_machine`, started before `faker`
imports, so default arguments that read the date at import are frozen too). The writer runs
workers at two clocks and three hash seeds, then classifies each cell as a digest, `unstable`
(clock-A processes disagree), or `raises:<class>`; a digest that differs between the two clocks
keeps its clock-A value with `calendar: true`. The sentry
(`tests/sentry/dependencies/test_faker_output_lock.py`) re-runs the workers and diffs the result
against the file in seven kinds. Plan: docs/plans/2026-11-18-faker-migrate.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(HERE) not in sys.path:  # loaded by file path in tests: the sibling modules need this
    sys.path.insert(0, str(HERE))

from digest_codec import CODEC_VERSION, _pool_digest  # noqa: E402
from worker_env import worker_env  # noqa: E402

LOCK_PATH = HERE / "output_lock.json"
LOCK_VERSION = 1
SAMPLES = 8
CLOCK_A = "2026-10-16T12:00:00Z"  # the F0 parity oracle instant (tests/parity/_f0_fixtures.py)
CLOCK_B = "2027-11-20T12:00:00Z"  # A plus 400 days: a different calendar date and year
WRITER_PYTHON = (3, 10, 20)
WORKER_TIMEOUT_S = 150
RECHECK_SEEDS = (2, 3, 4, 5, 6, 7)

DIGEST_RE = re.compile(r"[0-9a-f]{64}|unstable|raises:[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)?")
KINDS = (
    "changed",
    "removed",
    "added",
    "newly reproducible",
    "newly unstable",
    "newly calendar-dependent",
    "no longer calendar-dependent",
)
_REFLECTED_FIELDS = ("per_seed", "sequential")


class OutputLockError(RuntimeError):
    """A refusal with a fixed message: no value, no exception text."""


# --- worker -----------------------------------------------------------------------------------


def _digest(values: list[Any]) -> str:
    return hashlib.sha256(_pool_digest(values)).hexdigest()


def _cls(exc: BaseException | None) -> str:
    return "none" if exc is None else type(exc).__name__


def _reflected_cells(fake_ps: Any, fake_seq: Any, access: Any) -> dict[str, Any]:
    """`kwargs`, `per_seed` and `sequential` for every reflected provider of one locale."""
    prov_ps = access.get_faker_providers(fake_ps, provider_snapshot={})
    prov_seq = access.get_faker_providers(fake_seq, provider_snapshot={})
    cells: dict[str, Any] = {}
    for name in sorted(prov_ps):
        method = getattr(fake_ps, name, None)
        kwargs = sorted(access.reflected_kwargs(method)[1]) if callable(method) else []
        per_seed: list[Any] = []
        sequential: list[Any] = []
        per_seed_err = seq_err = ""
        try:
            for i in range(SAMPLES):
                fake_ps.seed_instance(i)
                per_seed.append(prov_ps[name]())
        except Exception as exc:
            per_seed_err = f"raises:{_cls(exc)}"
        try:
            fake_seq.seed_instance(0)
            sequential = [prov_seq[name]() for _ in range(SAMPLES)]
        except Exception as exc:
            seq_err = f"raises:{_cls(exc)}"
        cells[name] = {
            "kwargs": kwargs,
            "per_seed": per_seed_err or _digest(per_seed),
            "sequential": seq_err or _digest(sequential),
        }
    return cells


def _adapter_cells(locale: str, fake: Any, names: list[str], faker_mod: Any) -> dict[str, Any]:
    from unittest import mock

    from decoy_engine.providers_v2 import FakerAdapter, ProviderSpec

    adapter = FakerAdapter(locale)
    spec = ProviderSpec(
        locale=locale, deterministic=False, namespace=None, seed=(0).to_bytes(8, "big")
    )
    cells: dict[str, Any] = {}
    # generate_batch builds Faker(locale) itself; hand it the one preconstructed instance and let
    # it reseed before every provider, so the production seed conversion and error wrapping run.
    with mock.patch.object(faker_mod, "Faker", return_value=fake):
        for name in names:
            values: list[Any] = []
            err = ""
            try:
                values = list(adapter.generate_batch(name, spec=spec, count=SAMPLES))
            except Exception as exc:
                err = f"raises:{_cls(exc)}/{_cls(exc.__cause__)}"
            cells[name] = {"batch": err or _digest(values)}
    return cells


def run_worker_in_process(
    clock: str, locales: list[str] | None, stub: str | None
) -> dict[str, Any]:
    import time_machine  # before faker and decoy_engine: freezes default arguments read at import

    when = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    time_machine.travel(when, tick=False).start()
    import runpy

    import _engine_access as access
    import faker
    from faker.config import AVAILABLE_LOCALES

    from decoy_engine.providers_v2 import get_default_registry

    if stub:
        runpy.run_path(stub)
    names = [cap.provider for cap in get_default_registry().faker_providers()]
    out: dict[str, Any] = {}
    for locale in sorted(locales or AVAILABLE_LOCALES):
        fake_ps = access.make_faker(locale)
        fake_seq = access.make_faker(locale)
        resolved = locale if list(fake_ps.locales) == [locale] else "fallback:en_US"
        out[locale] = {
            "resolved": resolved,
            "reflected": _reflected_cells(fake_ps, fake_seq, access),
            "adapter": _adapter_cells(locale, faker.Faker(locale), names, faker),
        }
    return out


# --- classification and diff ------------------------------------------------------------------


def classify(a_docs: list[dict[str, Any]], b_doc: dict[str, Any]) -> dict[str, Any]:
    """Merge workers into lock-shaped locales: clock-A processes that disagree are `unstable`;
    a digest that differs at clock B keeps its clock-A value with `calendar: true`."""
    locales: dict[str, Any] = {}
    for loc, entry in a_docs[0].items():
        out: dict[str, Any] = {"resolved": entry["resolved"], "reflected": {}, "adapter": {}}
        for surface, fields in (("reflected", _REFLECTED_FIELDS), ("adapter", ("batch",))):
            for name, cell in entry[surface].items():
                merged: dict[str, Any] = {}
                calendar = False
                for f in fields:
                    values = [d[loc][surface][name][f] for d in a_docs]
                    if len(set(values)) > 1:
                        merged[f] = "unstable"
                        continue
                    merged[f] = values[0]
                    b_cell = b_doc.get(loc, {}).get(surface, {}).get(name)
                    calendar = calendar or (b_cell is not None and b_cell[f] != values[0])
                if surface == "reflected":
                    merged["kwargs"] = cell["kwargs"]
                merged["calendar"] = calendar
                out[surface][name] = merged
        locales[loc] = out
    return locales


def diff_locales(locked: dict[str, Any], observed: dict[str, Any]) -> dict[str, list[str]]:
    """Names grouped by the seven diff kinds; no value ever enters a name."""
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    for loc in sorted(set(locked) | set(observed)):
        if loc not in observed:
            out["removed"].append(f"locale {loc}")
            continue
        if loc not in locked:
            out["added"].append(f"locale {loc}")
            continue
        if locked[loc]["resolved"] != observed[loc]["resolved"]:
            out["changed"].append(f"{loc} resolved")
        for surface in ("reflected", "adapter"):
            old, new = locked[loc][surface], observed[loc][surface]
            for name in sorted(set(old) | set(new)):
                label = f"{loc} {surface} {name}"
                if name not in new:
                    out["removed"].append(label)
                elif name not in old:
                    out["added"].append(label)
                else:
                    _diff_cell(out, label, old[name], new[name])
    return out


def _diff_cell(
    out: dict[str, list[str]], label: str, old: dict[str, Any], new: dict[str, Any]
) -> None:
    old_kw, new_kw = old.get("kwargs", []), new.get("kwargs", [])
    for kwarg in sorted(set(old_kw) | set(new_kw)):
        if kwarg not in new_kw:
            out["removed"].append(f"{label} keyword argument {kwarg}")
        elif kwarg not in old_kw:
            out["added"].append(f"{label} keyword argument {kwarg}")
    for f in (*_REFLECTED_FIELDS, "batch"):
        if f not in old:
            continue
        before, after = old[f], new[f]
        if before == "unstable" and after != "unstable":
            out["newly reproducible"].append(f"{label} {f}")
        elif before != "unstable" and after == "unstable":
            out["newly unstable"].append(f"{label} {f}")
        elif before != after:
            out["changed"].append(f"{label} {f}")
    if old["calendar"] is False and new["calendar"] is True:
        out["newly calendar-dependent"].append(label)
    elif old["calendar"] is True and new["calendar"] is False:
        out["no longer calendar-dependent"].append(label)


def render_diff(diff: dict[str, list[str]]) -> str:
    lines = []
    for kind in KINDS:
        if diff[kind]:
            lines.append(f"{kind} ({len(diff[kind])}):")
            lines.extend(f"  {n}" for n in diff[kind])
    return "\n".join(lines) if lines else "no change"


def changelog_changed_lines(diff: dict[str, list[str]]) -> list[str]:
    """`Changed` bullets for pairs whose digest changed and that stopped reading the calendar."""
    pairs = sorted(
        label
        for label in diff["no longer calendar-dependent"]
        if any(c.startswith(label + " ") for c in diff["changed"])
    )
    return [f"Changed: {p}: digest changed and no longer depends on the calendar" for p in pairs]


# --- strict shape check -----------------------------------------------------------------------


def check_lock_shape(doc: object) -> list[str]:
    """Problems with a lock document, as paths only. Closed keys, exact types, anchored digests."""
    problems: list[str] = []

    def need(ok: bool, path: str) -> bool:
        if not ok:
            problems.append(path)
        return ok

    if not need(isinstance(doc, dict), "$") or not isinstance(doc, dict):
        return problems
    top = {"lock_version", "faker_version", "codec_version", "samples", "clocks", "locales"}
    need(set(doc) == top, "$ keys")
    for key, want in (
        ("lock_version", LOCK_VERSION),
        ("codec_version", CODEC_VERSION),
        ("samples", SAMPLES),
    ):
        v = doc.get(key)
        need(type(v) is int and v == want, key)
    fv = doc.get("faker_version")
    need(type(fv) is str and re.fullmatch(r"\d+\.\d+\.\d+", fv) is not None, "faker_version")
    clocks = doc.get("clocks")
    need(
        type(clocks) is list and len(clocks) == 2 and all(type(c) is str for c in clocks), "clocks"
    )
    locales = doc.get("locales")
    if not need(isinstance(locales, dict), "locales") or not isinstance(locales, dict):
        return problems
    for loc, entry in locales.items():
        base = f"locales.{loc}"
        keys = {"resolved", "reflected", "adapter"}
        if not need(isinstance(entry, dict) and set(entry) == keys, base):
            continue
        need(type(entry["resolved"]) is str, f"{base}.resolved")
        for surface, fields in (
            ("reflected", ("kwargs", "per_seed", "sequential", "calendar")),
            ("adapter", ("batch", "calendar")),
        ):
            cells = entry[surface]
            if not need(isinstance(cells, dict), f"{base}.{surface}"):
                continue
            for name, cell in cells.items():
                path = f"{base}.{surface}.{name}"
                if not need(isinstance(cell, dict) and set(cell) == set(fields), path):
                    continue
                for f in fields:
                    v = cell[f]
                    if f == "calendar":
                        need(type(v) is bool, f"{path}.calendar")
                    elif f == "kwargs":
                        ok = type(v) is list and all(type(k) is str for k in v)
                        need(ok, f"{path}.kwargs")
                    else:
                        need(type(v) is str and DIGEST_RE.fullmatch(v) is not None, f"{path}.{f}")
    return problems


def canonical_text(doc: dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


# --- orchestration ----------------------------------------------------------------------------


def run_worker(
    clock: str,
    hash_seed: int,
    locales: list[str] | None = None,
    stub: str | None = None,
    python_exe: str | None = None,
) -> dict[str, Any]:
    cmd = [python_exe or sys.executable, str(HERE / "output_lock.py"), "--worker", "--clock", clock]
    if locales:
        cmd += ["--locales", *locales]
    if stub:
        cmd += ["--stub", stub]
    try:
        proc: subprocess.CompletedProcess[str] | None = subprocess.run(  # noqa: S603 -- fixed argv
            cmd,
            env=worker_env(ROOT, hash_seed, "unknown"),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        proc = None
    if proc is None or proc.returncode != 0:
        raise OutputLockError("an output-lock worker failed or timed out")
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise OutputLockError("an output-lock worker printed no JSON document")
    return doc


def _suspect_locales(observed: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Locales with a cell the baseline records `unstable` that this run saw as one digest."""
    out = []
    for loc, entry in observed.items():
        for surface, fields in (("reflected", _REFLECTED_FIELDS), ("adapter", ("batch",))):
            for name, cell in entry[surface].items():
                locked = baseline.get(loc, {}).get(surface, {}).get(name)
                if locked and any(
                    locked[f] == "unstable" and cell[f] != "unstable" for f in fields
                ):
                    out.append(loc)
    return sorted(set(out))


def capture(
    a_seeds: tuple[int, ...],
    locales: list[str] | None = None,
    stub: str | None = None,
    python_exe: str | None = None,
    baseline: dict[str, Any] | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    """Run clock A at each hash seed and clock B at seed 0, concurrently, and classify.

    The dominant unstable cells are providers that draw from unseeded module-level `random`
    (the `passport_*` providers, about 428 fields in all). Two processes still agree on all 8 draws
    of one such field about 0.3% of the time, so a two-seed run would read a few of them as
    reproducible on every run. With `baseline`, a cell it records `unstable` that these seeds saw
    agree is re-run over `RECHECK_SEEDS`, and it reads as newly reproducible only if all 8 seeds
    (the two here plus those six) agree. Hash-order providers (the `it_IT` city set) can also agree
    by chance, and the chance differs between CPython minors (3.11 changed the str hash)."""
    run = runner or run_worker
    with ThreadPoolExecutor(max_workers=len(a_seeds) + 1) as pool:
        a_futs = [pool.submit(run, CLOCK_A, s, locales, stub, python_exe) for s in a_seeds]
        b_fut = pool.submit(run, CLOCK_B, 0, locales, stub, python_exe)
        a_docs = [f.result() for f in a_futs]
        b_doc = b_fut.result()
    observed = classify(a_docs, b_doc)
    suspects = _suspect_locales(observed, baseline) if baseline else []
    if suspects:
        with ThreadPoolExecutor(max_workers=len(RECHECK_SEEDS)) as pool:
            futs = [pool.submit(run, CLOCK_A, s, suspects, stub, python_exe) for s in RECHECK_SEEDS]
            extra = [f.result() for f in futs]
        merged = classify(
            [{loc: d[loc] for loc in suspects} for d in (*a_docs, *extra)],
            {loc: b_doc[loc] for loc in suspects if loc in b_doc},
        )
        observed.update(merged)
    return observed


def pinned_faker() -> str:
    """The one exact `faker==` pin in pyproject.toml; the pin sentry reads it through this."""
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    pins = [d.split("==", 1)[1] for d in deps if d.startswith("faker==")]
    if len(pins) != 1 or re.fullmatch(r"\d+\.\d+\.\d+", pins[0]) is None:
        raise OutputLockError("pyproject.toml must carry exactly one exact faker pin")
    return pins[0]


def build_lock(locales: dict[str, Any], faker_version: str) -> dict[str, Any]:
    return {
        "lock_version": LOCK_VERSION,
        "faker_version": faker_version,
        "codec_version": CODEC_VERSION,
        "samples": SAMPLES,
        "clocks": [CLOCK_A, CLOCK_B],
        "locales": locales,
    }


def write_lock(path: Path = LOCK_PATH) -> int:
    from importlib.metadata import version

    pinned = pinned_faker()
    if sys.version_info[:3] != WRITER_PYTHON or version("faker") != pinned:
        print(
            "output_lock: refused: write only under CPython 3.10.20 with the pinned Faker",
            file=sys.stderr,
        )
        return 1
    try:
        observed = capture((0, 1, 2))
    except OutputLockError:
        print("output_lock: refused: a worker failed", file=sys.stderr)
        return 1
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    path.write_text(canonical_text(build_lock(observed, pinned)), encoding="utf-8")
    if previous is not None:
        diff = diff_locales(previous["locales"], observed)
        print(f"faker {previous['faker_version']} -> {pinned}")
        print(render_diff(diff))
        for line in changelog_changed_lines(diff):
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--write", action="store_true", help="regenerate output_lock.json")
    ap.add_argument("--worker", action="store_true", help="one frozen-clock capture on stdout")
    ap.add_argument("--clock", help="ISO 8601 instant for --worker")
    ap.add_argument("--locales", nargs="*", help="narrow --worker to these locales (tests only)")
    ap.add_argument("--stub", help="python file the worker runs before capture (tests only)")
    args = ap.parse_args(argv)
    if args.worker:
        if not args.clock:
            ap.error("--worker needs --clock")
        print(json.dumps(run_worker_in_process(args.clock, args.locales, args.stub)))
        return 0
    if args.write:
        return write_lock()
    ap.error("choose --write or --worker")
    return 2


if __name__ == "__main__":
    sys.exit(main())
