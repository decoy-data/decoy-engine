"""The built-in column detectors (``detect_*``) and their format-variant tables.

Moved verbatim from ``detection/detectors.py``, which re-exports every name here and owns the
registry that runs them.
"""

from __future__ import annotations

import re

import pandas as pd

from decoy_engine.detection._hints import _hits_name_hint
from decoy_engine.detection._patterns import (
    _ADDRESS_RE,
    _BIOMETRIC_ID_RE,
    _CVV_RE,
    _DEVICE_ID_RE,
    _EMAIL_RE,
    _EU_DATE_RE,
    _FAX_NUMBER_RE,
    _HEALTH_PLAN_ID_RE,
    _IBAN_RE,
    _ICD10_RE,
    _IPV4_RE,
    _ISO_DATE_RE,
    _LICENSE_NUM_RE,
    _MRN_RE,
    _NPI_RE,
    _PAN_RE,
    _PERSON_NAME_RE,
    _SSN_RE,
    _URL_RE,
    _US_DATE_RE,
    _US_PHONE_RE,
    _US_ZIP_RE,
    _VEHICLE_ID_RE,
)
from decoy_engine.detection._scoring import (
    DEFAULT_MIN_MATCH_RATE,
    NAME_HINT_MIN_RATE,
    _evaluate,
    _series_str,
)
from decoy_engine.detection._validators import (
    _iban_valid,
    _icd10_valid,
    _ipv4_valid,
    _iso_date_valid,
    _luhn_valid,
    _npi_valid,
)
from decoy_engine.detection.types import DetectorMatch

# ── format variants (Item 65) ───────────────────────────────────────────────────────────────
#
# Per-detector ordered (label, regex) pairs that classify which sub-shape
# of the detector's parent pattern actually fired. The label is what the
# mask post-pass reads - for regex-style detectors (SSN, phone, ZIP) it's
# the regex shape; for date detectors it's a strptime format string the
# date_shift strategy can pass directly to dt.strftime().


def _variant(label: str) -> tuple[str, re.Pattern[str]]:
    """F-8 fix: derive the compiled regex from the label so the two cannot
    drift. Used by the regex-style variants where ``label == regex_source``.
    The date variants below intentionally pass an independent label
    (a strptime format string) so they cannot use this helper."""
    return label, re.compile(label)


_SSN_VARIANTS = [
    _variant(r"\d{3}-\d{2}-\d{4}"),
    _variant(r"\d{9}"),
]

_US_PHONE_VARIANTS = [
    # NB: most distinctive shapes first so e.g. "(NNN) NNN-NNNN" doesn't
    # leak into the bare-dash bucket.
    _variant(r"\(\d{3}\) \d{3}-\d{4}"),
    _variant(r"\(\d{3}\)\d{3}-\d{4}"),
    _variant(r"\d{3}-\d{3}-\d{4}"),
    _variant(r"\d{3}\.\d{3}\.\d{4}"),
    _variant(r"\d{3} \d{3} \d{4}"),
    _variant(r"\+1 \d{3} \d{3} \d{4}"),
    _variant(r"\+1-\d{3}-\d{3}-\d{4}"),
    _variant(r"\d{10}"),
]

_US_ZIP_VARIANTS = [
    _variant(r"\d{5}-\d{4}"),
    # QA-3 F6 (2026-05-31): the bare 5-digit variant gets the same
    # non-word boundary protection as the iter_spans pattern; otherwise
    # the format-variant rate calculation accepts any 5-digit substring
    # in a measurement column as a us_zip match.
    _variant(r"(?<!\w)\d{5}(?!\w)(?!\.\d)"),
]

# Date detectors map directly to strptime - the format_pattern label is
# what date_shift's dt.strftime() will consume on the masked output.
_ISO_DATE_VARIANTS = [
    ("%Y-%m-%dT%H:%M:%SZ", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")),
    ("%Y-%m-%dT%H:%M:%S", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")),
    ("%Y-%m-%d %H:%M:%S", re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")),
    ("%Y-%m-%dT%H:%M", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")),
    ("%Y-%m-%d %H:%M", re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")),
    ("%Y-%m-%d", re.compile(r"\d{4}-\d{2}-\d{2}")),
    ("%Y%m%d", re.compile(r"\d{8}")),
]
_US_DATE_VARIANTS = [
    ("%m/%d/%Y", re.compile(r"\d{1,2}/\d{1,2}/\d{4}")),
    ("%m/%d/%y", re.compile(r"\d{1,2}/\d{1,2}/\d{2}")),
]
_EU_DATE_VARIANTS = [
    ("%d.%m.%Y", re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")),
    ("%d.%m.%y", re.compile(r"\d{1,2}\.\d{1,2}\.\d{2}")),
    ("%d-%m-%Y", re.compile(r"\d{1,2}-\d{1,2}-\d{4}")),
]

_PAN_VARIANTS = [
    _variant(r"\d{4} \d{4} \d{4} \d{4}"),
    _variant(r"\d{4}-\d{4}-\d{4}-\d{4}"),
    _variant(r"\d{16}"),
    _variant(r"\d{15}"),  # Amex
    _variant(r"\d{14}"),  # Diners
]

_ICD10_VARIANTS = [
    _variant(r"[A-Z]\d{2}\.[A-Z0-9]{1,4}"),
    _variant(r"[A-Z]\d{2}"),
    _variant(r"[A-Z]\d{2}[A-Z0-9]{1,4}"),
]


# ── detectors (callables) ───────────────────────────────────────────────────────────────────


def detect_email(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "email",
        _series_str(series),
        _EMAIL_RE,
        name_hint=_hits_name_hint("email", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
    )


def detect_ssn(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "ssn",
        _series_str(series),
        _SSN_RE,
        name_hint=_hits_name_hint("ssn", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        format_variants=_SSN_VARIANTS,
    )


def detect_us_phone(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "us_phone",
        _series_str(series),
        _US_PHONE_RE,
        name_hint=_hits_name_hint("us_phone", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        format_variants=_US_PHONE_VARIANTS,
    )


def detect_us_zip(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "us_zip",
        _series_str(series),
        _US_ZIP_RE,
        name_hint=_hits_name_hint("us_zip", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        format_variants=_US_ZIP_VARIANTS,
    )


def detect_person_name(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Heuristic: name-hinted column name + values look like proper-cased tokens.

    Without a strong column-name hint, person_name is too noisy - most short
    string columns happen to "look like names" by this regex. Require the hint.
    """
    if not _hits_name_hint("person_name", col_name):
        return None
    return _evaluate(
        "person_name",
        _series_str(series),
        _PERSON_NAME_RE,
        name_hint=True,
        min_rate=DEFAULT_MIN_MATCH_RATE,
    )


def detect_first_name(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """First-name columns (fn, f_name, firstname, mm_fn, cust_fn, ...).

    Detection sprint (V1): split out from person_name so the strategy
    table routes to faker.first_name (single token, gendered shape)
    instead of faker.name. Name-hint only - value regex is the same as
    person_name.
    """
    if not _hits_name_hint("first_name", col_name):
        return None
    return _evaluate(
        "first_name",
        _series_str(series),
        _PERSON_NAME_RE,
        name_hint=True,
        min_rate=NAME_HINT_MIN_RATE,
    )


def detect_last_name(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Last-name columns (ln, l_name, lastname, surname, mm_ln, cust_ln, ...).

    Detection sprint (V1) sibling of detect_first_name. Routes to
    faker.last_name in the strategy table.
    """
    if not _hits_name_hint("last_name", col_name):
        return None
    return _evaluate(
        "last_name",
        _series_str(series),
        _PERSON_NAME_RE,
        name_hint=True,
        min_rate=NAME_HINT_MIN_RATE,
    )


def detect_address(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Street addresses (addr, addr1, line1, street_1, mailing_address, ...).

    Detection sprint (V1). Name-hint only - street formats vary too widely
    (rural routes, military APO, PO boxes, international) for a meaningful
    value regex. The address regex just filters out obviously non-address
    values (pure phone numbers, plain prose without a leading digit).
    """
    if not _hits_name_hint("address", col_name):
        return None
    return _evaluate(
        "address", _series_str(series), _ADDRESS_RE, name_hint=True, min_rate=NAME_HINT_MIN_RATE
    )


def detect_iso_date(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "iso_date",
        _series_str(series),
        _ISO_DATE_RE,
        name_hint=_hits_name_hint("iso_date", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_iso_date_valid,
        format_variants=_ISO_DATE_VARIANTS,
    )


def detect_us_date(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "us_date",
        _series_str(series),
        _US_DATE_RE,
        name_hint=_hits_name_hint("us_date", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        format_variants=_US_DATE_VARIANTS,
    )


def detect_eu_date(series: pd.Series, col_name: str) -> DetectorMatch | None:
    return _evaluate(
        "eu_date",
        _series_str(series),
        _EU_DATE_RE,
        name_hint=_hits_name_hint("eu_date", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        format_variants=_EU_DATE_VARIANTS,
    )


def detect_pan(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Credit-card PAN. Regex picks up 13-19-digit groups; Luhn checksum
    rejects random digit strings so a 16-digit phone stub or transaction
    ID doesn't false-positive."""
    return _evaluate(
        "pan",
        _series_str(series),
        _PAN_RE,
        name_hint=_hits_name_hint("pan", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_luhn_valid,
        format_variants=_PAN_VARIANTS,
    )


def detect_cvv(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """CVV / CVC. Any 3-digit string matches the regex, so the detector
    only fires on a strong column-name hint - false-positive rate
    without the hint would be unmanageable."""
    if not _hits_name_hint("cvv", col_name):
        return None
    return _evaluate(
        "cvv", _series_str(series), _CVV_RE, name_hint=True, min_rate=DEFAULT_MIN_MATCH_RATE
    )


def detect_iban(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """IBAN - country code + checksum + BBAN. Mod-97 validates the
    checksum so random alphanumeric strings don't false-positive."""
    return _evaluate(
        "iban",
        _series_str(series),
        _IBAN_RE,
        name_hint=_hits_name_hint("iban", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_iban_valid,
    )


def detect_ipv4(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """IPv4 dotted-quad. Validator clamps each octet to 0-255 so
    "999.1.1.1" is rejected even though it matches the regex."""
    return _evaluate(
        "ipv4",
        _series_str(series),
        _IPV4_RE,
        name_hint=_hits_name_hint("ipv4", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_ipv4_valid,
    )


def detect_icd10(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """ICD-10-CM diagnosis codes. Regex matches the chapter-letter + 2-digit
    category structure; validator enforces minimal structural rules to reduce
    false-positives on short arbitrary strings. Fires on value pattern alone;
    name hint lowers the threshold."""
    return _evaluate(
        "icd10",
        _series_str(series),
        _ICD10_RE,
        name_hint=_hits_name_hint("icd10", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_icd10_valid,
        format_variants=_ICD10_VARIANTS,
    )


def detect_npi(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """National Provider Identifier - 10-digit with CMS Luhn check digit."""
    return _evaluate(
        "npi",
        _series_str(series),
        _NPI_RE,
        name_hint=_hits_name_hint("npi", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
        validator=_npi_valid,
    )


def detect_mrn(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Medical Record Number - no universal format; fires on name hint only.
    The alphanumeric pattern guards against obviously non-identifier values
    (plain prose, floats, very short strings)."""
    if not _hits_name_hint("mrn", col_name):
        return None
    return _evaluate(
        "mrn", _series_str(series), _MRN_RE, name_hint=True, min_rate=NAME_HINT_MIN_RATE
    )


def detect_url(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Web URLs - http/https scheme. Fires on value pattern alone (no
    name hint required) since the URL format is distinctive enough."""
    return _evaluate(
        "url",
        _series_str(series),
        _URL_RE,
        name_hint=_hits_name_hint("url", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
    )


def detect_fax_number(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Fax numbers - identical format to US phone; name hint is the only
    way to distinguish a fax column from a phone column."""
    if not _hits_name_hint("fax_number", col_name):
        return None
    return _evaluate(
        "fax_number",
        _series_str(series),
        _FAX_NUMBER_RE,
        name_hint=True,
        min_rate=DEFAULT_MIN_MATCH_RATE,
    )


def detect_health_plan_id(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Health-plan beneficiary / member / subscriber IDs - name hint only.
    No standard value format; meaning lives in the column name."""
    if not _hits_name_hint("health_plan_id", col_name):
        return None
    return _evaluate(
        "health_plan_id",
        _series_str(series),
        _HEALTH_PLAN_ID_RE,
        name_hint=True,
        min_rate=NAME_HINT_MIN_RATE,
    )


def detect_license_num(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Certificate and license numbers - name hint only. Formats vary by
    state / regulatory body; the column name is the definitive signal."""
    if not _hits_name_hint("license_num", col_name):
        return None
    return _evaluate(
        "license_num",
        _series_str(series),
        _LICENSE_NUM_RE,
        name_hint=True,
        min_rate=NAME_HINT_MIN_RATE,
    )


def detect_vehicle_id(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Vehicle identifiers. The VIN format (17 alphanum, no I/O/Q per ISO 3779)
    fires without a name hint; name hint lowers the threshold for partial or
    non-VIN vehicle identifiers."""
    return _evaluate(
        "vehicle_id",
        _series_str(series),
        _VEHICLE_ID_RE,
        name_hint=_hits_name_hint("vehicle_id", col_name),
        min_rate=DEFAULT_MIN_MATCH_RATE,
    )


def detect_device_id(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Device identifiers and serial numbers - name hint only. Medical device
    UDIs, implant serial numbers, and equipment IDs have no shared format."""
    if not _hits_name_hint("device_id", col_name):
        return None
    return _evaluate(
        "device_id", _series_str(series), _DEVICE_ID_RE, name_hint=True, min_rate=NAME_HINT_MIN_RATE
    )


def detect_biometric_id(series: pd.Series, col_name: str) -> DetectorMatch | None:
    """Biometric identifiers (fingerprints, retina scans, etc.) - name hint only.
    Biometric data has no universal string format; the column name is definitive."""
    if not _hits_name_hint("biometric_id", col_name):
        return None
    return _evaluate(
        "biometric_id",
        _series_str(series),
        _BIOMETRIC_ID_RE,
        name_hint=True,
        min_rate=NAME_HINT_MIN_RATE,
    )
