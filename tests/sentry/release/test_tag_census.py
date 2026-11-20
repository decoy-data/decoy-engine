"""S7a sentry: every `"<name>/vN"` tag literal in engine source has one class (AT-S7a).

Classes: a frozen format in contract 3.1, a frozen derivation label in contract 3.3 (and
`DERIVATION_LABELS`), or an internal tag with a reason (`INTERNAL_TAGS`). A new literal fails
until it is classified. The artifact scan for internal tags is in `test_tag_artifacts.py`.
"""

from __future__ import annotations

from decoy_engine.contracts import stability as st
from tests.sentry.release import _tags


def test_every_tag_literal_is_classified() -> None:
    found = _tags.source_tags()
    # Not vacuous: the walk sees the tags the contract names and the ones S7a classified.
    assert len(found) >= 60, len(found)
    assert {"decoy-vault/v2", "tokenize-key/v1", "phase-event/v1", "decoy-telemetry/v1"} <= set(
        found
    )
    frozen, labels, internal = _tags.classes()
    assert _tags.unclassified(set(found), frozen, labels, internal) == set()


def test_the_census_flags_a_new_literal_and_reads_dotted_and_underscored_tags() -> None:
    text = 'A = "x.tag/v1"\nB = b"snake_case/v12"\nC = "not a tag/v1"\nD = f"{x}/v1"\n'
    assert _tags.literals(text) == {"x.tag/v1", "snake_case/v12"}
    assert _tags.unclassified({"x.tag/v1", "ok/v1"}, {"ok/v1"}, set(), set()) == {"x.tag/v1"}


def test_a_tag_has_one_class() -> None:
    frozen, labels, internal = _tags.classes()
    assert _tags.overlaps(frozen, labels, internal) == set()
    assert _tags.overlaps({"a/v1"}, {"a/v1"}, {"b/v1"}) == {"a/v1"}


def test_every_label_and_internal_row_names_a_live_literal() -> None:
    found = _tags.source_tags()
    for table in (
        {tag: owner for tag, owner in st.DERIVATION_LABELS.items()},
        {tag: owner for tag, (owner, _) in st.INTERNAL_TAGS.items()},
    ):
        for tag, owner in table.items():
            assert owner in found.get(tag, []), f"{tag}: not a literal in {owner}"


def test_every_internal_tag_has_a_reason() -> None:
    assert st.INTERNAL_TAGS
    for tag, (_, reason) in st.INTERNAL_TAGS.items():
        assert len(reason.split()) >= 5, tag


def test_contract_3_3_lists_the_derivation_labels() -> None:
    contract = _tags.CONTRACT.read_text(encoding="utf-8")
    assert _tags.contract_3_3_labels(contract) == set(st.DERIVATION_LABELS)


def test_contract_3_1_lists_no_internal_tag_and_no_label() -> None:
    contract = _tags.CONTRACT.read_text(encoding="utf-8")
    in_3_1 = _tags.contract_3_1_tags(contract)
    assert not in_3_1 & set(st.INTERNAL_TAGS)
    assert not in_3_1 & set(st.DERIVATION_LABELS)
