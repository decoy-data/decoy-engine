"""Catalog of the ``evidence`` composite refusals: a strict-reader code under a document name.

A composite token (``STATEMENT_NOT_JSON``) is an identity of its own, ``statement.not_json``, so no
dynamic string ever reaches the registry. ``_wire.py`` maps each to its frozen wire token.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED

__all__ = [
    "CATALOG_BOM",
    "CATALOG_DUPLICATE_MEMBER",
    "CATALOG_FLOAT_NOT_ALLOWED",
    "CATALOG_INTEGER_OUT_OF_DOMAIN",
    "CATALOG_INVALID_UNICODE",
    "CATALOG_NON_FINITE_NUMBER",
    "CATALOG_NOT_JSON",
    "CATALOG_NOT_UTF8",
    "CATALOG_TOO_DEEP",
    "CATALOG_TOO_LARGE",
    "CATALOG_TOO_MANY_NODES",
    "ENVELOPE_DUPLICATE_MEMBER",
    "ENVELOPE_FLOAT_NOT_ALLOWED",
    "ENVELOPE_INTEGER_OUT_OF_DOMAIN",
    "ENVELOPE_INVALID_UNICODE",
    "ENVELOPE_NON_FINITE_NUMBER",
    "ENVELOPE_TOO_DEEP",
    "ENVELOPE_TOO_LARGE",
    "ENVELOPE_TOO_MANY_NODES",
    "EXPECTATIONS_BOM",
    "EXPECTATIONS_DUPLICATE_MEMBER",
    "EXPECTATIONS_FLOAT_NOT_ALLOWED",
    "EXPECTATIONS_INTEGER_OUT_OF_DOMAIN",
    "EXPECTATIONS_INVALID_UNICODE",
    "EXPECTATIONS_NON_FINITE_NUMBER",
    "EXPECTATIONS_NOT_JSON",
    "EXPECTATIONS_NOT_UTF8",
    "EXPECTATIONS_TOO_DEEP",
    "EXPECTATIONS_TOO_LARGE",
    "EXPECTATIONS_TOO_MANY_NODES",
    "STATEMENT_BOM",
    "STATEMENT_DUPLICATE_MEMBER",
    "STATEMENT_FLOAT_NOT_ALLOWED",
    "STATEMENT_INTEGER_OUT_OF_DOMAIN",
    "STATEMENT_INVALID_UNICODE",
    "STATEMENT_NON_FINITE_NUMBER",
    "STATEMENT_NOT_JSON",
    "STATEMENT_NOT_UTF8",
    "STATEMENT_TOO_DEEP",
    "STATEMENT_TOO_LARGE",
    "STATEMENT_TOO_MANY_NODES",
    "TRUST_POLICY_BOM",
    "TRUST_POLICY_DUPLICATE_MEMBER",
    "TRUST_POLICY_FLOAT_NOT_ALLOWED",
    "TRUST_POLICY_INTEGER_OUT_OF_DOMAIN",
    "TRUST_POLICY_INVALID_UNICODE",
    "TRUST_POLICY_NON_FINITE_NUMBER",
    "TRUST_POLICY_NOT_JSON",
    "TRUST_POLICY_NOT_UTF8",
    "TRUST_POLICY_TOO_DEEP",
    "TRUST_POLICY_TOO_LARGE",
    "TRUST_POLICY_TOO_MANY_NODES",
]

_d = _catalog.evidence("SignedEvidence")
STATEMENT_BOM = _d("statement.bom", "Signed evidence was refused: statement bom.", since=UNRELEASED)
STATEMENT_DUPLICATE_MEMBER = _d(
    "statement.duplicate_member",
    "Signed evidence was refused: statement duplicate member.",
    since=UNRELEASED,
)
STATEMENT_FLOAT_NOT_ALLOWED = _d(
    "statement.float_not_allowed",
    "Signed evidence was refused: statement float not allowed.",
    since=UNRELEASED,
)
STATEMENT_INTEGER_OUT_OF_DOMAIN = _d(
    "statement.integer_out_of_domain",
    "Signed evidence was refused: statement integer out of domain.",
    since=UNRELEASED,
)
STATEMENT_INVALID_UNICODE = _d(
    "statement.invalid_unicode",
    "Signed evidence was refused: statement invalid unicode.",
    since=UNRELEASED,
)
STATEMENT_NON_FINITE_NUMBER = _d(
    "statement.non_finite_number",
    "Signed evidence was refused: statement non finite number.",
    since=UNRELEASED,
)
STATEMENT_NOT_JSON = _d(
    "statement.not_json",
    "Signed evidence was refused: statement not json.",
    since=UNRELEASED,
)
STATEMENT_NOT_UTF8 = _d(
    "statement.not_utf8",
    "Signed evidence was refused: statement not utf8.",
    since=UNRELEASED,
)
STATEMENT_TOO_DEEP = _d(
    "statement.too_deep",
    "Signed evidence was refused: statement too deep.",
    since=UNRELEASED,
)
STATEMENT_TOO_LARGE = _d(
    "statement.too_large",
    "Signed evidence was refused: statement too large.",
    since=UNRELEASED,
)
STATEMENT_TOO_MANY_NODES = _d(
    "statement.too_many_nodes",
    "Signed evidence was refused: statement too many nodes.",
    since=UNRELEASED,
)
TRUST_POLICY_BOM = _d(
    "trust_policy.bom",
    "Signed evidence was refused: trust policy bom.",
    since=UNRELEASED,
)
TRUST_POLICY_DUPLICATE_MEMBER = _d(
    "trust_policy.duplicate_member",
    "Signed evidence was refused: trust policy duplicate member.",
    since=UNRELEASED,
)
TRUST_POLICY_FLOAT_NOT_ALLOWED = _d(
    "trust_policy.float_not_allowed",
    "Signed evidence was refused: trust policy float not allowed.",
    since=UNRELEASED,
)
TRUST_POLICY_INTEGER_OUT_OF_DOMAIN = _d(
    "trust_policy.integer_out_of_domain",
    "Signed evidence was refused: trust policy integer out of domain.",
    since=UNRELEASED,
)
TRUST_POLICY_INVALID_UNICODE = _d(
    "trust_policy.invalid_unicode",
    "Signed evidence was refused: trust policy invalid unicode.",
    since=UNRELEASED,
)
TRUST_POLICY_NON_FINITE_NUMBER = _d(
    "trust_policy.non_finite_number",
    "Signed evidence was refused: trust policy non finite number.",
    since=UNRELEASED,
)
TRUST_POLICY_NOT_JSON = _d(
    "trust_policy.not_json",
    "Signed evidence was refused: trust policy not json.",
    since=UNRELEASED,
)
TRUST_POLICY_NOT_UTF8 = _d(
    "trust_policy.not_utf8",
    "Signed evidence was refused: trust policy not utf8.",
    since=UNRELEASED,
)
TRUST_POLICY_TOO_DEEP = _d(
    "trust_policy.too_deep",
    "Signed evidence was refused: trust policy too deep.",
    since=UNRELEASED,
)
TRUST_POLICY_TOO_LARGE = _d(
    "trust_policy.too_large",
    "Signed evidence was refused: trust policy too large.",
    since=UNRELEASED,
)
TRUST_POLICY_TOO_MANY_NODES = _d(
    "trust_policy.too_many_nodes",
    "Signed evidence was refused: trust policy too many nodes.",
    since=UNRELEASED,
)
CATALOG_BOM = _d("catalog.bom", "Signed evidence was refused: catalog bom.", since=UNRELEASED)
CATALOG_DUPLICATE_MEMBER = _d(
    "catalog.duplicate_member",
    "Signed evidence was refused: catalog duplicate member.",
    since=UNRELEASED,
)
CATALOG_FLOAT_NOT_ALLOWED = _d(
    "catalog.float_not_allowed",
    "Signed evidence was refused: catalog float not allowed.",
    since=UNRELEASED,
)
CATALOG_INTEGER_OUT_OF_DOMAIN = _d(
    "catalog.integer_out_of_domain",
    "Signed evidence was refused: catalog integer out of domain.",
    since=UNRELEASED,
)
CATALOG_INVALID_UNICODE = _d(
    "catalog.invalid_unicode",
    "Signed evidence was refused: catalog invalid unicode.",
    since=UNRELEASED,
)
CATALOG_NON_FINITE_NUMBER = _d(
    "catalog.non_finite_number",
    "Signed evidence was refused: catalog non finite number.",
    since=UNRELEASED,
)
CATALOG_NOT_JSON = _d(
    "catalog.not_json",
    "Signed evidence was refused: catalog not json.",
    since=UNRELEASED,
)
CATALOG_NOT_UTF8 = _d(
    "catalog.not_utf8",
    "Signed evidence was refused: catalog not utf8.",
    since=UNRELEASED,
)
CATALOG_TOO_DEEP = _d(
    "catalog.too_deep",
    "Signed evidence was refused: catalog too deep.",
    since=UNRELEASED,
)
CATALOG_TOO_LARGE = _d(
    "catalog.too_large",
    "Signed evidence was refused: catalog too large.",
    since=UNRELEASED,
)
CATALOG_TOO_MANY_NODES = _d(
    "catalog.too_many_nodes",
    "Signed evidence was refused: catalog too many nodes.",
    since=UNRELEASED,
)
EXPECTATIONS_BOM = _d(
    "expectations.bom",
    "Signed evidence was refused: expectations bom.",
    since=UNRELEASED,
)
EXPECTATIONS_DUPLICATE_MEMBER = _d(
    "expectations.duplicate_member",
    "Signed evidence was refused: expectations duplicate member.",
    since=UNRELEASED,
)
EXPECTATIONS_FLOAT_NOT_ALLOWED = _d(
    "expectations.float_not_allowed",
    "Signed evidence was refused: expectations float not allowed.",
    since=UNRELEASED,
)
EXPECTATIONS_INTEGER_OUT_OF_DOMAIN = _d(
    "expectations.integer_out_of_domain",
    "Signed evidence was refused: expectations integer out of domain.",
    since=UNRELEASED,
)
EXPECTATIONS_INVALID_UNICODE = _d(
    "expectations.invalid_unicode",
    "Signed evidence was refused: expectations invalid unicode.",
    since=UNRELEASED,
)
EXPECTATIONS_NON_FINITE_NUMBER = _d(
    "expectations.non_finite_number",
    "Signed evidence was refused: expectations non finite number.",
    since=UNRELEASED,
)
EXPECTATIONS_NOT_JSON = _d(
    "expectations.not_json",
    "Signed evidence was refused: expectations not json.",
    since=UNRELEASED,
)
EXPECTATIONS_NOT_UTF8 = _d(
    "expectations.not_utf8",
    "Signed evidence was refused: expectations not utf8.",
    since=UNRELEASED,
)
EXPECTATIONS_TOO_DEEP = _d(
    "expectations.too_deep",
    "Signed evidence was refused: expectations too deep.",
    since=UNRELEASED,
)
EXPECTATIONS_TOO_LARGE = _d(
    "expectations.too_large",
    "Signed evidence was refused: expectations too large.",
    since=UNRELEASED,
)
EXPECTATIONS_TOO_MANY_NODES = _d(
    "expectations.too_many_nodes",
    "Signed evidence was refused: expectations too many nodes.",
    since=UNRELEASED,
)
ENVELOPE_DUPLICATE_MEMBER = _d(
    "envelope.duplicate_member",
    "Signed evidence was refused: envelope duplicate member.",
    since=UNRELEASED,
)
ENVELOPE_FLOAT_NOT_ALLOWED = _d(
    "envelope.float_not_allowed",
    "Signed evidence was refused: envelope float not allowed.",
    since=UNRELEASED,
)
ENVELOPE_INTEGER_OUT_OF_DOMAIN = _d(
    "envelope.integer_out_of_domain",
    "Signed evidence was refused: envelope integer out of domain.",
    since=UNRELEASED,
)
ENVELOPE_INVALID_UNICODE = _d(
    "envelope.invalid_unicode",
    "Signed evidence was refused: envelope invalid unicode.",
    since=UNRELEASED,
)
ENVELOPE_NON_FINITE_NUMBER = _d(
    "envelope.non_finite_number",
    "Signed evidence was refused: envelope non finite number.",
    since=UNRELEASED,
)
ENVELOPE_TOO_DEEP = _d(
    "envelope.too_deep",
    "Signed evidence was refused: envelope too deep.",
    since=UNRELEASED,
)
ENVELOPE_TOO_LARGE = _d(
    "envelope.too_large",
    "Signed evidence was refused: envelope too large.",
    since=UNRELEASED,
)
ENVELOPE_TOO_MANY_NODES = _d(
    "envelope.too_many_nodes",
    "Signed evidence was refused: envelope too many nodes.",
    since=UNRELEASED,
)
