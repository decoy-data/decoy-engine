"""Catalog of the ``evidence`` namespace: the refusals the signed-evidence verifier raises directly.

One lowercase identity per raised wire token. The frozen uppercase token a conformance vector or a
result reports for each identity is in ``_wire.py``. Refusals that wrap a strict-reader code are in
``_composite.py``.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED

__all__ = [
    "ADOPT_NOT_VERIFIED",
    "ARTIFACT_CHANGED_DURING_READ",
    "ARTIFACT_ENUMERATION_FAILED",
    "ARTIFACT_MISSING",
    "ARTIFACT_NOT_REGULAR_FILE",
    "ARTIFACT_PATH_UNSAFE",
    "ARTIFACT_PLATFORM_UNSUPPORTED",
    "ARTIFACT_UNREADABLE",
    "BOM",
    "BUNDLE_CONSTRUCTION_FORBIDDEN",
    "BUNDLE_MEMBER_MISSING",
    "BUNDLE_MEMBER_UNAVAILABLE",
    "BUNDLE_ROOT_MISSING",
    "BUNDLE_ROOT_NOT_DIRECTORY",
    "CANONICALIZATION_FAILED",
    "CARRIER_CONSTRUCTION_FORBIDDEN",
    "CARRIER_FIELDS_INVALID",
    "CATALOG_DUPLICATE_REQUIREMENT",
    "CATALOG_NO_REQUIRED_CHECKS",
    "CATALOG_SCHEMA_INVALID",
    "CATALOG_SCHEMA_UNSUPPORTED",
    "CONTEXT_INCOMPLETE",
    "CONTEXT_INVALID",
    "DUPLICATE_MEMBER",
    "ENVELOPE_ALG_NOT_ES256",
    "ENVELOPE_BASE64URL_INVALID",
    "ENVELOPE_CRIT_INVALID",
    "ENVELOPE_CTY_INVALID",
    "ENVELOPE_HEADER_FIELD_INVALID",
    "ENVELOPE_HEADER_FIELD_MISSING",
    "ENVELOPE_HEADER_MEMBER_FORBIDDEN",
    "ENVELOPE_NOT_JSON",
    "ENVELOPE_PAYLOAD_PRESENT",
    "ENVELOPE_PROTECTED_NOT_JSON",
    "ENVELOPE_SHAPE_UNSUPPORTED",
    "ENVELOPE_TYP_INVALID",
    "ENVELOPE_UNPROTECTED_HEADER",
    "EXPECTATIONS_ARTIFACTS_EMPTY",
    "EXPECTATIONS_ARTIFACT_ID_DUPLICATE",
    "EXPECTATIONS_BAD_PATH",
    "EXPECTATIONS_BAD_TOKEN",
    "EXPECTATIONS_DIGEST_MISMATCH",
    "EXPECTATIONS_MISSING_FIELD",
    "EXPECTATIONS_OUT_OF_RANGE",
    "EXPECTATIONS_PIN_INVALID",
    "EXPECTATIONS_SCHEMA_UNKNOWN",
    "EXPECTATIONS_UNKNOWN_FIELD",
    "EXPECTATIONS_WRONG_TYPE",
    "FLOAT_NOT_ALLOWED",
    "INPUT_ACCESS_DENIED",
    "INPUT_INVALID",
    "INPUT_TOO_LARGE",
    "INPUT_UNAVAILABLE",
    "INTEGER_OUT_OF_DOMAIN",
    "INVALID_UNICODE",
    "LEGACY_INTEGRITY_ONLY",
    "NON_FINITE_NUMBER",
    "NOT_JSON",
    "NOT_UTF8",
    "PERMIT_CONSTRUCTION_FORBIDDEN",
    "PERMIT_FIELDS_INVALID",
    "SIGNATURE_ENCODING_INVALID",
    "SIGNER_BAD_SIGNATURE",
    "SIGNER_IDENTITY_INVALID",
    "SIGNER_IDENTITY_MISMATCH",
    "SIGNER_INVALID",
    "SIGNER_KEY_INVALID",
    "SIGNER_VERIFY_UNSUPPORTED",
    "SIGNING_FAILED",
    "STATEMENT_ARRAY_ORDER",
    "STATEMENT_ARTIFACT_ID_DUPLICATE",
    "STATEMENT_COVERAGE_INVALID",
    "STATEMENT_MISSING_FIELD",
    "STATEMENT_NOT_CANONICAL",
    "STATEMENT_PATH_DUPLICATE",
    "STATEMENT_PATH_INVALID",
    "STATEMENT_PUBLICATION_INCOHERENT",
    "STATEMENT_SCHEMA_INVALID",
    "STATEMENT_SCHEMA_UNSUPPORTED",
    "STATEMENT_TOO_MANY_ARTIFACTS",
    "STATEMENT_TOO_MANY_CHECKS",
    "STATEMENT_UNKNOWN_FIELD",
    "TOO_DEEP",
    "TOO_LARGE",
    "TOO_MANY_NODES",
    "TRUST_POLICY_ALG_UNSUPPORTED",
    "TRUST_POLICY_DIGEST_MISMATCH",
    "TRUST_POLICY_DUPLICATE_KID",
    "TRUST_POLICY_KEY_CONFLICT",
    "TRUST_POLICY_KEY_INVALID",
    "TRUST_POLICY_LIFECYCLE_INCOHERENT",
    "TRUST_POLICY_PIN_INVALID",
    "TRUST_POLICY_SCHEMA_INVALID",
    "TRUST_POLICY_SCHEMA_UNSUPPORTED",
    "TRUST_POLICY_THUMBPRINT_MISMATCH",
]

_d = _catalog.evidence("SignedEvidence")
BOM = _d("bom", "Signed evidence was refused: bom.", since=UNRELEASED)
DUPLICATE_MEMBER = _d(
    "duplicate_member",
    "Signed evidence was refused: duplicate member.",
    since=UNRELEASED,
)
FLOAT_NOT_ALLOWED = _d(
    "float_not_allowed",
    "Signed evidence was refused: float not allowed.",
    since=UNRELEASED,
)
INTEGER_OUT_OF_DOMAIN = _d(
    "integer_out_of_domain",
    "Signed evidence was refused: integer out of domain.",
    since=UNRELEASED,
)
INVALID_UNICODE = _d(
    "invalid_unicode",
    "Signed evidence was refused: invalid unicode.",
    since=UNRELEASED,
)
NON_FINITE_NUMBER = _d(
    "non_finite_number",
    "Signed evidence was refused: non finite number.",
    since=UNRELEASED,
)
NOT_JSON = _d("not_json", "Signed evidence was refused: not json.", since=UNRELEASED)
NOT_UTF8 = _d("not_utf8", "Signed evidence was refused: not utf8.", since=UNRELEASED)
TOO_DEEP = _d("too_deep", "Signed evidence was refused: too deep.", since=UNRELEASED)
TOO_LARGE = _d("too_large", "Signed evidence was refused: too large.", since=UNRELEASED)
TOO_MANY_NODES = _d(
    "too_many_nodes",
    "Signed evidence was refused: too many nodes.",
    since=UNRELEASED,
)
ADOPT_NOT_VERIFIED = _d(
    "adopt_not_verified",
    "Signed evidence was refused: adopt not verified.",
    since=UNRELEASED,
)
ARTIFACT_CHANGED_DURING_READ = _d(
    "artifact_changed_during_read",
    "Signed evidence was refused: artifact changed during read.",
    since=UNRELEASED,
)
ARTIFACT_ENUMERATION_FAILED = _d(
    "artifact_enumeration_failed",
    "Signed evidence was refused: artifact enumeration failed.",
    since=UNRELEASED,
)
ARTIFACT_MISSING = _d(
    "artifact_missing",
    "Signed evidence was refused: artifact missing.",
    since=UNRELEASED,
)
ARTIFACT_NOT_REGULAR_FILE = _d(
    "artifact_not_regular_file",
    "Signed evidence was refused: artifact not regular file.",
    since=UNRELEASED,
)
ARTIFACT_PATH_UNSAFE = _d(
    "artifact_path_unsafe",
    "Signed evidence was refused: artifact path unsafe.",
    since=UNRELEASED,
)
ARTIFACT_PLATFORM_UNSUPPORTED = _d(
    "artifact_platform_unsupported",
    "Signed evidence was refused: artifact platform unsupported.",
    since=UNRELEASED,
)
ARTIFACT_UNREADABLE = _d(
    "artifact_unreadable",
    "Signed evidence was refused: artifact unreadable.",
    since=UNRELEASED,
)
BUNDLE_CONSTRUCTION_FORBIDDEN = _d(
    "bundle_construction_forbidden",
    "Signed evidence was refused: bundle construction forbidden.",
    since=UNRELEASED,
)
BUNDLE_MEMBER_MISSING = _d(
    "bundle_member_missing",
    "Signed evidence was refused: bundle member missing.",
    since=UNRELEASED,
)
BUNDLE_MEMBER_UNAVAILABLE = _d(
    "bundle_member_unavailable",
    "Signed evidence was refused: bundle member unavailable.",
    since=UNRELEASED,
)
BUNDLE_ROOT_MISSING = _d(
    "bundle_root_missing",
    "Signed evidence was refused: bundle root missing.",
    since=UNRELEASED,
)
BUNDLE_ROOT_NOT_DIRECTORY = _d(
    "bundle_root_not_directory",
    "Signed evidence was refused: bundle root not directory.",
    since=UNRELEASED,
)
CANONICALIZATION_FAILED = _d(
    "canonicalization_failed",
    "Signed evidence was refused: canonicalization failed.",
    since=UNRELEASED,
)
CARRIER_CONSTRUCTION_FORBIDDEN = _d(
    "carrier_construction_forbidden",
    "Signed evidence was refused: carrier construction forbidden.",
    since=UNRELEASED,
)
CARRIER_FIELDS_INVALID = _d(
    "carrier_fields_invalid",
    "Signed evidence was refused: carrier fields invalid.",
    since=UNRELEASED,
)
CATALOG_DUPLICATE_REQUIREMENT = _d(
    "catalog_duplicate_requirement",
    "Signed evidence was refused: catalog duplicate requirement.",
    since=UNRELEASED,
)
CATALOG_NO_REQUIRED_CHECKS = _d(
    "catalog_no_required_checks",
    "Signed evidence was refused: catalog no required checks.",
    since=UNRELEASED,
)
CATALOG_SCHEMA_INVALID = _d(
    "catalog_schema_invalid",
    "Signed evidence was refused: catalog schema invalid.",
    since=UNRELEASED,
)
CATALOG_SCHEMA_UNSUPPORTED = _d(
    "catalog_schema_unsupported",
    "Signed evidence was refused: catalog schema unsupported.",
    since=UNRELEASED,
)
CONTEXT_INCOMPLETE = _d(
    "context_incomplete",
    "Signed evidence was refused: context incomplete.",
    since=UNRELEASED,
)
CONTEXT_INVALID = _d(
    "context_invalid",
    "Signed evidence was refused: context invalid.",
    since=UNRELEASED,
)
ENVELOPE_ALG_NOT_ES256 = _d(
    "envelope_alg_not_es256",
    "Signed evidence was refused: envelope alg not es256.",
    since=UNRELEASED,
)
ENVELOPE_BASE64URL_INVALID = _d(
    "envelope_base64url_invalid",
    "Signed evidence was refused: envelope base64url invalid.",
    since=UNRELEASED,
)
ENVELOPE_CRIT_INVALID = _d(
    "envelope_crit_invalid",
    "Signed evidence was refused: envelope crit invalid.",
    since=UNRELEASED,
)
ENVELOPE_CTY_INVALID = _d(
    "envelope_cty_invalid",
    "Signed evidence was refused: envelope cty invalid.",
    since=UNRELEASED,
)
ENVELOPE_HEADER_FIELD_INVALID = _d(
    "envelope_header_field_invalid",
    "Signed evidence was refused: envelope header field invalid.",
    since=UNRELEASED,
)
ENVELOPE_HEADER_FIELD_MISSING = _d(
    "envelope_header_field_missing",
    "Signed evidence was refused: envelope header field missing.",
    since=UNRELEASED,
)
ENVELOPE_HEADER_MEMBER_FORBIDDEN = _d(
    "envelope_header_member_forbidden",
    "Signed evidence was refused: envelope header member forbidden.",
    since=UNRELEASED,
)
ENVELOPE_NOT_JSON = _d(
    "envelope_not_json",
    "Signed evidence was refused: envelope not json.",
    since=UNRELEASED,
)
ENVELOPE_PAYLOAD_PRESENT = _d(
    "envelope_payload_present",
    "Signed evidence was refused: envelope payload present.",
    since=UNRELEASED,
)
ENVELOPE_PROTECTED_NOT_JSON = _d(
    "envelope_protected_not_json",
    "Signed evidence was refused: envelope protected not json.",
    since=UNRELEASED,
)
ENVELOPE_SHAPE_UNSUPPORTED = _d(
    "envelope_shape_unsupported",
    "Signed evidence was refused: envelope shape unsupported.",
    since=UNRELEASED,
)
ENVELOPE_TYP_INVALID = _d(
    "envelope_typ_invalid",
    "Signed evidence was refused: envelope typ invalid.",
    since=UNRELEASED,
)
ENVELOPE_UNPROTECTED_HEADER = _d(
    "envelope_unprotected_header",
    "Signed evidence was refused: envelope unprotected header.",
    since=UNRELEASED,
)
EXPECTATIONS_ARTIFACTS_EMPTY = _d(
    "expectations_artifacts_empty",
    "Signed evidence was refused: expectations artifacts empty.",
    since=UNRELEASED,
)
EXPECTATIONS_ARTIFACT_ID_DUPLICATE = _d(
    "expectations_artifact_id_duplicate",
    "Signed evidence was refused: expectations artifact id duplicate.",
    since=UNRELEASED,
)
EXPECTATIONS_BAD_PATH = _d(
    "expectations_bad_path",
    "Signed evidence was refused: expectations bad path.",
    since=UNRELEASED,
)
EXPECTATIONS_BAD_TOKEN = _d(
    "expectations_bad_token",
    "Signed evidence was refused: expectations bad token.",
    since=UNRELEASED,
)
EXPECTATIONS_DIGEST_MISMATCH = _d(
    "expectations_digest_mismatch",
    "Signed evidence was refused: expectations digest mismatch.",
    since=UNRELEASED,
)
EXPECTATIONS_MISSING_FIELD = _d(
    "expectations_missing_field",
    "Signed evidence was refused: expectations missing field.",
    since=UNRELEASED,
)
EXPECTATIONS_OUT_OF_RANGE = _d(
    "expectations_out_of_range",
    "Signed evidence was refused: expectations out of range.",
    since=UNRELEASED,
)
EXPECTATIONS_PIN_INVALID = _d(
    "expectations_pin_invalid",
    "Signed evidence was refused: expectations pin invalid.",
    since=UNRELEASED,
)
EXPECTATIONS_SCHEMA_UNKNOWN = _d(
    "expectations_schema_unknown",
    "Signed evidence was refused: expectations schema unknown.",
    since=UNRELEASED,
)
EXPECTATIONS_UNKNOWN_FIELD = _d(
    "expectations_unknown_field",
    "Signed evidence was refused: expectations unknown field.",
    since=UNRELEASED,
)
EXPECTATIONS_WRONG_TYPE = _d(
    "expectations_wrong_type",
    "Signed evidence was refused: expectations wrong type.",
    since=UNRELEASED,
)
INPUT_ACCESS_DENIED = _d(
    "input_access_denied",
    "Signed evidence was refused: input access denied.",
    since=UNRELEASED,
)
INPUT_INVALID = _d("input_invalid", "Signed evidence was refused: input invalid.", since=UNRELEASED)
INPUT_TOO_LARGE = _d(
    "input_too_large",
    "Signed evidence was refused: input too large.",
    since=UNRELEASED,
)
INPUT_UNAVAILABLE = _d(
    "input_unavailable",
    "Signed evidence was refused: input unavailable.",
    since=UNRELEASED,
)
LEGACY_INTEGRITY_ONLY = _d(
    "legacy_integrity_only",
    "Signed evidence was refused: legacy integrity only.",
    since=UNRELEASED,
)
PERMIT_CONSTRUCTION_FORBIDDEN = _d(
    "permit_construction_forbidden",
    "Signed evidence was refused: permit construction forbidden.",
    since=UNRELEASED,
)
PERMIT_FIELDS_INVALID = _d(
    "permit_fields_invalid",
    "Signed evidence was refused: permit fields invalid.",
    since=UNRELEASED,
)
SIGNATURE_ENCODING_INVALID = _d(
    "signature_encoding_invalid",
    "Signed evidence was refused: signature encoding invalid.",
    since=UNRELEASED,
)
SIGNER_BAD_SIGNATURE = _d(
    "signer_bad_signature",
    "Signed evidence was refused: signer bad signature.",
    since=UNRELEASED,
)
SIGNER_IDENTITY_INVALID = _d(
    "signer_identity_invalid",
    "Signed evidence was refused: signer identity invalid.",
    since=UNRELEASED,
)
SIGNER_IDENTITY_MISMATCH = _d(
    "signer_identity_mismatch",
    "Signed evidence was refused: signer identity mismatch.",
    since=UNRELEASED,
)
SIGNER_INVALID = _d(
    "signer_invalid",
    "Signed evidence was refused: signer invalid.",
    since=UNRELEASED,
)
SIGNER_KEY_INVALID = _d(
    "signer_key_invalid",
    "Signed evidence was refused: signer key invalid.",
    since=UNRELEASED,
)
SIGNER_VERIFY_UNSUPPORTED = _d(
    "signer_verify_unsupported",
    "Signed evidence was refused: signer verify unsupported.",
    since=UNRELEASED,
)
SIGNING_FAILED = _d(
    "signing_failed",
    "Signed evidence was refused: signing failed.",
    since=UNRELEASED,
)
STATEMENT_ARRAY_ORDER = _d(
    "statement_array_order",
    "Signed evidence was refused: statement array order.",
    since=UNRELEASED,
)
STATEMENT_ARTIFACT_ID_DUPLICATE = _d(
    "statement_artifact_id_duplicate",
    "Signed evidence was refused: statement artifact id duplicate.",
    since=UNRELEASED,
)
STATEMENT_COVERAGE_INVALID = _d(
    "statement_coverage_invalid",
    "Signed evidence was refused: statement coverage invalid.",
    since=UNRELEASED,
)
STATEMENT_MISSING_FIELD = _d(
    "statement_missing_field",
    "Signed evidence was refused: statement missing field.",
    since=UNRELEASED,
)
STATEMENT_NOT_CANONICAL = _d(
    "statement_not_canonical",
    "Signed evidence was refused: statement not canonical.",
    since=UNRELEASED,
)
STATEMENT_PATH_DUPLICATE = _d(
    "statement_path_duplicate",
    "Signed evidence was refused: statement path duplicate.",
    since=UNRELEASED,
)
STATEMENT_PATH_INVALID = _d(
    "statement_path_invalid",
    "Signed evidence was refused: statement path invalid.",
    since=UNRELEASED,
)
STATEMENT_PUBLICATION_INCOHERENT = _d(
    "statement_publication_incoherent",
    "Signed evidence was refused: statement publication incoherent.",
    since=UNRELEASED,
)
STATEMENT_SCHEMA_INVALID = _d(
    "statement_schema_invalid",
    "Signed evidence was refused: statement schema invalid.",
    since=UNRELEASED,
)
STATEMENT_SCHEMA_UNSUPPORTED = _d(
    "statement_schema_unsupported",
    "Signed evidence was refused: statement schema unsupported.",
    since=UNRELEASED,
)
STATEMENT_TOO_MANY_ARTIFACTS = _d(
    "statement_too_many_artifacts",
    "Signed evidence was refused: statement too many artifacts.",
    since=UNRELEASED,
)
STATEMENT_TOO_MANY_CHECKS = _d(
    "statement_too_many_checks",
    "Signed evidence was refused: statement too many checks.",
    since=UNRELEASED,
)
STATEMENT_UNKNOWN_FIELD = _d(
    "statement_unknown_field",
    "Signed evidence was refused: statement unknown field.",
    since=UNRELEASED,
)
TRUST_POLICY_ALG_UNSUPPORTED = _d(
    "trust_policy_alg_unsupported",
    "Signed evidence was refused: trust policy alg unsupported.",
    since=UNRELEASED,
)
TRUST_POLICY_DIGEST_MISMATCH = _d(
    "trust_policy_digest_mismatch",
    "Signed evidence was refused: trust policy digest mismatch.",
    since=UNRELEASED,
)
TRUST_POLICY_DUPLICATE_KID = _d(
    "trust_policy_duplicate_kid",
    "Signed evidence was refused: trust policy duplicate kid.",
    since=UNRELEASED,
)
TRUST_POLICY_KEY_CONFLICT = _d(
    "trust_policy_key_conflict",
    "Signed evidence was refused: trust policy key conflict.",
    since=UNRELEASED,
)
TRUST_POLICY_KEY_INVALID = _d(
    "trust_policy_key_invalid",
    "Signed evidence was refused: trust policy key invalid.",
    since=UNRELEASED,
)
TRUST_POLICY_LIFECYCLE_INCOHERENT = _d(
    "trust_policy_lifecycle_incoherent",
    "Signed evidence was refused: trust policy lifecycle incoherent.",
    since=UNRELEASED,
)
TRUST_POLICY_PIN_INVALID = _d(
    "trust_policy_pin_invalid",
    "Signed evidence was refused: trust policy pin invalid.",
    since=UNRELEASED,
)
TRUST_POLICY_SCHEMA_INVALID = _d(
    "trust_policy_schema_invalid",
    "Signed evidence was refused: trust policy schema invalid.",
    since=UNRELEASED,
)
TRUST_POLICY_SCHEMA_UNSUPPORTED = _d(
    "trust_policy_schema_unsupported",
    "Signed evidence was refused: trust policy schema unsupported.",
    since=UNRELEASED,
)
TRUST_POLICY_THUMBPRINT_MISMATCH = _d(
    "trust_policy_thumbprint_mismatch",
    "Signed evidence was refused: trust policy thumbprint mismatch.",
    since=UNRELEASED,
)
