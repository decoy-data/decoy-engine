"""AT-E6c (RUN-STREAM): `/result/route/sink`, an optional `SafeRef` on the run result.

Written before the implementation. Do not delete one, add a skip or xfail, or weaken a
comparison to make a case pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from decoy_engine.run_result import RunResultRead
from decoy_engine.run_result._model import Route
from tests.unit.run_result.test_build import build

CORPUS = Path(__file__).parents[2] / "integration" / "compat_corpus" / "run_result"


@pytest.mark.parametrize("sink", ["used", "run.sink_unused.post_scan", None])
def test_the_sink_fact_writes_and_round_trips(sink: str | None) -> None:
    result = build(sink=sink)
    assert result.route.sink == sink
    again = RunResultRead.model_validate(result.to_payload())
    assert again.route.sink == sink


@pytest.mark.parametrize("text", ["has spaces", "a/b", "/abs/path", "used\n", "", "x;y", "é"])
def test_free_text_is_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        build(sink=text)


def test_sink_is_a_safe_ref_not_a_free_string() -> None:
    field = Route.model_fields["sink"]
    assert field.default is None
    with pytest.raises(ValidationError):
        Route(
            execution_mode=None,
            route_reason=None,
            chunked=False,
            native=None,
            sink="free text here",
        )


def test_an_older_document_without_the_field_reads_with_none() -> None:
    document = json.loads((CORPUS / "run-result-v1.json").read_text(encoding="utf-8"))
    assert "sink" not in document["route"]
    assert RunResultRead.model_validate(document).route.sink is None


def test_the_next_minor_cell_keeps_the_sink() -> None:
    document = json.loads((CORPUS / "run-result-v1-next-minor.json").read_text(encoding="utf-8"))
    assert document["route"]["sink"] == "used"
    assert RunResultRead.model_validate(document).route.sink == "used"
