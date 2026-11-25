"""AT-6: `decoy_engine/_locator.py` is the only module that parses locator text.

A second parser for `://`, `//`, `\\\\`, `@` or URL userinfo is a second answer to "does this
locator carry credentials", which is how two PRs leaked one after the other. The walk
(`_locator_scan.py`) lists every site outside `_locator.py` that parses those marks; the
baseline `locator-grammar` holds the reviewed sites, each with a reason. A new site fails here
and needs a reasoned, owner-dated entry. Entries only shrink (merge-base ratchet).

This is a tripwire for the spellings written by habit, not a proof. The runtime half is the
canary surface tests that run every credential row of the case table through each routed surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.sentry import _baseline_sources
from tests.sentry.safe_output._locator_scan import EXEMPT, scan_source, scan_tree

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
BASELINE = _baseline_sources.baseline_path("locator-grammar")


def _baseline() -> set[str]:
    return set(json.loads(BASELINE.read_text(encoding="utf-8"))["entries"])


def test_the_tree_has_no_unreviewed_locator_parser() -> None:
    unreviewed = sorted(scan_tree(SRC) - _baseline())
    assert unreviewed == [], f"locator text parsed outside _locator.py: {unreviewed}"


def test_a_removed_site_leaves_a_stale_entry() -> None:
    live = scan_tree(SRC)
    some = sorted(live)[0]
    assert (live - {some}) != _baseline(), "deleting a site must make its entry stale"
    assert _baseline() - (live - {some}) == {some}


def test_every_entry_carries_a_reason() -> None:
    for key, entry in json.loads(BASELINE.read_text(encoding="utf-8"))["entries"].items():
        assert len(entry["reason"]) >= 15, key


# Each seed is a spelling from the plan (section 5); every one must produce a site the baseline
# does not hold.
SEEDS = {
    "in-operator": 'def f(text):\n    if "@" in text:\n        return 1\n',
    "regex-literal": 'import re\nre.compile(r"[a-z]+://")\n',
    "regex-constant": 'import re\n_SEP = "://"\nre.compile("[a-z]+" + _SEP)\n',
    "regex-alias": 'import re as r\nr.sub(r"[^@]+@", "", t)\n',
    "regex-from-alias": 'from re import sub as s\ns(r"[^@]+@", "", t)\n',
    "urlsplit-alias": "from urllib.parse import urlsplit as u\nu(t).netloc\n",
    "unbound-method": 'str.partition(t, "@")\n',
    "equality": 'if t[:2] == "//":\n    pass\n',
    "tuple-literal": '_MARKS = ("@", "?", "#")\n',
    "set-literal": 'any(m in t for m in {"://", "@"})\n',
    "method-constant": '_AT = "@"\nt.rpartition(_AT)\n',
    "startswith": 'u.startswith("s3://")\n',
    "split-colon-slash": 'u.split(":/")\n',
    "backslash-pair": 'u.find("\\\\\\\\")\n',
    "f-string-regex": 'import re\n_H = "//"\nre.search(f"x{_H}y", t)\n',
    "urlparse": "import urllib.parse as up\nup.urlparse(t)\n",
    "username-attr": "cfg.username\n",
    "yarl": "import yarl\nyarl.URL(t)\n",
    "furl-from": "from furl import furl\nfurl(t)\n",
    "rfc3986": "import rfc3986\nrfc3986.urlparse(t)\n",
}


@pytest.mark.parametrize("name", sorted(SEEDS))
def test_a_seeded_parser_is_flagged(name: str) -> None:
    keys = scan_source(SEEDS[name], "scratch.py")
    assert keys, f"{name}: the walk saw nothing"
    assert keys - _baseline() == keys


def test_a_seeded_module_in_a_tree_turns_the_walk_red(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "scratch.py").write_text(SEEDS["in-operator"], encoding="utf-8")
    assert scan_tree(tmp_path) - _baseline()


def test_the_recognizer_is_exempt_and_would_otherwise_be_flagged() -> None:
    text = (SRC / EXEMPT).read_text(encoding="utf-8")
    assert scan_source(text, EXEMPT), "the exemption would hide nothing"
    assert not any(k.startswith(f"{EXEMPT}::") for k in scan_tree(SRC))


def test_clean_code_is_not_flagged() -> None:
    assert scan_source("x = a.split(',')\nif name == 'id':\n    pass\n", "ok.py") == set()


def test_a_recognizer_caller_is_not_a_parser() -> None:
    src = "from decoy_engine._locator import scan_locator\nscan_locator(t).shown\n"
    assert scan_source(src, "ok.py") == set()
