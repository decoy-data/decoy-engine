"""Generate the check-digit KAT corpus from the live Python oracle.

`tests/kat_checksum.rs` reads `checksum_kat.json` and asserts `checksum::length_ok`,
`checksum::validate` and `checksum::check_digit` agree with `decoy_engine.checksums`
(python-stdnum for luhn, ean13, gtin and isbn13; the CMS and NHTSA rules for npi and vin) on
every row. `tests/unit/test_checksum_kat_regen.py` re-runs `build_corpus` and compares it with
the committed file, so the JSON cannot drift from the oracle.

Usage: `python generate_checksum_kat.py` writes the file; `--check` compares without writing.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import stdnum

from decoy_engine import checksums

SEED = 20261125
FORMAT_VERSION = 1
BODIES_PER_SCHEME = 220
_DIGITS = "0123456789"
_VIN_ALPHABET = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
_PATH = Path(__file__).parent / "checksum_kat.json"

# Body length (characters without the check digit) per scheme, where several are legal.
_BODY_LENGTHS: dict[str, tuple[int, ...]] = {
    "luhn": tuple(range(1, 41)),
    "npi": (9,),
    "ean13": (12,),
    "gtin": (7, 11, 12, 13),
    "isbn13": (12,),
    "vin": (16,),
}


def _length_ok(scheme: str, n: int) -> bool:
    """The plan's length rule, written out here so the corpus pins it independently."""
    return {
        "luhn": n >= 2,
        "npi": n == 10,
        "ean13": n == 13,
        "isbn13": n == 13,
        "vin": n == 17,
        "gtin": n in (8, 12, 13, 14),
    }[scheme]


def _bodies(scheme: str, rng: random.Random) -> list[str]:
    alphabet = _VIN_ALPHABET if scheme == "vin" else _DIGITS
    lengths = _BODY_LENGTHS[scheme]
    out: list[str] = []
    for n in lengths:
        out.append(alphabet[0] * n)
        out.append(alphabet[-1] * n)
    if scheme == "npi":
        out += ["123456789", "323456789", "023456789", "999999999", "223456789"]
    if scheme == "vin":
        out += ["1M8GDM9AKP042788", "ZZZZZZZZZZZZZZZZ", "1HGCM82633A004352"[:8] + "33A00435"]
    if scheme == "isbn13":
        out += ["978030640615", "979123456789", "123456789012", "977123456789"]
    while len(out) < BODIES_PER_SCHEME:
        n = lengths[len(out) % len(lengths)]
        body = "".join(rng.choice(alphabet) for _ in range(n))
        if scheme == "npi":
            body = rng.choice("12") + body[1:]
        elif scheme == "isbn13":
            body = rng.choice(("978", "979")) + body[3:]
        out.append(body)
    return out


def _body_row(scheme: str, body: str) -> dict[str, Any]:
    return {"scheme": scheme, "body": body, "check": checksums.calc_check_digit(scheme, body)}


def _value_row(scheme: str, value: str) -> dict[str, Any]:
    length_ok = _length_ok(scheme, len(value))
    # The Rust `validate` is the oracle's verdict inside the legal lengths and false outside them
    # (the oracle also accepts other lengths, e.g. an 8-digit ean13; the FPE path never asks).
    # The oracle's ean and isbn validators also strip spaces and dashes; the FPE path never passes
    # either, so a value outside the scheme's alphabet is pinned as invalid.
    alphabet = _VIN_ALPHABET + _VIN_ALPHABET.lower() if scheme == "vin" else _DIGITS
    in_alphabet = all(c in alphabet for c in value)
    valid = length_ok and in_alphabet and checksums.validate(scheme, value)
    return {"scheme": scheme, "value": value, "length_ok": length_ok, "valid": valid}


def _variants(scheme: str, full: str, rng: random.Random) -> list[str]:
    """The valid value plus mutations: wrong check, a swapped body digit, a bad character,
    a short and a long value."""
    flip = "1" if full[-1] != "1" else "2"
    out = [full, full[:-1] + flip]
    pos = rng.randrange(len(full) - 1)
    out.append(full[:pos] + ("5" if full[pos] != "5" else "6") + full[pos + 1 :])
    out.append(full[:1] + "-" + full[2:])
    out.append(full[:-1])
    out.append(full + "0")
    if scheme == "vin":
        out.append(full.lower())
        out.append(full[:3] + "I" + full[4:])
        out.append(full[:3] + "é" + full[4:])
    else:
        out.append(full[:-1] + "٣")
    return out


def build_corpus(engine_commit: str) -> dict[str, Any]:
    rng = random.Random(SEED)
    bodies: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    for scheme in _BODY_LENGTHS:
        for body in _bodies(scheme, rng):
            bodies.append(_body_row(scheme, body))
            check = checksums.calc_check_digit(scheme, body)
            full = body[:8] + check + body[8:] if scheme == "vin" else body + check
            values.extend(_value_row(scheme, v) for v in _variants(scheme, full, rng))
    return {
        "format_version": FORMAT_VERSION,
        "provenance": {
            "generator": "decoy-engine-native/vectors/generate_checksum_kat.py",
            "python_stdnum": stdnum.__version__,
            "engine_commit": engine_commit,
            "seed": SEED,
        },
        "bodies": bodies,
        "values": values,
    }


def _head() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    out = subprocess.run(  # noqa: S603 (fixed argv, no user input)
        [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=False, cwd=_PATH.parent
    )
    return out.stdout.strip() or "unknown"


def main(argv: list[str]) -> int:
    existing = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.exists() else None
    commit = existing["provenance"]["engine_commit"] if existing else _head()
    fresh = build_corpus(commit if "--check" in argv else _head())
    if "--check" in argv:
        return 0 if fresh == existing else 1
    _PATH.write_text(json.dumps(fresh, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {len(fresh['bodies'])} bodies and {len(fresh['values'])} values to {_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
