"""EXPECT-OFF-ROUTE plan section 3a: every table a run delivers is judged exactly once.

A failing judgement fails the run (or quarantines, when configured). Marking a table complete is
not a judgement, and a step defers only behind an explicit owner token. Each route row uses a
reject-all `regex_match`.

Mutations these tests kill (plan section 3a): M17 (`close` raises only for tables its own caller
fed), M18 (`table_complete` also marks a table judged).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.errors import ValidatorFailedError, ValidatorStateError
from decoy_engine.validators import ValidationSession, bind_validation_session
from tests.parity import _f2_mixed_support as mixed
from tests.parity import test_phase_d_d3a_validators_ooc as ooc

_REJECT_ALL = {"pattern": "^$"}
_ONE_TABLE = {
    "validators": [{"name": "regex_match", "columns": {"t": ["v"]}, "params": _REJECT_ALL}]
}
_TABLE = pa.table({"v": ["a", "b", "c"]})


def _reject_parent_code() -> list[dict[str, Any]]:
    return [ooc._v("regex_match", {"parent": ["code"]}, pattern="^$")]


# --- V15a: resident full frame ------------------------------------------------------------------


def test_v15a_resident_full_frame_raises(tmp_path: Path) -> None:
    cfg, tables = ooc.standard(tmp_path, _reject_parent_code())
    with pytest.raises(ValidatorFailedError):
        ooc.run(cfg, tables, full=True)


def test_v15a_resident_full_frame_quarantines_when_configured(tmp_path: Path) -> None:
    quarantine = {
        "enabled": True,
        "output_path": str(tmp_path / "q.jsonl"),
        "triggers": ["validation_fail"],
    }
    cfg, tables = ooc.standard(tmp_path, _reject_parent_code(), quarantine=quarantine)
    result = ooc.run(cfg, tables, full=True)
    assert result.quality_metrics["validation"]["validators"]["passed"] is False
    # Quarantine took the rejected rows out of what the run delivers.
    assert result.outputs["parent"].num_rows == 0


# --- V15c: full frame under a bound session -----------------------------------------------------


def test_v15c_a_table_fed_by_the_resident_choke_fails_at_close() -> None:
    with bind_validation_session(_ONE_TABLE, key_state_budget=lambda: None) as session:
        assert session is not None
        session.observe_unobserved({"t": _TABLE}, {})
        with pytest.raises(ValidatorFailedError):
            session.close()
        assert session.unjudged_tables() == []


# --- V15d: a table some other step fed is still judged at close (the security finding) ----------


def test_v15d_close_raises_for_a_table_an_earlier_step_fed() -> None:
    session = ValidationSession(_ONE_TABLE)
    session.observe("t", _TABLE)  # an earlier step fed and completed the table, then returned
    assert session.unobserved_tables(["t"]) == []
    with pytest.raises(ValidatorFailedError):
        session.close()
    assert session.unjudged_tables() == []


def test_v15d_a_judged_failure_is_not_raised_twice() -> None:
    """A judge that settled the report (quarantine covered it) leaves nothing for close."""
    session = ValidationSession(_ONE_TABLE)
    session.observe("t", _TABLE)
    report = session.finish()
    session.record_verdict(report)
    assert session.close() is report


def test_v15d_a_verdict_for_another_report_settles_nothing() -> None:
    session = ValidationSession(_ONE_TABLE)
    session.observe("t", _TABLE)
    other = ValidationSession(_ONE_TABLE)
    other.observe("t", _TABLE)
    session.record_verdict(other.finish())
    with pytest.raises(ValidatorFailedError):
        session.close()


# --- V15e: mixed route ----------------------------------------------------------------------------


@mixed.NEEDS_COMPANION
def test_v15e_mixed_route_raises(tmp_path: Path) -> None:
    keys = pa.array([str(i) for i in range(5)] * 8, pa.string())
    child = mixed.child_table(keys)
    config = mixed.mixed_config(tmp_path, child)
    config["validators"] = [
        {"name": "regex_match", "columns": {mixed.CHILD: ["email"]}, "params": _REJECT_ALL}
    ]
    with pytest.raises(ValidatorFailedError):
        mixed.run(config, {mixed.CHILD: child})


# --- V15f: out-of-core ----------------------------------------------------------------------------


def test_v15f_out_of_core_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ooc.fixed_disk(monkeypatch)
    cfg, tables = ooc.standard(tmp_path, _reject_parent_code())
    with pytest.raises(ValidatorFailedError):
        ooc.run(cfg, tables)


def test_v15f_an_external_verdict_needs_an_owner_and_feeds_nothing() -> None:
    session = ValidationSession(_ONE_TABLE)
    with pytest.raises(ValueError, match="owner"):
        session.record_external_verdict(["t"], owner="")
    session.record_external_verdict(["t"], owner="out_of_core_collector")
    assert session.unobserved_tables(["t"]) == []
    assert session.close().passed is True


# --- V15g: complete is not judged; deferral is explicit -----------------------------------------


def test_v15g_complete_without_a_feed_or_verdict_refuses_at_close() -> None:
    session = ValidationSession(_ONE_TABLE)
    session.table_complete("t")
    with pytest.raises(ValidatorStateError) as caught:
        session.close()
    assert caught.value.code == reasons.runtime.VALIDATOR_TABLE_NOT_OBSERVED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_v15g_table_complete_after_a_failing_batch_is_still_judged_at_close() -> None:
    """M18: completing a fed table is not a judgement of it."""
    session = ValidationSession(_ONE_TABLE)
    session.observe_published("t", _TABLE.to_batches()[0])
    session.table_complete("t")
    with pytest.raises(ValidatorFailedError):
        session.close()
    with pytest.raises(ValidatorFailedError):
        session.close()


def test_v15g_a_deferred_table_the_owner_never_fed_refuses_at_close() -> None:
    session = ValidationSession(_ONE_TABLE)
    session.defer(["t"], owner="unified_slice")
    with pytest.raises(ValidatorStateError) as caught:
        session.close()
    assert caught.value.code == reasons.runtime.VALIDATOR_TABLE_NOT_OBSERVED


def test_v15g_a_deferred_table_the_owner_fed_is_judged_at_close() -> None:
    session = ValidationSession(_ONE_TABLE)
    session.defer(["t"], owner="unified_slice")
    session.observe("t", _TABLE)
    with pytest.raises(ValidatorFailedError):
        session.close()


def test_v15g_deferral_needs_an_owner_token() -> None:
    session = ValidationSession(_ONE_TABLE)
    with pytest.raises(ValueError, match="owner"):
        session.defer(["t"], owner="")
