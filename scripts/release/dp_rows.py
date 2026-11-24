"""How a DP certified row is computed, and how release prep writes it into `quality/dp_certified_stacks.py`.

One fact lives here: a certified row is `compute_lock_fingerprint` over a distribution set. Two
profiles earn a row per engine release:

* the dev/CI row, from `uv.lock` alone (`uv export`, PEP 508 markers evaluated for the certified
  platform) plus the engine version being released;
* a CLI-profile row, from a `requirements-certified.txt`, the engine version and the CLI version
  (the CLI's own distribution joins the set, as `scripts/cert_smoke.py` sees it).

`tests/sentry/test_dp_lock_row.py` uses the same functions to check the lock, and
`scripts/release/stamp_release.py` uses them to write the rows at release prep. Every refusal is a
`DpRowError` whose message names a file label, line numbers and package names, never file content.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CLI_BLOCK_MARK = "# decoy-cli pristine RUNTIME profile"
_BOOTSTRAP = re.compile(r"EXTRAS=\((--extra \w+(?: --extra \w+)*)\)")
NEED_UV = "uv is required on every gate host to check the lock against the certified DP rows"
ENGINE = "decoy-engine"
CLI = "decoy-cli"
_HASH_LINE = re.compile(r'^(\s+)"([0-9a-f]{64})",\s*$')


class DpRowError(ValueError):
    """A refusal; the message carries no file content."""


def target_env(python_full: str) -> dict[str, str]:
    """Every PEP 508 key, fixed to the certified platform; nothing falls through from the host."""
    return {
        "implementation_name": "cpython",
        "implementation_version": python_full,
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "platform_python_implementation": "CPython",
        "python_version": python_full.rsplit(".", 1)[0],
        "python_full_version": python_full,
        "sys_platform": "linux",
    }


def lock_profile_python(root: Path) -> str:
    """The CPython patch of the lock profile, from the one shell reader of it."""
    script = root / "scripts" / "dev" / "lock_version.sh"
    run = subprocess.run(  # noqa: S603 -- static argv (bash + repo script)
        ["bash", str(script), "--python"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    out = run.stdout.strip()
    if run.returncode != 0 or not re.fullmatch(r"\d+\.\d+\.\d+", out):
        raise DpRowError("lock_version.sh --python did not name a CPython patch")
    return out


def bootstrap_extras(text: str) -> list[str]:
    """The extras bootstrap.sh syncs: the certified dev/CI profile."""
    line = next((ln for ln in text.splitlines() if "EXTRAS=(" in ln), "")
    match = _BOOTSTRAP.fullmatch(line)
    if match is None:
        raise DpRowError("bootstrap.sh EXTRAS declaration is not exactly --extra <name> items")
    return sorted(match.group(1).replace("--extra ", "").split())


def _canonical(name: str) -> str:
    from packaging.utils import canonicalize_name

    return str(canonicalize_name(name))


def _marker_ok(marker: str, env: dict[str, str]) -> bool:
    from packaging.markers import Marker

    return not marker or Marker(marker).evaluate(env)


def profile_pins(
    root: Path, extras: list[str], python_full: str, uv: str | None
) -> set[tuple[str, str]]:
    """What `uv export` of the lock selects on the certified platform; the engine is not in it."""
    if not uv:
        raise DpRowError(NEED_UV)
    flags = [f for e in extras for f in ("--extra", e)]
    cmd = [uv, "export", "--frozen", "--no-emit-project", "--no-hashes", "--no-header", *flags]
    run = subprocess.run(  # noqa: S603 -- uv from which(), static flags
        cmd, cwd=root, capture_output=True, text=True, check=False
    )
    if run.returncode != 0:
        raise DpRowError("uv export of uv.lock failed")
    env = target_env(python_full)
    pins: set[tuple[str, str]] = set()
    for line in run.stdout.splitlines():
        if not line or line.startswith((" ", "#")):
            continue
        spec, _, marker = line.partition(" ; ")
        if not _marker_ok(marker, env):
            continue
        name, _, version = spec.partition("==")
        pins.add((_canonical(name), version))
    return pins


def _project_version(root: Path) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def _fingerprint(pins: set[tuple[str, str]]) -> str:
    from decoy_engine.quality import dp_provenance

    return dp_provenance.compute_lock_fingerprint(pins)


def profile_fingerprint(root: Path, extras: list[str], python_full: str, uv: str | None) -> str:
    """The dev/CI row of the lock at the engine version pyproject.toml names."""
    pins = profile_pins(root, extras, python_full, uv)
    return _fingerprint({*pins, (ENGINE, _project_version(root))})


def dev_row(root: Path, engine_version: str, uv: str | None = None) -> str:
    """The dev/CI row of `uv.lock` for `engine_version`."""
    extras = bootstrap_extras((root / "scripts/dev/bootstrap.sh").read_text(encoding="utf-8"))
    py = lock_profile_python(root)
    pins = profile_pins(root, extras, py, uv or shutil.which("uv"))
    return _fingerprint({*pins, (ENGINE, engine_version)})


def _read(label: str, path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise DpRowError(f"{label}: cannot read the pin file") from None


def checked_pins(label: str, text: str, python_full: str) -> dict[str, str]:
    """canonical name -> version of a certified pin file, for the certified platform.

    Refuses a file `sbom_checks` does not read as plain `name==version [; marker]` lines, and a name
    that two applicable lines pin to different versions.
    """
    from scripts.release import sbom_checks

    bad = sbom_checks.pin_violations(text, require_hashes=False, allow_comments=True)
    if bad:
        raise DpRowError(f"{label}: not a pin file, lines {', '.join(map(str, bad[:5]))}")
    if sbom_checks.requirement_violations(text):
        raise DpRowError(f"{label}: a requirement is not exactly name==version")
    env = target_env(python_full)
    out: dict[str, str] = {}
    for name, version, line in sbom_checks.pins(text):
        if not _marker_ok(line.partition(" ; ")[2], env):
            continue
        key = _canonical(name)
        if key in (ENGINE, CLI):
            raise DpRowError(f"{label}: names {key}, which the row adds itself")
        if out.setdefault(key, version) != version:
            raise DpRowError(f"{label}: {key} is pinned to two versions")
    if not out:
        raise DpRowError(f"{label}: no pins apply to the certified platform")
    return out


def base_closure(root: Path, python_full: str, uv: str | None) -> set[str]:
    """Canonical names the engine installs with no extra: its base requirements and their closure.

    A CLI runtime installs the engine plus these, so a certified CLI pin file that lacks one names
    a set the real install never has (the 0.28.0 row was stamped without `joserfc` and `rfc8785`).
    """
    return {name for name, _ in profile_pins(root, [], python_full, uv)}


def cli_rows(
    base: Path,
    candidates: list[Path],
    engine_version: str,
    cli_version: str,
    python_full: str,
    allow_delta: list[str],
    closure: set[str],
) -> list[str]:
    """One row per candidate pin file, each refused unless its package names match `base` and it
    covers `closure`, the engine's own base-requirements closure from `uv.lock`."""
    reference = set(checked_pins("--cli-pins-base", _read("--cli-pins-base", base), python_full))
    allowed = {_canonical(n) for n in allow_delta}
    rows: list[str] = []
    for i, path in enumerate(candidates, 1):
        label = f"--cli-pins #{i}"
        pins = checked_pins(label, _read(label, path), python_full)
        delta = sorted((reference ^ set(pins)) - allowed)
        if delta:
            raise DpRowError(f"{label}: package names differ from the base: {', '.join(delta)}")
        missing = sorted(closure - set(pins))
        if missing:
            raise DpRowError(f"{label}: lacks the engine's base requirements: {', '.join(missing)}")
        rows.append(_fingerprint({*pins.items(), (ENGINE, engine_version), (CLI, cli_version)}))
    return rows


def _body(lines: list[str], key: str) -> tuple[int, int, int]:
    """(first line of the set body, one past its last, line of the decoy-cli marker)."""
    head = f'"{key}": frozenset('
    starts = [i for i, ln in enumerate(lines) if ln.strip() == head]
    if len(starts) != 1:
        raise DpRowError(f"dp_certified_stacks has no single {key} row set")
    begin = starts[0] + 2
    end = next((i for i in range(begin, len(lines)) if lines[i].strip() == "}"), -1)
    marks = [i for i in range(begin, end) if lines[i].lstrip().startswith(CLI_BLOCK_MARK)]
    if end < 0 or len(marks) != 1:
        raise DpRowError(f"the {key} row set does not have exactly one decoy-cli block")
    return begin, end, marks[0]


def rows_in(text: str, key: str) -> list[str]:
    """Every row of one set, in file order."""
    lines = text.split("\n")
    begin, end, _ = _body(lines, key)
    return [m[2] for ln in lines[begin:end] if (m := _HASH_LINE.match(ln))]


def insert_rows(text: str, key: str, dev: list[str], cli: list[str]) -> str:
    """`text` with the rows added at the top of their blocks, newest first; present rows are
    skipped, so a second call adds nothing and no existing row is ever removed or reordered."""
    lines = text.split("\n")
    begin, end, mark = _body(lines, key)
    have = {m[2] for ln in lines[begin:end] if (m := _HASH_LINE.match(ln))}

    def fresh(rows: list[str]) -> list[str]:
        out: list[str] = []
        for row in rows:
            if row not in have and row not in out:
                out.append(row)
        return out

    for rows, lo, hi in ((fresh(cli), mark, end), (fresh(dev), begin, mark)):
        top = next((i for i in range(lo, hi) if _HASH_LINE.match(lines[i])), -1)
        if top < 0:
            raise DpRowError(f"the {key} row set has no row to insert above")
        indent = _HASH_LINE.match(lines[top]).group(1)  # type: ignore[union-attr]
        lines[top:top] = [f'{indent}"{row}",' for row in rows]
        have.update(rows)
    return "\n".join(lines)


def plan_rows(
    root: Path,
    text: str,
    engine_version: str,
    cli_version: str,
    base: Path,
    candidates: list[Path],
    allow_delta: list[str],
) -> str:
    """The new text of dp_certified_stacks.py with this release's rows, or a `DpRowError`."""
    py = lock_profile_python(root)
    key = f"{py}.final"
    closure = base_closure(root, py, shutil.which("uv"))
    cli = cli_rows(base, candidates, engine_version, cli_version, py, allow_delta, closure)
    new = insert_rows(text, key, [dev_row(root, engine_version)], cli)
    old_rows, new_rows = rows_in(text, key), rows_in(new, key)
    if [r for r in new_rows if r in old_rows] != old_rows:
        raise DpRowError("the row set lost or reordered a certified row")
    return new
