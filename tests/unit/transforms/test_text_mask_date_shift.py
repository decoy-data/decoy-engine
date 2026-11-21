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
