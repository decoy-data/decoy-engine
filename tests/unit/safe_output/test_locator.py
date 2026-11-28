"""AT-1 to AT-4 and AT-8 of the locator plan: one recognizer decides what a locator shows.

The case table is `tests/fixtures/locator_credentials/cases.json`; the CLI vendors a copy
pinned by hash. Rows use the synthetic secret `CANARY`. Hypothesis runs with a fixed seed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import decoy_engine
from decoy_engine import safe_output
from decoy_engine._locator import _ID_SCHEMES
from decoy_engine.safe_output import LocatorKind, LocatorScan, scan_locator

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "locator_credentials" / "cases.json").read_text(
        encoding="utf-8"
    )
)
REDACTED = "<redacted>"
FIXED = settings(
    max_examples=300,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["id"] for r in rows]


def test_the_table_has_the_planned_rows() -> None:
    assert len(CASES) == 59
    assert len(set(_ids(CASES))) == 59


@pytest.mark.parametrize("row", CASES, ids=_ids(CASES))
def test_row_matches_the_table(row: dict[str, Any]) -> None:
    """AT-1: kind, shown, carries and published for every row."""
    scan = scan_locator(row["input"])
    assert scan.kind.value == row["kind"]
    assert scan.shown == row["shown"]
    assert scan.carries_credentials is row["carries"]
    assert scan.published == row["origin_shown"]


@pytest.mark.parametrize("row", CASES, ids=_ids(CASES))
def test_row_never_publishes_the_secret(row: dict[str, Any]) -> None:
    scan = scan_locator(row["input"])
    assert "CANARY" not in (scan.published or "")
    if scan.carries_credentials:
        assert "CANARY" not in scan.shown


def _is_span_replacement(original: str, shown: str) -> bool:
    """`shown` is `original` with zero or more spans replaced by the marker (P1)."""
    pieces = shown.split(REDACTED)
    if len(pieces) == 1:
        return original == shown
    tail = pieces[-1]
    if not original.startswith(pieces[0]) or not original.endswith(tail):
        return False
    pos = len(pieces[0])
    for piece in pieces[1:-1]:
        # Each marker stands for at least one replaced character.
        found = original.find(piece, pos + 1)
        if found < 0:
            return False
        pos = found + len(piece)
    return len(original) - len(tail) >= pos + 1


FRAGMENTS = [
    "://",
    ":/",
    ":\\",
    "//",
    "\\\\",
    "@",
    ":",
    "/",
    "\\",
    "?",
    "#",
    "'",
    " ",
    "\t",
    "=",
    "<",
    "CANARY",
    "h",
    "a",
    "x",
    "s3",
    "https",
    "sftp",
    "abfss",
    "C",
    ".",
    "u",
    "%40",
    "[::1]",
    "8080",
    REDACTED,
] + [r["input"] for r in CASES]
INPUTS = st.lists(st.sampled_from(FRAGMENTS), max_size=9).map("".join) | st.text(max_size=40)


@pytest.mark.parametrize("row", CASES, ids=_ids(CASES))
def test_p1_to_p3_over_rows(row: dict[str, Any]) -> None:
    _check_properties(row["input"])


@FIXED
@given(INPUTS)
def test_p1_to_p3_over_generated_inputs(text: str) -> None:
    _check_properties(text)


def _check_properties(text: str) -> None:
    scan = scan_locator(text)
    assert isinstance(scan, LocatorScan)
    # P3: the detector and the redactor cannot disagree.
    assert scan.carries_credentials == (scan.shown != text)
    # P1: text outside a replaced span never changes (no case folding, no separator rewrite).
    assert _is_span_replacement(text, scan.shown)
    # P2: showing a shown value again changes nothing.
    again = scan_locator(scan.shown)
    assert again.shown == scan.shown
    assert again.carries_credentials is False


SCHEMES = st.sampled_from(["https", "s3", "sftp", "abfss", "gs", "postgresql+psycopg", "x3"]) | (
    st.from_regex(r"[A-Za-z][A-Za-z0-9+.-]{1,6}", fullmatch=True)
)
SECRET_CHARS = st.text(alphabet="abcXYZ019?#/\\'@:", max_size=12)
SECRETS = SECRET_CHARS.map(lambda s: "CANARY" + s)
_RAW_DELIMS = str.maketrans({"/": "%2F", "?": "%3F", "#": "%23", "\\": "%5C"})


def _templates(scheme: str, s: str) -> list[str]:
    """Credential positions of the plan's P4. The user-only token has its raw delimiters
    percent-encoded: a raw `/` there would put the secret in the host, outside userinfo."""
    out = [
        f"{scheme}://u:{s}@h/a",
        f"//svc:{s}@host/key",
        f"x://svc:{s}@host/key",
        f"dsn={scheme}://u:{s}@h/a",
        f"{scheme}://h/a?t={s}",
        f"{scheme}://h/My Report.csv?sig={s}",
        f"{scheme}://h/a#{s}",
    ]
    if scheme.lower() not in _ID_SCHEMES:
        out.append(f"{scheme}://{s.translate(_RAW_DELIMS)}@h/a")
    return out


@FIXED
@given(SCHEMES, SECRETS)
def test_p4_a_secret_never_survives_any_template(scheme: str, s: str) -> None:
    for text in _templates(scheme, s):
        scan = scan_locator(text)
        assert "CANARY" not in scan.shown, text
        assert "CANARY" not in (scan.published or ""), text
        assert scan.carries_credentials is True, text


@pytest.mark.parametrize("row", CASES, ids=_ids(CASES))
def test_a_trailing_newline_does_not_change_the_decision(row: dict[str, Any]) -> None:
    """Class 1: whole-value matching, so `value + newline` is judged as its own text."""
    scan = scan_locator(row["input"] + "\n")
    assert scan.carries_credentials == (scan.shown != row["input"] + "\n")
    if row["carries"]:
        assert "CANARY" not in scan.shown


def test_a_valid_host_does_not_match_with_a_trailing_newline() -> None:
    assert scan_locator("https://h/a\n").carries_credentials is False
    assert scan_locator("https://h\n").carries_credentials is True  # newline is not a host char


def test_the_result_is_frozen_and_never_raises() -> None:
    scan = scan_locator("s3://b/k")
    with pytest.raises(AttributeError):
        scan.shown = "x"  # type: ignore[misc]
    for odd in ("\x00", "\ud800", "https://", "//", "\\\\", "C:", "x://", "?", "#", "@", "://"):
        assert isinstance(scan_locator(odd).kind, LocatorKind)


def test_at_8_public_names() -> None:
    """The three names live on `safe_output`, not on the root package (PROP-SURFACE)."""
    for name in ("scan_locator", "LocatorScan", "LocatorKind"):
        assert name in safe_output.__all__
        assert name not in decoy_engine.__all__
    assert not hasattr(decoy_engine, "scan_locator")


def test_the_known_remote_set_is_not_a_second_copy() -> None:
    src = Path(decoy_engine.__file__).parent
    hits = [
        p.name
        for p in src.rglob("*.py")
        if p.name != "_locator.py" and re.search(r"\babfss\b.*\bwasbs\b", p.read_text("utf-8"))
    ]
    assert hits == []


@pytest.mark.serial
@pytest.mark.parametrize(
    "text",
    ["a:" * 4000, "a:b" * 2700, ("x:" * 3 + "/") * 1300, "a" * 8000 + ":"],
    ids=["colons", "pairs", "segments", "one-run"],
)
def test_long_input_scans_in_linear_time(text: str) -> None:
    """The scp-shape check must not backtrack over a long segment (8k chars)."""
    start = time.perf_counter()
    scan_locator(text)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize(
    ("text", "published"),
    [
        ("svc:CANARY@host:/data", None),
        ("a:b@c", None),
        ("a::b@c", "a::b@c"),
        (":b@c", ":b@c"),
        ("/tmp/a:b@c", None),
        ("ab:c d@e", "ab:c d@e"),
        ("a:b/c@d", "a:b/c@d"),
    ],
)
def test_scp_shape_is_one_segment(text: str, published: str | None) -> None:
    assert scan_locator(text).published == published
