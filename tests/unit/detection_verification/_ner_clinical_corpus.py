"""The clinical-vocabulary negative corpus for the per-model NER rates (seeded, no network).

Cells are free-text description values from Synthea's sample CSV bundle (Apache-2.0; zip sha256
`9ffed7cda683fb4a1eb9e39cfa01c53a5fc8fa957a935d293ed44f499740250d`): drugs, vaccines, lab and
observation terms, procedures, conditions, devices, supplies and care plans. They are vocabulary,
not PII. A column holds no person and no place, so it is a negative for every NER detector id.

The distinct values and how often each occurs are committed in `clinical_terms.tsv`
(`table.COLUMN`, count, term). Each column draws `N` cells from them, weighted by count, with a
seeded RNG, so the corpus keeps the real term frequencies without committing 28,000 cells. The
digest is pinned by `test_ner_clinical_corpus_frozen.py` and was taken before any rate was
measured. Like `_ner_corpus.py`, the corpus is never edited after a measurement. Nothing here reads
the bundle: regenerating from it on load would let the corpus drift from its digest.
"""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from tests.unit.detection_verification import _ner_corpus as nc

TERMS_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ner_clinical" / "clinical_terms.tsv"
)
N = nc.N
SEED = 20261116


def terms() -> dict[str, list[tuple[str, int]]]:
    """Column name -> (term, count) rows, in file order."""
    out: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for line in TERMS_PATH.read_text(encoding="ascii").splitlines():
        column, count, term = line.split("\t")
        out[column].append((term, int(count)))
    return dict(out)


def corpus() -> list[nc.Negative]:
    columns = []
    for index, (column, rows) in enumerate(terms().items()):
        rng = random.Random(SEED + index)
        cells = rng.choices([t for t, _ in rows], weights=[c for _, c in rows], k=N)
        columns.append(nc.Negative(f"clinical_{column}", nc.BOTH, tuple(cells)))
    return columns
