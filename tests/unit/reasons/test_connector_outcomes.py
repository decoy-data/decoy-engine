"""Connector reason outcomes drive the CLI exit split (AT-E13)."""

from __future__ import annotations

import pytest

from decoy_engine import reasons
from decoy_engine.connectors.postgres_snapshot import POSTGRES_SOURCE_USAGE_CODES
from decoy_engine.reasons import Outcome, RetryClass

_USAGE = {
    "ambiguous_name",
    "column_name_unsupported",
    "column_not_found",
    "duplicate_relation",
    "extension_unavailable",
    "extension_untrusted_location",
    "relation_not_found",
    "relation_shape_changed",
    "unsupported_column_type",
    "value_not_representable",
}
_NEW = {"column_name_unsupported", "relation_shape_changed"}


def _connector():
    return [s for s in reasons.specs() if s.namespace == "connector"]


def test_every_connector_code_is_configuration_or_execution():
    specs = _connector()
    assert specs
    for s in specs:
        assert {r.outcome for r in s.rules} <= {Outcome.CONFIGURATION, Outcome.EXECUTION}, s.code


def test_usage_codes_are_the_configuration_set():
    config = {s.code for s in _connector() if s.rules[0].outcome is Outcome.CONFIGURATION}
    assert set(POSTGRES_SOURCE_USAGE_CODES) == config == _USAGE


@pytest.mark.parametrize("spec", _connector(), ids=lambda s: s.code)
def test_retry_class_follows_the_outcome(spec):
    for r in spec.rules:
        if spec.code in _USAGE:
            assert (r.outcome, r.retry) == (Outcome.CONFIGURATION, RetryClass.CONFIGURATION_REPAIR)
        else:
            assert r.outcome is Outcome.EXECUTION


def test_new_codes_are_unreleased_and_old_ones_keep_their_release():
    for s in _connector():
        assert (s.since == reasons.UNRELEASED) == (s.code in _NEW), s.code
