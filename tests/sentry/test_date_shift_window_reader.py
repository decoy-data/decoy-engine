"""Sentry: only the date_shift resolver reads a date_shift window key.

`transforms/date_shift.py` owns `shift_window` and `shift_window_problem`. Every other module that
spells `"min_days"`, `"max_days"` or `"jitter_days"` as a string is on the census below, each with
the reason it is not a date_shift window read. The census may only shrink: an entry with no
remaining hit fails, and a new hit outside the census fails. A new date_shift route reads its
window through the resolver, or adds an entry here that a reviewer has to approve.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
KEYS = frozenset({"min_days", "max_days", "jitter_days"})

# (path below src/decoy_engine, enclosing function or class or None for the whole file) -> reason.
CENSUS: dict[tuple[str, str | None], str] = {
    ("transforms/date_shift.py", None): "the date_shift resolver and validator",
    (
        "execution/_strategies/_date_shift.py",
        "DateShiftStrategyHandler",
    ): "wizard option defaults, not a window read",
    ("profiling/recommendations.py", None): "recommendation descriptors, not a window read",
    ("transforms/windowed_date.py", None): "windowed_date config, a different strategy",
    ("generation/_column_streams.py", None): "windowed_date generation stream",
    ("generation/_grouped_windowed_generators.py", None): "grouped windowed_date generation",
    ("generation/_window_admission.py", None): "windowed_date anchor admission",
    ("config/_generate_options.py", None): "generate column option schema",
    ("plan/checks/_generate_columns.py", None): "generate column option parsing",
    (
        "execution/_strategies/_text_mask.py",
        None,
    ): "text_mask per-span bounds (TEXT-MASK-DATE-BOUNDS)",
    ("transforms/text_mask.py", None): "text_mask per-span bounds (TEXT-MASK-DATE-BOUNDS)",
    ("execution/out_of_core/_text_mask_native.py", None): "text_mask per-span bounds",
    ("execution/out_of_core/_mask_group_c.py", "_text_mask_array"): "text_mask per-span bounds",
    (
        "execution/native/_operator_params.py",
        "resolve_operator_params",
    ): "the text_mask branch; the date_shift branch calls shift_window",
}

# `resolve_operator_params` holds the text_mask literal and the date_shift branch in one function.
# The text_mask branch reads both keys once, so any further literal there is a date_shift read.
MAX_HITS: dict[tuple[str, str | None], int] = {
    ("execution/native/_operator_params.py", "resolve_operator_params"): 2,
}


class _Hits(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[tuple[int, str]] = []

    def _scope(self, node: ast.AST) -> None:
        self.stack.append(getattr(node, "name", "?"))
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _scope  # noqa: N815
    visit_AsyncFunctionDef = _scope  # noqa: N815
    visit_ClassDef = _scope  # noqa: N815

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value in KEYS:
            self.hits.append((node.lineno, ".".join(self.stack)))


def _allowed(rel: str, scope: str) -> tuple[str, str | None] | None:
    if (rel, None) in CENSUS:
        return (rel, None)
    if (rel, scope) in CENSUS:
        return (rel, scope)
    return None


def offences(
    root: Path,
) -> tuple[list[str], set[tuple[str, str | None]], dict[tuple[str, str | None], int]]:
    """Reads outside the census, the census entries that were hit, and each entry's hit count."""
    found: list[str] = []
    used: set[tuple[str, str | None]] = set()
    counts: dict[tuple[str, str | None], int] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        visitor = _Hits()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for lineno, scope in visitor.hits:
            key = _allowed(rel, scope)
            if key is None:
                found.append(f"{rel}:{lineno} ({scope or 'module'})")
            else:
                used.add(key)
                counts[key] = counts.get(key, 0) + 1
    return found, used, counts


def test_no_date_shift_window_read_outside_the_resolver() -> None:
    found, used, counts = offences(SRC)
    assert found == [], (
        "a date_shift window key is read outside transforms/date_shift.py; call shift_window "
        f"instead: {found}"
    )
    stale = sorted(str(k) for k in CENSUS if k not in used)
    assert stale == [], f"census entries with no remaining hit (remove them): {stale}"
    for key, limit in MAX_HITS.items():
        assert counts[key] <= limit, f"{key} reads more window keys than its text_mask branch"


def test_the_sentry_catches_a_planted_read(tmp_path: Path) -> None:
    probe = tmp_path / "transforms" / "date_shift_probe.py"
    probe.parent.mkdir()
    probe.write_text('def f(cfg):\n    return cfg.get("min_days", -365)\n', encoding="utf-8")
    found, _, _ = offences(tmp_path)
    assert found == ["transforms/date_shift_probe.py:2 (f)"]


def test_the_sentry_catches_a_planted_read_beside_an_allowed_scope(tmp_path: Path) -> None:
    probe = tmp_path / "execution" / "native" / "_operator_params.py"
    probe.parent.mkdir(parents=True)
    probe.write_text('def other(cfg):\n    return cfg.get("jitter_days")\n', encoding="utf-8")
    found, _, _ = offences(tmp_path)
    assert found == ["execution/native/_operator_params.py:2 (other)"]
