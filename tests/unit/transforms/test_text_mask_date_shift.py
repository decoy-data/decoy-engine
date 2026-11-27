"""E-F0: a date span that does not parse never comes back as its real text, and an unsupported
detector and strategy pair raises a tagged error instead of writing the span through."""

from __future__ import annotations

import pytest

from decoy_engine import reasons
from decoy_engine.detection.detectors import Span
from decoy_engine.errors import ConfigError
from decoy_engine.transforms import text_mask as tm

_KEY = b"\x09" * 32
_MARKER = "MARKER-123-45-6789"


def test_unparseable_iso_date_span_becomes_the_token() -> None:
    span = Span("iso_date", 0, 10, "2024-02-30")
    out = tm.mask_cell_with_spans("2024-02-30", [span], _KEY)
    assert out == "[REDACTED]"
    custom = tm.mask_cell_with_spans("2024-02-30", [span], _KEY, token="[GONE]")
    assert custom == "[GONE]"


def test_parseable_date_span_still_shifts() -> None:
    span = Span("iso_date", 0, 10, "2024-02-20")
    out = tm.mask_cell_with_spans("2024-02-20", [span], _KEY, cfg={"min_days": 3, "max_days": 3})
    assert out == "2024-02-23"


@pytest.mark.parametrize(
    ("detector", "strategy"),
    [("ssn", "date_shift"), ("email", "fpe"), ("email", "faker"), ("person_name", "fakr")],
)
def test_unsupported_pair_raises_tagged_config_error_without_the_value(
    detector: str, strategy: str
) -> None:
    span = Span(detector, 0, len(_MARKER), _MARKER)
    with pytest.raises(ConfigError) as exc:
        tm._mask_span(span, _KEY, strategy, {"token": "[T]"})
    err = exc.value
    assert getattr(err, "code", None) == str(reasons.config.MASK_TEXT_MASK_STRATEGY_UNSUPPORTED)
    for text in (str(err), repr(err.args), repr(err.__cause__), repr(err.__context__)):
        assert _MARKER not in text
    assert detector in str(err) and strategy in str(err)
    assert err.__cause__ is None and err.__context__ is None


def test_mask_cell_with_ssn_date_shift_no_longer_writes_the_real_ssn() -> None:
    with pytest.raises(ConfigError):
        tm.mask_cell("ssn 123-45-6789 here", _KEY, strategy_map={"ssn": "date_shift"})


def test_unknown_detector_id_span_raises() -> None:
    span = Span("not_a_detector", 0, 3, "abc")
    with pytest.raises(ConfigError):
        tm._mask_span(span, _KEY, "redact", {"token": "[T]"})


# DATE-RANGE-SENTINEL S4: a span at the calendar edge that the shift would push past it.
_EDGE_CASES = [
    ("iso_date", "9999-12-31", {"min_days": 3, "max_days": 3}),
    ("us_date", "12/31/9999", {"min_days": 1, "max_days": 30}),
    ("eu_date", "31/12/9999", {"min_days": 1, "max_days": 30}),
    ("iso_date", "0001-01-01", {"min_days": -3, "max_days": -3}),
    ("iso_date", "0001-01-01", {"min_days": -30, "max_days": -1}),
]


@pytest.mark.parametrize(("detector", "text", "cfg"), _EDGE_CASES)
def test_edge_date_span_becomes_the_token(detector: str, text: str, cfg: dict[str, int]) -> None:
    span = Span(detector, 0, len(text), text)
    assert tm.mask_cell_with_spans(text, [span], _KEY, cfg=cfg) == "[REDACTED]"
    custom = tm.mask_cell_with_spans(text, [span], _KEY, token="[GONE]", cfg=cfg)
    assert custom == "[GONE]"


def test_edge_span_leaves_the_rest_of_the_cell_masked_as_before() -> None:
    cell = "from 9999-12-31 to 2024-02-20"
    spans = [Span("iso_date", 5, 15, "9999-12-31"), Span("iso_date", 19, 29, "2024-02-20")]
    out = tm.mask_cell_with_spans(
        cell, spans, _KEY, unmatched_span_policy="passthrough", cfg={"min_days": 3, "max_days": 3}
    )
    assert out == "from [REDACTED] to 2024-02-23"


def test_edge_span_that_the_shift_keeps_inside_the_calendar_still_shifts() -> None:
    far = Span("iso_date", 0, 10, "9999-12-31")
    assert (
        tm.mask_cell_with_spans("9999-12-31", [far], _KEY, cfg={"min_days": -3, "max_days": -3})
        == "9999-12-28"
    )
    early = Span("iso_date", 0, 10, "0002-01-05")
    assert (
        tm.mask_cell_with_spans("0002-01-05", [early], _KEY, cfg={"min_days": 2, "max_days": 2})
        == "0002-01-07"
    )


def test_edge_span_overflow_raises_no_error_and_writes_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    span = Span("iso_date", 0, 10, "9999-12-31")
    with caplog.at_level("DEBUG"):
        out = tm.mask_cell_with_spans(
            "9999-12-31", [span], _KEY, cfg={"min_days": 5, "max_days": 5}
        )
    assert out == "[REDACTED]"
    assert "9999" not in caplog.text
