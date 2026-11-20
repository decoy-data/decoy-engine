"""Characterization pins for `detection.detectors` across its module split.

Recorded on the unsplit file and held byte-equal after it: every built-in detector's
`run_all_detectors` output on one fixed frame (plus a custom spec and per-scan name-hint
extras), `iter_spans` spans on one fixed text, and every name callers import from
`decoy_engine.detection.detectors` or `decoy_engine.detection`.
"""

from __future__ import annotations

import dataclasses
import importlib
import re

import pandas as pd
import pytest

from decoy_engine.detection.detectors import (
    Span,
    iter_spans,
    name_hint_extras,
    run_all_detectors,
)
from decoy_engine.detection.types import CustomDetectorSpec

FRAME: dict[str, list[object]] = {
    "email": ["a@example.com", "b@test.org", "c@x.io", None, "not an email"],
    "ssn": ["123-45-6789", "987-65-4321", "111223333", "555-55-5555"],
    "phone": ["(555) 123-4567", "555-987-6543", "555.111.2222", "5551112222"],
    "zip": ["12345", "98765-4321", "54321", "00501"],
    "first_name": ["Alice", "Bob", "Carol", "Dave"],
    "last_name": ["Smith", "Jones", "Brown", "Lee"],
    "name": ["Alice Smith", "Bob Jones", "Carol Brown", "Dave Lee"],
    "address": ["12 Main St", "400 Oak Ave Apt 2", "9 Elm Rd", "77 Pine Ln"],
    "dob": ["2020-01-31", "1999-12-01", "2001-06-15", "1980-02-29"],
    "visit_date": ["01/31/2020", "12/1/1999", "6/15/01", "2/29/1980"],
    "datum": ["31.01.2020", "1.12.1999", "15-06-2001", "29.2.80"],
    "card_number": ["4111111111111111", "5500000000000004", "340000000000009", "4012888888881881"],
    "cvv": ["123", "456", "789", "012"],
    "iban": ["GB82WEST12345698765432", "DE89370400440532013000", "FR1420041010050500013M02606"],
    "ip_address": ["192.168.0.1", "10.0.0.255", "8.8.8.8", "999.1.1.1"],
    "diagnosis_code": ["E11.9", "I10", "J45.909", "Z00.00"],
    "npi": ["1234567893", "1245319599", "1003000126", "1111111111"],
    "mrn": ["MRN12345", "A1234567", "XYZ98765", "00012345"],
    "website": ["https://example.com", "http://a.b/c", "https://x.org/p?q=1", "ftp://no"],
    "fax": ["555-123-4567", "(555) 222-3333", "555.444.5555", "5556667777"],
    "member_id": ["W123456789", "XZ9988776", "H00011122", "M55544433"],
    "license_number": ["D1234567", "CA-998877", "LIC00042", "NY12-3456"],
    "vin": ["1HGCM82633A004352", "JH4KA7561PC008269", "WVWZZZ1JZXW000001", "not-a-vin"],
    "device_serial": ["SN-0001-AB", "UDI12345678", "DEV998877", "X1Y2Z3W4"],
    "biometric_id": ["FP-000123", "RET998877", "BIO55544", "IRIS0001"],
    "notes": ["call me at 555-123-4567", "lorem ipsum", "mail a@b.co", "nothing here"],
    "amount": ["12.50", "99.99", "0.01", "1000"],
    "ticket_ref": ["TCK-0001", "TCK-0002", "TCK-0003", "OTHER-9"],
    "taxid": ["123-45-6789", "987-65-4321", "222-33-4444", "555-66-7777"],
}

CUSTOM = [
    CustomDetectorSpec(id="custom__ticket", pattern=r"TCK-\d{4}", name_hints=["ticket"]),
    CustomDetectorSpec(id="custom__bad", pattern="(", name_hints=["ticket"]),
]
EXTRAS = {"ssn": ["taxid"], "email": []}

TEXT = (
    "Mail a@example.com or call (555) 123-4567; SSN 123-45-6789 and 987654321, card "
    "4111 1111 1111 1111 (bad 4111 1111 1111 1112), ip 192.168.0.1, IBAN GB82WEST12345698765432, "
    "NPI 1234567893, code E11.9, see https://x.org/p at 12 Main Street Apt 4, zip 12345-6789."
)

# Names callers import from `decoy_engine.detection.detectors` (src, scripts, tests) plus
# every module-level definition of the unsplit file.
DETECTORS_NAMES = [
    "DEFAULT_MIN_MATCH_RATE",
    "HIGH_CONFIDENCE_NO_HINT_FLOOR",
    "HIGH_CONFIDENCE_WITH_HINT_FLOOR",
    "LOW_CONFIDENCE_NO_HINT_FLOOR",
    "NAME_HINT_MIN_RATE",
    "SAMPLE_MISS_LIMIT",
    "DetectorFn",
    "PreparedValues",
    "REGISTERED_DETECTORS",
    "Span",
    "_CVV_RE",
    "_EMAIL_RE",
    "_EU_DATE_RE",
    "_EU_DATE_VARIANTS",
    "_IBAN_COUNTRIES",
    "_IBAN_RE",
    "_ICD10_CHAPTERS",
    "_ICD10_RE",
    "_ICD10_VARIANTS",
    "_IPV4_RE",
    "_ISO_DATE_RE",
    "_ISO_DATE_VARIANTS",
    "_NAME_HINTS",
    "_NAME_HINT_EXTRAS",
    "_NPI_RE",
    "_PAN_RE",
    "_PAN_VARIANTS",
    "_PERSON_NAME_RE",
    "_SPAN_DETECTORS",
    "_SSN_RE",
    "_SSN_VARIANTS",
    "_STREET_ADDRESS_RE",
    "_USPS_STREET_SUFFIXES",
    "_US_DATE_RE",
    "_US_DATE_VARIANTS",
    "_US_PHONE_RE",
    "_US_PHONE_VARIANTS",
    "_US_ZIP_RE",
    "_US_ZIP_VARIANTS",
    "_custom_name_hint_pattern",
    "_evaluate",
    "_hint",
    "_hits_custom_name_hint",
    "_hits_name_hint",
    "_iban_valid",
    "_icd10_valid",
    "_ipv4_valid",
    "_iso_date_valid",
    "_luhn_valid",
    "_npi_valid",
    "_run_custom_detector",
    "_series_str",
    "_variant",
    "counting_scope",
    "decide_detector",
    "detect_address",
    "detect_biometric_id",
    "detect_cvv",
    "detect_device_id",
    "detect_email",
    "detect_eu_date",
    "detect_fax_number",
    "detect_first_name",
    "detect_health_plan_id",
    "detect_iban",
    "detect_icd10",
    "detect_ipv4",
    "detect_iso_date",
    "detect_last_name",
    "detect_license_num",
    "detect_mrn",
    "detect_npi",
    "detect_pan",
    "detect_person_name",
    "detect_ssn",
    "detect_url",
    "detect_us_date",
    "detect_us_phone",
    "detect_us_zip",
    "detect_vehicle_id",
    "hits_custom_name_hint",
    "hits_name_hint",
    "iter_spans",
    "name_hint_extras",
    "prepared_scope",
    "run_all_detectors",
]

REGISTRY_ORDER = [
    "detect_email",
    "detect_ssn",
    "detect_us_phone",
    "detect_us_zip",
    "detect_first_name",
    "detect_last_name",
    "detect_person_name",
    "detect_address",
    "detect_iso_date",
    "detect_us_date",
    "detect_eu_date",
    "detect_pan",
    "detect_cvv",
    "detect_iban",
    "detect_ipv4",
    "detect_icd10",
    "detect_npi",
    "detect_mrn",
    "detect_url",
    "detect_fax_number",
    "detect_health_plan_id",
    "detect_license_num",
    "detect_vehicle_id",
    "detect_device_id",
    "detect_biometric_id",
]


def _matches(col: str, values: list[object]) -> list[tuple]:
    found = run_all_detectors(pd.Series(values, dtype=object), col, custom=CUSTOM)
    return [tuple(dataclasses.astuple(m)) for m in found]


def observed_matches() -> dict[str, list[tuple]]:
    out = {col: _matches(col, vals) for col, vals in FRAME.items()}
    with name_hint_extras(EXTRAS):
        out["extras:taxid"] = _matches("taxid", FRAME["taxid"])
    return out


def observed_spans() -> dict[str, list[tuple]]:
    custom = [{"detector_id": "custom__word", "pattern": re.compile(r"Mail"), "validator": None}]
    extra = [Span("person_name", 0, 4, "Mail")]
    runs = {
        "all": iter_spans(TEXT),
        "subset": iter_spans(TEXT, ["ssn", "pan", "unknown_id"]),
        "custom": iter_spans(TEXT, [], custom=custom),
        "extra": iter_spans(TEXT, ["email"], extra_spans=extra),
    }
    return {k: [dataclasses.astuple(s) for s in v] for k, v in runs.items()}


EXPECTED_MATCHES: dict[str, list[tuple]] = {
    "email": [("email", 0.75, ["not an email"], None, "high", "CONTACT")],
    "ssn": [("ssn", 0.75, ["987-65-4321"], "\\d{3}-\\d{2}-\\d{4}", "high", "IDENTITY")],
    "phone": [],
    "zip": [("us_zip", 1.0, [], "(?<!\\w)\\d{5}(?!\\w)(?!\\.\\d)", "high", "LOCATION")],
    "first_name": [
        ("first_name", 1.0, [], None, "high", "IDENTITY"),
        ("person_name", 1.0, [], None, "high", "IDENTITY"),
    ],
    "last_name": [
        ("last_name", 1.0, [], None, "high", "IDENTITY"),
        ("person_name", 1.0, [], None, "high", "IDENTITY"),
    ],
    "name": [("person_name", 1.0, [], None, "high", "IDENTITY")],
    "address": [("address", 1.0, [], None, "high", "LOCATION")],
    "dob": [("iso_date", 1.0, [], "%Y-%m-%d", "high", "IDENTITY")],
    "visit_date": [("us_date", 1.0, [], "%m/%d/%Y", "high", "IDENTITY")],
    "datum": [("eu_date", 1.0, [], "%d.%m.%Y", "high", "IDENTITY")],
    "card_number": [("pan", 1.0, [], "\\d{16}", "high", "FINANCIAL")],
    "cvv": [("cvv", 1.0, [], None, "high", "FINANCIAL")],
    "iban": [("iban", 1.0, [], None, "high", "FINANCIAL")],
    "ip_address": [("ipv4", 0.75, ["999.1.1.1"], None, "high", "IDENTITY")],
    "diagnosis_code": [("icd10", 1.0, [], "[A-Z]\\d{2}\\.[A-Z0-9]{1,4}", "high", "HEALTH")],
    "npi": [("npi", 0.75, ["1111111111"], None, "high", "HEALTH")],
    "mrn": [("mrn", 1.0, [], None, "high", "HEALTH")],
    "website": [("url", 0.75, ["ftp://no"], None, "high", "CONTACT")],
    "fax": [
        ("us_phone", 0.75, ["555-123-4567"], "\\(\\d{3}\\) \\d{3}-\\d{4}", "high", "CONTACT"),
        ("fax_number", 0.75, ["555-123-4567"], None, "high", "CONTACT"),
    ],
    "member_id": [("health_plan_id", 1.0, [], None, "high", "HEALTH")],
    "license_number": [("license_num", 1.0, [], None, "high", "HEALTH")],
    "vin": [("vehicle_id", 0.75, ["not-a-vin"], None, "high", "IDENTITY")],
    "device_serial": [("device_id", 1.0, [], None, "high", "HEALTH")],
    "biometric_id": [("biometric_id", 1.0, [], None, "high", "HEALTH")],
    "notes": [],
    "amount": [],
    "ticket_ref": [("custom__ticket", 0.75, ["OTHER-9"], None, "high", "OTHER")],
    "taxid": [("ssn", 0.75, ["987-65-4321"], "\\d{3}-\\d{2}-\\d{4}", "high", "IDENTITY")],
    "extras:taxid": [("ssn", 0.75, ["987-65-4321"], "\\d{3}-\\d{2}-\\d{4}", "high", "IDENTITY")],
}

EXPECTED_SPANS: dict[str, list[tuple]] = {
    "all": [
        ("email", 5, 18, "a@example.com"),
        ("ssn", 47, 58, "123-45-6789"),
        ("pan", 79, 98, "4111 1111 1111 1111"),
        ("ipv4", 129, 140, "192.168.0.1"),
        ("iban", 147, 169, "GB82WEST12345698765432"),
        ("npi", 175, 185, "1234567893"),
        ("icd10", 192, 197, "E11.9"),
        ("url", 203, 218, "https://x.org/p"),
        ("street_address", 222, 242, "12 Main Street Apt 4"),
        ("ssn", 248, 258, "12345-6789"),
    ],
    "subset": [
        ("ssn", 47, 58, "123-45-6789"),
        ("pan", 79, 98, "4111 1111 1111 1111"),
        ("ssn", 155, 164, "123456987"),
        ("ssn", 175, 184, "123456789"),
        ("ssn", 248, 258, "12345-6789"),
    ],
    "custom": [("custom__word", 0, 4, "Mail")],
    "extra": [("person_name", 0, 4, "Mail"), ("email", 5, 18, "a@example.com")],
}


def test_run_all_detectors_output_is_pinned() -> None:
    assert observed_matches() == EXPECTED_MATCHES


def test_iter_spans_output_is_pinned() -> None:
    assert observed_spans() == EXPECTED_SPANS


@pytest.mark.parametrize("name", sorted(set(DETECTORS_NAMES)))
def test_name_still_imports_from_detectors(name: str) -> None:
    module = importlib.import_module("decoy_engine.detection.detectors")
    assert hasattr(module, name)


def test_package_exports_still_import() -> None:
    package = importlib.import_module("decoy_engine.detection")
    detectors = importlib.import_module("decoy_engine.detection.detectors")
    assert all(hasattr(package, name) for name in package.__all__)
    assert package.REGISTERED_DETECTORS is detectors.REGISTERED_DETECTORS
    assert package.Span is detectors.Span


def test_registry_order_is_pinned() -> None:
    from decoy_engine.detection.detectors import REGISTERED_DETECTORS

    assert [fn.__name__ for fn in REGISTERED_DETECTORS] == REGISTRY_ORDER
