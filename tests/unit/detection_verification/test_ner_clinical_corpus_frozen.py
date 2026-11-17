"""M-T1: the clinical negative corpus is frozen: its cells are pinned by digest.

The digest was taken before the first md measurement. A change to the term file, the seed or the
draw moves it, and `NER_MIN_RATES["en_core_web_md"]` would then describe a different corpus. If the
digest has to move, say why in the commit: a corpus bug found after a measurement is the only
acceptable reason. No spaCy is needed here.
"""

from __future__ import annotations

from decoy_engine.detection import _ner_rate as nr
from tests.unit.detection_verification import _ner_clinical_corpus as cc
from tests.unit.detection_verification import _ner_corpus as nc

CLINICAL_DIGEST = "a824a67fdf33e3843349075f3fbd273b419bdf118ccfb967833930edef163903"
CLINICAL_COLUMNS = (
    "clinical_allergies.DESCRIPTION",
    "clinical_careplans.DESCRIPTION",
    "clinical_careplans.REASONDESCRIPTION",
    "clinical_conditions.DESCRIPTION",
    "clinical_devices.DESCRIPTION",
    "clinical_encounters.DESCRIPTION",
    "clinical_encounters.REASONDESCRIPTION",
    "clinical_immunizations.DESCRIPTION",
    "clinical_medications.DESCRIPTION",
    "clinical_medications.REASONDESCRIPTION",
    "clinical_observations.DESCRIPTION",
    "clinical_procedures.DESCRIPTION",
    "clinical_procedures.REASONDESCRIPTION",
    "clinical_supplies.DESCRIPTION",
)


def test_the_clinical_corpus_is_frozen() -> None:
    columns = cc.corpus()
    assert tuple(c.name for c in columns) == CLINICAL_COLUMNS
    assert nc.digest(columns) == CLINICAL_DIGEST


def test_the_digest_moves_when_a_single_cell_changes() -> None:
    columns = cc.corpus()
    first = columns[0]
    edited = nc.Negative(first.name, first.negative_for, (first.cells[0] + " x", *first.cells[1:]))
    assert nc.digest([edited, *columns[1:]]) != nc.digest(columns)


def test_every_column_is_full_size_free_text_and_a_negative_for_every_id() -> None:
    for column in cc.corpus():
        assert len(column.cells) == cc.N, column.name
        assert all(isinstance(c, str) and c for c in column.cells), column.name
        assert column.negative_for == nc.BOTH, column.name
        assert nr.is_free_text(list(column.cells)), (column.name, "would not be scored")


def test_the_clinical_cells_share_nothing_with_the_other_corpora_columns() -> None:
    clinical = {cell for c in cc.corpus() for cell in c.cells}
    others = {cell for c in (*nc.corpus(), *nc.held_out_corpus()) for cell in c.cells}
    assert not clinical & others
