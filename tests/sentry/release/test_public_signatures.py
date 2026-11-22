"""SIGNATURE-SENTRY: a public signature break needs a Breaking line that names it.

Between the newest release tag reachable from HEAD and the HEAD tree, every API break griffe
reports on a FROZEN or EXPERIMENTAL name must be announced by one pending Breaking line that names
the object (and, for a parameter, the parameter) in backticks. Plan:
`docs/plans/2026-11-22-signature-sentry.md`. Types and constant values are out of scope.

AT-1 to AT-7, AT-10 and AT-12 to AT-15 build a small package in a temporary git repo (tag
`v0.0.1`, then an edit) with explicit tier tables, so they do not depend on the real census.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import griffe
import pytest

from decoy_engine.contracts import stability as st
from tests.sentry.release import _census as census
from tests.sentry.release import _signatures as sig

ROOT = Path(__file__).resolve().parents[3]
STABILITY = ROOT / "src" / "decoy_engine" / "contracts" / "stability.py"
CONTRACT = (ROOT / "docs" / "compatibility-contract.md").read_text(encoding="utf-8")
F, INT = sig.FROZEN, sig.INTERNAL

# Measured on 2026-11-22 against `v0.28.3` and main: in-scope census names that map to a griffe path.
MAPPED_FLOOR = 449

BASE_FILES = {
    "src/pkg/__init__.py": (
        "from pkg.mod import Cls, dflt, f, h, pos, ren\n"
        '__all__ = ["Cls", "dflt", "f", "h", "pos", "ren"]\n'
    ),
    "src/pkg/mod.py": (
        "def f(a, b=1): ...\n"
        "def h(a): ...\n"
        "def dflt(a=1): ...\n"
        "def ren(a): ...\n"
        "def pos(a, b): ...\n"
        "class Cls:\n"
        "    def __init__(self, a): ...\n"
    ),
}
TIERS = {
    ("pkg", "f"): F,
    ("pkg", "Cls"): F,
    ("pkg", "dflt"): F,
    ("pkg", "ren"): F,
    ("pkg", "pos"): F,
    ("pkg", "h"): INT,
}
FRAGMENT = "### Changed (thing, SLICE-X, 2026-11-22)\n\nBody.\n"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603 - fixed git executable, literal arguments
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path, files: dict[str, str] | None = None, tag: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, files or BASE_FILES)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    if tag:
        git(repo, "tag", "v0.0.1")
    return repo


def sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text
    p.write_text(text.replace(old, new), encoding="utf-8")


def run(repo, work, head_tiers=None, base_tiers=None, lines=(), exemptions=()):
    """Unannounced breaks of the repo's working tree against its base tag."""
    head_tiers = TIERS if head_tiers is None else head_tiers
    tag = sig.base_tag(repo)
    base_dir = sig.extract_base(repo, tag, work / "base")
    base = sig.load_tree(base_dir / "src", "pkg")
    head = sig.load_tree(repo / "src", "pkg")
    sc = sig.scope(base, head, head_tiers if base_tiers is None else base_tiers, head_tiers)
    assert sc.unresolved == []
    return sig.unannounced(sig.signature_breaks(base, head, sc), list(lines), exemptions, tag)


def lines_of(found: list[sig.Break]) -> list[str]:
    return sorted(b.line() for b in found)


def test_at1_a_line_naming_the_function_but_not_the_parameter_announces_nothing(tmp_path) -> None:
    """The #750 shape: another line names `f`, no line names `f` and `sources` together."""
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, sources)")
    for slug, line in (
        ("one", "`other` changed"),
        ("two", "`f` gains a keyword"),
        ("three", "`sources` is new"),
    ):
        write(repo, {f"changelog.d/{slug}.md": f"Breaking: {line}\n\n{FRAGMENT}"})
    lines = sig.pending_breaking_lines(repo, "0.0.1")
    assert lines_of(run(repo, tmp_path, lines=lines)) == [
        "f: Parameter was added as required (sources)"
    ]


def test_at2_a_root_alias_spelling_with_the_parameter_announces(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, my_param)")
    assert run(repo, tmp_path, lines=["`pkg.f` now requires `my_param`"]) == []


def test_at2b_plain_text_is_not_a_name(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, sources)")
    assert len(run(repo, tmp_path, lines=["f now requires sources"])) == 1


def test_at3_an_optional_keyword_is_not_a_break(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, extra=None)")
    assert run(repo, tmp_path) == []


def test_at4_each_signature_break_kind_is_reported(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a)")
    sub(repo, "src/pkg/mod.py", "def pos(a, b)", "def pos(a, *, b)")
    sub(repo, "src/pkg/mod.py", "def dflt(a=1)", "def dflt(a=2)")
    sub(repo, "src/pkg/mod.py", "def ren(a)", "def ren(b)")
    found = run(repo, tmp_path)
    assert lines_of(found) == [
        "dflt: Parameter default was changed (a)",
        "f: Parameter was removed (b)",
        "pos: Parameter kind was changed (b)",
        "ren: Parameter was added as required (b)",
        "ren: Parameter was removed (a)",
    ]
    # a rename is announced by a line that names the function and either parameter name
    for line in ("`ren` takes `b`", "`ren` was `a`"):
        assert not [x for x in run(repo, tmp_path, lines=[line]) if x.public_names == ("ren",)]
    assert (
        len([x for x in run(repo, tmp_path, lines=["`ren` changed"]) if x.public_names == ("ren",)])
        == 2
    )


def test_at5_a_name_outside_the_scope_needs_no_line(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def h(a)", "def h(a, c)")
    assert run(repo, tmp_path) == []


def test_at6_a_release_section_announces_after_the_fragments_are_gone(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, sources)")
    write(
        repo,
        {
            "CHANGELOG.md": (
                "# Changelog\n\n## [Unreleased]\n\n"
                "## [0.0.2] - 2026-11-23\n\n### Breaking for consumers\n\n"
                "- `f` requires the keyword\n  `sources` now.\n\n### Added (x, S, 2026-11-23)\n\nx\n\n"
                "## [0.0.1] - 2026-11-01\n\n### Breaking for consumers\n\n- `f` `sources` old note\n"
            )
        },
    )
    lines = sig.pending_breaking_lines(repo, "0.0.1")
    assert lines == ["`f` requires the keyword `sources` now."]
    assert run(repo, tmp_path, lines=lines) == []


def test_at6b_a_breaking_list_under_unreleased_is_refused(tmp_path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo,
        {
            "CHANGELOG.md": "# C\n\n## [Unreleased]\n\n### Breaking for consumers\n\n- `f` x\n\n"
            "## [0.0.1] - 2026-11-01\n\nx\n"
        },
    )
    with pytest.raises(AssertionError, match="changelog.d fragment"):
        sig.pending_breaking_lines(repo, "0.0.1")


def test_at7_a_constructor_parameter_and_a_removed_root_name(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def __init__(self, a)", "def __init__(self, a, z)")
    sub(repo, "src/pkg/__init__.py", ' "f",', "")
    sub(repo, "src/pkg/__init__.py", "f, h", "h")
    found = run(
        repo, tmp_path, head_tiers={k: v for k, v in TIERS.items() if k[1] != "f"}, base_tiers=TIERS
    )
    assert lines_of(found) == [
        "Cls: Parameter was added as required (z)",
        "f: Public object was removed",
    ]


def test_at10_no_reachable_tag_fails_with_the_fetch_message(tmp_path) -> None:
    repo = make_repo(tmp_path, tag=False)
    with pytest.raises(AssertionError, match="needs the release tags"):
        sig.base_tag(repo)


def test_at12_a_class_whose_runtime_module_is_rewritten_is_still_in_scope(
    tmp_path, monkeypatch
) -> None:
    files = {
        "src/pkg/__init__.py": "from pkg._base import Cls\n__all__ = ['Cls']\n",
        "src/pkg/_base.py": "class Cls:\n    def __init__(self, a): ...\nCls.__module__ = 'pkg.errors'\n",
    }
    repo = make_repo(tmp_path, files)
    sub(repo, "src/pkg/_base.py", "(self, a)", "(self, a, new)")
    monkeypatch.syspath_prepend(str(repo / "src"))
    for name in [n for n in sys.modules if n == "pkg" or n.startswith("pkg.")]:
        monkeypatch.delitem(sys.modules, name)
    found = run(repo, tmp_path, head_tiers={("pkg", "Cls"): F})
    assert lines_of(found) == ["Cls: Parameter was added as required (new)"]


def test_at13_a_leftover_griffe_branch_and_worktree_do_not_matter(tmp_path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "branch", "griffe-v0-0-1")
    git(repo, "worktree", "add", "-q", str(tmp_path / "stale"), "griffe-v0-0-1")
    (tmp_path / "stale" / ".git").unlink()  # the worktree entry stays, its directory is broken
    sub(repo, "src/pkg/mod.py", "def f(a, b=1)", "def f(a, b=1, *, sources)")

    def state() -> tuple[str, str]:
        return git(repo, "branch", "--list", "griffe-*"), git(repo, "worktree", "list")

    before = state()
    assert len(run(repo, tmp_path)) == 1
    assert state() == before


def test_at14_dropping_the_tier_and_breaking_the_name_in_one_diff_is_caught(tmp_path) -> None:
    files = {
        "src/pkg/__init__.py": "",
        "src/pkg/sub/__init__.py": "from pkg.sub._g import g\n__all__ = ['g']\n",
        "src/pkg/sub/_g.py": "def g(a): ...\n",
    }
    repo = make_repo(tmp_path, files)
    sub(repo, "src/pkg/sub/_g.py", "def g(a)", "def g(a, extra)")
    base = {("pkg.sub", "g"): F}
    found = run(repo, tmp_path, head_tiers={("pkg.sub", "g"): INT}, base_tiers=base)
    assert lines_of(found) == ["g: Parameter was added as required (extra)"]


def test_at15_an_exemption_row_silences_only_at_its_base_tag(tmp_path) -> None:
    repo = make_repo(tmp_path)
    sub(repo, "src/pkg/mod.py", "def dflt(a=1)", "def dflt(a=_ONE)")
    write(repo, {"src/pkg/mod.py": "_ONE = 1\n" + (repo / "src/pkg/mod.py").read_text("utf-8")})
    row = sig.Exemption("v0.0.1", "pkg.mod.dflt", "PARAMETER_CHANGED_DEFAULT", "a", "same value")
    assert run(repo, tmp_path, exemptions=(row,)) == []
    stale = sig.Exemption("v0.0.0", row.path, row.kind, row.parameter, row.reason)
    assert lines_of(run(repo, tmp_path, exemptions=(stale,))) == [
        "dflt: Parameter default was changed (a)"
    ]


def test_at16_every_griffe_kind_is_a_decision() -> None:
    assert set(griffe.BreakageKind) == sig.IN_SCOPE_KINDS | sig.EXCLUDED_KINDS
    assert not sig.IN_SCOPE_KINDS & sig.EXCLUDED_KINDS


# --- the real repository ---------------------------------------------------------------------


V0_28_3_BREAKING = [
    "`date_shift` on a number, boolean or decimal column (for example an `int64` holding `20240115` with a `date_format`) is now refused at compile; write the column as text first.",
    "a stored plan from an older engine is refused until you compile it again, and every profile hash changes once.",
    "`bucket_perturb` no longer passes source values through. When no `date_format` is set and the engine cannot detect one from the cells, the run now stops with `bucket_perturb_requires_date_format` instead of writing the column unchanged. A non-null cell that does not parse under the format is now a `format_error` row error, as it is for `date_shift`, so the run fails or quarantines the row instead of keeping the source text. A date outside pandas' range (before 1677 or after 2262, such as the sentinel 9999-12-31) is now a row error too; `preserve_values` keeps such a sentinel unchanged. Set `provider_config.date_format` (for example `%Y-%m-%d`) and fix or quarantine bad cells.",
    "a vault written by this engine is `decoy-vault/v3`, which an older engine cannot open; keep the older engine's vaults for it or re-run the mask.",
    "windowed_date produces different dates for the same seed (output-changing, pre-GA).",
]


def _tiers(tree_root: Path, tree) -> sig.Tiers:
    source = (tree_root / "src/decoy_engine/contracts/stability.py").read_text(encoding="utf-8")
    return sig.tiers_from_tree(tree, source)


def test_at8_the_0_28_3_break_the_gates_missed_is_found(tmp_path) -> None:
    """Fail-before proof: base `v0.28.2`, head `v0.28.3`, the Breaking list as released."""
    a = sig.extract_base(ROOT, "v0.28.2", tmp_path / "a")
    b = sig.extract_base(ROOT, "v0.28.3", tmp_path / "b")
    base, head = sig.load_tree(a / "src", "decoy_engine"), sig.load_tree(b / "src", "decoy_engine")
    sc = sig.scope(base, head, _tiers(a, base), _tiers(b, head))
    assert sc.unresolved == []
    found = lines_of(
        sig.unannounced(sig.signature_breaks(base, head, sc), V0_28_3_BREAKING, (), "v0.28.2")
    )
    assert "compile_plan: Parameter was added as required (sources)" in found
    assert "VaultWriter: Parameter was added as required (prepared)" in found
    assert "VaultWriter: Parameter was removed (mask_key)" in found


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    tag = sig.base_tag(ROOT)
    dest = sig.extract_base(ROOT, tag, tmp_path_factory.mktemp("base"))
    base = sig.load_tree(dest / "src", "decoy_engine")
    head = sig.load_tree(ROOT / "src", "decoy_engine")
    exports, _ = census.load()
    head_tiers = census.classify(exports)
    base_tiers = _tiers(dest, base)
    return tag, base, head, sig.scope(base, head, base_tiers, head_tiers)


def test_head_breaks_are_announced(live) -> None:
    """The guard: every break since the last release tag has a Breaking line that names it."""
    tag, base, head, sc = live
    assert sc.unresolved == [], f"in-scope names griffe cannot map: {sc.unresolved}"
    assert sc.mapped >= MAPPED_FLOOR, f"only {sc.mapped} in-scope names mapped"
    lines = sig.pending_breaking_lines(ROOT, tag.removeprefix("v"))
    left = sig.unannounced(
        sig.signature_breaks(base, head, sc),
        lines,
        sig.exemptions_from(sig.SIGNATURE_EXEMPTIONS),
        tag,
    )
    assert not left, (
        "\n".join(sorted({b.line() for b in left}))
        + "\nadd a `Breaking:` line naming the object and the parameter in backticks "
        "to your changelog.d fragment"
    )


def test_the_base_registry_reader_takes_the_real_file_and_refuses_a_call() -> None:
    source = STABILITY.read_text(encoding="utf-8")
    reg = sig.parse_stability(source)
    assert reg.package_tiers == st.PACKAGE_TIERS
    assert reg.exceptions == {(m, n): t for m, n, t in st.TIER_EXCEPTIONS}
    assert reg.experimental_objects == frozenset(st.EXPERIMENTAL_OBJECTS)
    header = "TIER_EXCEPTIONS: Final[tuple[tuple[str, str, str], ...]] = ("
    assert header in source
    with pytest.raises(ValueError, match="non-literal"):
        sig.parse_stability(source.replace(header, "TIER_EXCEPTIONS: Final = tuple(", 1))


def test_at11_plan_exports_the_compile_argument_with_a_tier() -> None:
    import decoy_engine.plan as plan
    from decoy_engine.contracts import column_shape

    assert plan.NO_SOURCES is column_shape.NO_SOURCES
    assert plan.SourceFacts is column_shape.SourceFacts
    tiers = census.classify(census.load()[0])
    assert tiers[("decoy_engine.plan", "NO_SOURCES")] == st.FROZEN
    assert tiers[("decoy_engine.plan", "SourceFacts")] == st.EXPERIMENTAL
    assert "decoy_engine.plan.NO_SOURCES" in CONTRACT
    assert "SourceFacts" in CONTRACT
