"""PII / format detectors used by Pre-scan.

Each detector is a callable `(series, col_name) -> DetectorMatch | None`. The
profiler runs every registered detector against every column and attaches the
resulting matches to the column's FieldStats.

A detector returns:
    - DetectorMatch if (match_rate >= min_match_rate) OR (column name strongly
      hints at the detector). The match_rate field reports the actual fraction
      of non-null values that matched the pattern, regardless of the name hint
      that may have triggered firing.
    - None otherwise.

Conservative thresholds keep the ranked FORECAST output clean: a column with
30% email-like values shouldn't get tagged "email" - that's noise.

Built-in detector set:
  Core PII:  email, ssn, us_phone, us_zip, person_name,
             iso_date, us_date, eu_date
  PCI/GDPR (Item 31 phase 1):  pan, cvv, iban, ipv4
  HIPAA Safe Harbor + clinical (Item 31 phase 3):
    icd10, npi, mrn, url, fax_number, health_plan_id, license_num,
    vehicle_id, device_id, biometric_id
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

from decoy_engine.detection._hints import (  # noqa: F401  re-exported; external importers use this path
    _NAME_HINT_EXTRAS,
    _NAME_HINTS,
    _hint,
    _hits_name_hint,
    hits_name_hint,
    name_hint_extras,
)
from decoy_engine.detection._patterns import (  # noqa: F401  re-exported; external importers use this path
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
from decoy_engine.detection._scoring import (  # noqa: F401  re-exported constants
    DEFAULT_MIN_MATCH_RATE,
    HIGH_CONFIDENCE_NO_HINT_FLOOR,
    HIGH_CONFIDENCE_WITH_HINT_FLOOR,
    LOW_CONFIDENCE_NO_HINT_FLOOR,
    NAME_HINT_MIN_RATE,
    SAMPLE_MISS_LIMIT,
    PreparedValues,
    _evaluate,
    _series_str,
    counting_scope,
    decide_detector,
    prepared_scope,
)
from decoy_engine.detection._validators import (
    _IBAN_COUNTRIES,  # noqa: F401  re-exported; external importers use this path
    _ICD10_CHAPTERS,  # noqa: F401  re-exported; external importers use this path
    _iban_valid,
    _icd10_valid,
    _ipv4_valid,
    _iso_date_valid,  # noqa: F401  re-exported; external importers use this path
    _luhn_valid,
    _npi_valid,
)
from decoy_engine.detection.builtin import (  # noqa: F401  re-exported; external importers use this path
    _EU_DATE_VARIANTS,
    _ICD10_VARIANTS,
    _ISO_DATE_VARIANTS,
    _PAN_VARIANTS,
    _SSN_VARIANTS,
    _US_DATE_VARIANTS,
    _US_PHONE_VARIANTS,
    _US_ZIP_VARIANTS,
    _variant,
    detect_address,
    detect_biometric_id,
    detect_cvv,
    detect_device_id,
    detect_email,
    detect_eu_date,
    detect_fax_number,
    detect_first_name,
    detect_health_plan_id,
    detect_iban,
    detect_icd10,
    detect_ipv4,
    detect_iso_date,
    detect_last_name,
    detect_license_num,
    detect_mrn,
    detect_npi,
    detect_pan,
    detect_person_name,
    detect_ssn,
    detect_url,
    detect_us_date,
    detect_us_phone,
    detect_us_zip,
    detect_vehicle_id,
)
from decoy_engine.detection.types import CustomDetectorSpec, DetectorMatch

# ── registry ──────────────────────────────────────────────────────────────────────────────────

DetectorFn = Callable[[pd.Series, str], DetectorMatch | None]

REGISTERED_DETECTORS: list[DetectorFn] = [
    detect_email,
    detect_ssn,
    detect_us_phone,
    detect_us_zip,
    # Specific name detectors before the generic person_name so the
    # strategy table routes to faker.first_name / faker.last_name when the
    # column header is specific.
    detect_first_name,
    detect_last_name,
    detect_person_name,
    detect_address,
    detect_iso_date,
    detect_us_date,
    detect_eu_date,
    detect_pan,
    detect_cvv,
    detect_iban,
    detect_ipv4,
    # Item 31 phase 3 - HIPAA Safe Harbor completers + clinical identifiers.
    detect_icd10,
    detect_npi,
    detect_mrn,
    detect_url,
    detect_fax_number,
    detect_health_plan_id,
    detect_license_num,
    detect_vehicle_id,
    detect_device_id,
    detect_biometric_id,
]


def run_all_detectors(
    series: pd.Series,
    col_name: str,
    *,
    custom: list[CustomDetectorSpec] | None = None,
) -> list[DetectorMatch]:
    """Run every registered detector against a column, plus any caller-supplied
    custom detectors. Returns matches sorted by descending match_rate so the
    highest-confidence detector is first.

    Custom detectors run after the built-ins. A bad regex in one custom spec
    (e.g. malformed pattern) is logged-and-skipped rather than raising - one
    misconfigured admin entry shouldn't kill the whole scan.
    """
    matches: list[DetectorMatch] = []
    with prepared_scope(series):
        for fn in REGISTERED_DETECTORS:
            m = fn(series, col_name)
            if m is not None:
                matches.append(m)
        if custom:
            for spec in custom:
                try:
                    m = _run_custom_detector(series, col_name, spec)
                except re.error:
                    # Bad regex - skip silently. The platform validates patterns
                    # at create-time so we should rarely hit this in practice.
                    continue
                if m is not None:
                    matches.append(m)
    matches.sort(key=lambda m: m.match_rate, reverse=True)
    return matches


# ── custom detectors ──────────────────────────────────────────────────────────────────────────


def _custom_name_hint_pattern(name_hints: list[str]) -> re.Pattern[str] | None:
    """Compile a column-name-matching regex from a list of substrings.

    Mirrors the built-in `_NAME_HINTS` shape: case-insensitive, matches when
    any hint appears as a token in the column name (separated by `_-` or at
    word boundaries). Empty/whitespace hints are skipped.
    """
    cleaned = [re.escape(h.strip()) for h in name_hints if h.strip()]
    if not cleaned:
        return None
    body = "|".join(cleaned)
    return re.compile(rf"(?i)(^|[._-])({body})($|[._-])")


def _hits_custom_name_hint(spec: CustomDetectorSpec, col_name: str) -> bool:
    pat = _custom_name_hint_pattern(spec.name_hints)
    return bool(pat and pat.search(col_name or ""))


def _run_custom_detector(
    series: pd.Series,
    col_name: str,
    spec: CustomDetectorSpec,
) -> DetectorMatch | None:
    """Compile + apply one custom regex spec to a column."""
    pattern = re.compile(spec.pattern)
    name_hint = _hits_custom_name_hint(spec, col_name)
    return _evaluate(
        spec.id,
        _series_str(series),
        pattern,
        name_hint=name_hint,
        min_rate=max(0.0, min(1.0, spec.threshold)),
    )


def hits_custom_name_hint(spec: CustomDetectorSpec, col_name: str) -> bool:
    """Public accessor used by the profiler to log name-hint trail rows for
    custom detectors. Mirrors `hits_name_hint` for built-ins."""
    return _hits_custom_name_hint(spec, col_name)


# ── iter_spans: in-text PII span extraction (MG-2, 2026-05-31) ────────────────
#
# Surfaces the existing detector regexes under a span-iterating contract so
# the `text_redact` masking strategy (and future text-aware strategies) can
# replace PII spans inside free-text columns without rebuilding the regex
# catalog. Additive only: no existing detector behavior changes.
#
# Public surface:
#   - `Span` dataclass (detector_id, start, end, matched_text)
#   - `iter_spans(text, detector_ids=None, *, custom=None) -> list[Span]`
#
# Overlap policy: leftmost-then-longest. Sort by (start, -length) and keep
# the first span; drop any subsequent span whose [start, end) overlaps a
# kept span. Priority-based resolution (e.g. SSN beats person_name) is a
# fast-follow if customers ask.

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A non-overlapping PII span inside a text cell.

    `detector_id` matches the keys in `_SPAN_DETECTORS` (``"email"``,
    ``"ssn"``, ``"us_phone"``, ``"pan"``, ``"npi"``, ``"icd10"``,
    ``"iban"``, etc).
    """

    detector_id: str
    start: int
    end: int
    matched_text: str


# Street addresses in free text (deferred follow-up 8a, 2026-06-12).
# Pure regex, no spaCy: a leading house number plus a USPS street-suffix
# anchor is unambiguous enough for prose, unlike the name-hint-only
# column-level `address` detector. Suffix vocabulary: USPS Publication
# 28, Appendix C1 (primary street suffix names + standard abbreviations),
# curated to the high-frequency entries; secondary-unit designators
# (Apt/Suite/Unit/#, Pub 28 Appendix C2) ride along optionally.
_USPS_STREET_SUFFIXES: tuple[str, ...] = (
    "street",
    "st",
    "avenue",
    "ave",
    "boulevard",
    "blvd",
    "road",
    "rd",
    "drive",
    "dr",
    "lane",
    "ln",
    "court",
    "ct",
    "circle",
    "cir",
    "place",
    "pl",
    "terrace",
    "ter",
    "trail",
    "trl",
    "parkway",
    "pkwy",
    "highway",
    "hwy",
    "way",
    "plaza",
    "plz",
    "square",
    "sq",
    "expressway",
    "expy",
    "freeway",
    "fwy",
    "crossing",
    "xing",
    "loop",
    "alley",
    "aly",
    "bend",
    "cove",
    "cv",
    "point",
    "pt",
    "ridge",
    "rdg",
)
_STREET_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+"  # house number
    # 1-4 street-name words; the leading [A-Za-z0-9] admits ordinal names
    # ("5th", "42nd") while the suffix anchor keeps bare number runs out.
    r"(?:[A-Za-z0-9][A-Za-z0-9'.\-]*\s+){1,4}"
    r"(?:" + "|".join(_USPS_STREET_SUFFIXES) + r")\.?"  # Pub 28 C1 suffix
    r"(?:\s+(?:apt|apartment|suite|ste|unit|#)\.?\s*[\w\-]+)?"  # C2 unit
    r"(?=[\s,.;:!?)\"']|$)",
    re.IGNORECASE,
)

# Map from detector_id to (compiled_regex, optional_validator). Validators
# are the same per-value functions that `_evaluate` already calls; reusing
# them here keeps the column-level + span-level detector behavior in sync.
# Mirrors the existing module-level `_*_RE` constants.
#
# `person_name` / name-hint-only detectors (license_num,
# health_plan_id, device_id, biometric_id, vehicle_id, mrn) are intentionally
# OMITTED: their regexes are too loose to use without a column-name signal
# (per the existing docstrings on each). The text_redact contract is "find
# unambiguous PII inside free text" - adding name-hint-only detectors here
# would shred legitimate prose. Customers needing those detectors in text
# pass them via the `custom` kwarg with a tighter pattern.
# `street_address` is the exception that proves the rule: the house-number
# + USPS-suffix anchor makes it unambiguous without a column-name signal.
_SPAN_DETECTORS: dict[str, tuple[re.Pattern[str], Callable[[str], bool] | None]] = {
    "email": (_EMAIL_RE, None),
    "ssn": (_SSN_RE, None),
    "us_phone": (_US_PHONE_RE, None),
    "us_zip": (_US_ZIP_RE, None),
    "pan": (_PAN_RE, _luhn_valid),
    "iban": (_IBAN_RE, _iban_valid),
    "ipv4": (_IPV4_RE, _ipv4_valid),
    "icd10": (_ICD10_RE, _icd10_valid),
    "npi": (_NPI_RE, _npi_valid),
    "url": (_URL_RE, None),
    "street_address": (_STREET_ADDRESS_RE, None),
}


def iter_spans(
    text: str,
    detector_ids: list[str] | None = None,
    *,
    custom: list[dict] | None = None,
    extra_spans: list[Span] | None = None,
) -> list[Span]:
    """Yield non-overlapping PII spans found in ``text``.

    ``detector_ids`` selects which built-in detectors run; ``None`` runs every
    detector in `_SPAN_DETECTORS`. Unknown detector ids are silently skipped
    (matches the platform's per-tenant detector-overrides shape, where the
    same id might be present on one tenant and absent on another).

    ``custom`` is an optional list of one-shot detector specs of shape
    ``{"detector_id": str, "pattern": re.Pattern, "validator": callable | None}``.
    Custom detectors run after the built-ins and are subject to the same
    overlap dedupe.

    ``extra_spans`` (WS2, 2026-06-12) injects pre-computed spans -- e.g.
    NER hits from `detection.ner.iter_ner_spans` -- into the SAME overlap
    resolution as the regex spans, so a regex SSN and an NER person name
    covering overlapping text resolve leftmost-then-longest instead of
    double-splicing.

    Returns spans sorted by ``.start``, with overlaps resolved by keeping
    the leftmost-then-longest match.
    """
    if not isinstance(text, str) or not text:
        return []
    if detector_ids is None:
        detector_ids = list(_SPAN_DETECTORS.keys())

    raw_spans: list[Span] = list(extra_spans or [])
    for det_id in detector_ids:
        entry = _SPAN_DETECTORS.get(det_id)
        if entry is None:
            continue
        regex, validator = entry
        for m in regex.finditer(text):
            matched = m.group(0)
            if validator is not None and not validator(matched):
                continue
            raw_spans.append(Span(det_id, m.start(), m.end(), matched))

    for spec in custom or []:
        pattern = spec["pattern"]
        validator = spec.get("validator")
        det_id = spec["detector_id"]
        for m in pattern.finditer(text):
            matched = m.group(0)
            if validator is not None and not validator(matched):
                continue
            raw_spans.append(Span(det_id, m.start(), m.end(), matched))

    raw_spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Span] = []
    last_end = -1
    for s in raw_spans:
        if s.start >= last_end:
            out.append(s)
            last_end = s.end

    return out
