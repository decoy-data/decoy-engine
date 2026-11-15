"""OSS.3: pin the publishable pyproject.toml metadata for decoy-engine.

Mirror of the test in `decoy/tests/unit/test_pyproject_metadata.py`,
narrowed to the engine's contract.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


def _load() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_distribution_name_is_decoy_engine() -> None:
    """Q-OSS-1 RESOLVED 2026-06-01: engine dist stays `decoy-engine`."""
    data = _load()
    assert data["project"]["name"] == "decoy-engine"


def test_license_is_fsl_1_1_alv2() -> None:
    """Engine and CLI share FSL-1.1-ALv2; each version becomes Apache-2.0 two years after release."""
    data = _load()
    assert data["project"]["license"] == "FSL-1.1-ALv2"
    assert data["project"]["license-files"] == ["LICENSE", "NOTICE"]


def test_classifiers_cover_python_3_10_3_11_3_12() -> None:
    """The engine supports the same Python matrix as the CLI."""
    data = _load()
    classifiers = set(data["project"]["classifiers"])
    for version in ("3.10", "3.11", "3.12"):
        cls = f"Programming Language :: Python :: {version}"
        assert cls in classifiers, f"missing Trove classifier {cls!r}"


def test_classifiers_do_not_claim_osi_approval() -> None:
    """FSL is source-available, not OSI-approved, and has no Trove classifier of its own."""
    data = _load()
    classifiers = data["project"]["classifiers"]
    assert "License :: Other/Proprietary License" in classifiers
    assert not any(c.startswith("License :: OSI Approved") for c in classifiers)


def test_project_urls_present() -> None:
    data = _load()
    urls = data["project"]["urls"]
    for key in ("Homepage", "Repository", "Documentation", "Issues", "Changelog"):
        assert key in urls, f"missing project.urls key {key!r}"


def test_keywords_present() -> None:
    data = _load()
    keywords = data["project"]["keywords"]
    assert isinstance(keywords, list) and len(keywords) >= 5
    assert "decoy" in keywords


def test_native_companion_ships_the_root_license() -> None:
    """The native wheel carries the same LICENSE text as the engine, from its own directory."""
    native = PYPROJECT.parent / "decoy-engine-native"
    with (native / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    assert project["license"] == "FSL-1.1-ALv2"
    assert project["license-files"] == ["LICENSE"]
    assert (native / "LICENSE").read_bytes() == (PYPROJECT.parent / "LICENSE").read_bytes()


def test_readme_install_story() -> None:
    """RG-L: V1 users get the engine inside the CLI bundle. The README must not offer
    `pip install decoy...` or name PyPI anywhere until a public package exists."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"pip install\s+decoy", readme), "README offers a pip install"
    assert not re.search(r"pypi", readme, re.IGNORECASE), "README names PyPI"
    install = readme.split("## Install", 1)[1].split("\n## ", 1)[0]
    assert "CLI bundle" in install


# RG-L: any other license id is legal only in an allowlisted history or conversion sentence,
# keyed by (file, full sentence) with its exact occurrence count. LICENSE is the verbatim FSL
# text. NOTICE is generated ("do not edit by hand") and its third-party table lists dependency
# licenses by design, so only its header above "THIRD-PARTY NOTICES" is scanned.
ROOT = PYPROJECT.parent
OTHER_LICENSE_ID = re.compile(
    r"Apache|\bMIT\b|GPL|\bBSD|\bMPL|BUSL|\bBSL|Business Source License|Elastic License"
    r"|SSPL|Server Side Public License|GNU General Public License",
    re.IGNORECASE,
)
_FSL_NAME = "Functional Source License, Version 1.1, Apache 2.0 Future License"
ALLOWED_ID_SENTENCES: dict[str, dict[str, int]] = {
    "NOTICE": {f"Licensed under the {_FSL_NAME} (FSL-1.1-ALv2).": 1},
    "README.md": {
        "The engine is source-available under the Functional Source License (FSL-1.1-ALv2): "
        "use it for anything, including production, except building a competing product, and "
        "each release becomes Apache-2.0 two years after it ships.": 1,
        f"{_FSL_NAME} (FSL-1.1-ALv2).": 1,
        "Each release converts to the Apache License 2.0 on the second anniversary of its "
        "release.": 1,
        "Releases published before the switch to FSL stay under the Apache License 2.0 they "
        "shipped with.": 1,
    },
}


def _id_sentences(text: str) -> dict[str, int]:
    """Whitespace-normalized sentences that name a license id, with occurrence counts. A new
    markdown block (blank line, heading, bullet) starts a new sentence."""
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "- ", "* ", "|")):
            blocks.append([])
        blocks[-1].append(line.strip())
        if line.startswith("#"):
            blocks.append([])
    counts: dict[str, int] = {}
    for block in blocks:
        joined = " ".join(part for part in block if part)
        for sentence in re.split(r"(?<=[.!?;])\s+(?=[A-Z*(`])", joined):
            if OTHER_LICENSE_ID.search(sentence):
                counts[sentence] = counts.get(sentence, 0) + 1
    return counts


def test_one_license_id_across_docs() -> None:
    """RG-L (plan 5.6): LICENSE, NOTICE and README name FSL-1.1-ALv2, and any other license id
    sits in an allowlisted sentence, exactly as many times as listed."""
    for name in ("LICENSE", "NOTICE", "README.md"):
        assert "FSL-1.1-ALv2" in (ROOT / name).read_text(encoding="utf-8"), name
    for name, allowed in ALLOWED_ID_SENTENCES.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        if name == "NOTICE":
            text = text.split("THIRD-PARTY NOTICES", 1)[0]
        found = _id_sentences(text)
        assert found == allowed, (
            f"{name}: license-id sentences changed. New or miscounted: "
            f"{ {k: v for k, v in found.items() if allowed.get(k) != v} }; "
            f"missing: {[k for k in allowed if k not in found]}"
        )
