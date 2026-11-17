"""decoy_engine.detection - PII/format span detection (the base layer).

Detection is the base layer shared by the Pre-scan (profiling) and Post-scan
(verification) phases: both depend on it, never the reverse.
"""

from decoy_engine.detection._model_status import (
    ModelStatus,
    ModelUnavailableError,
    log_detector_models,
    log_detector_run,
    ner_model_state,
    ner_status,
    qualified,
    refuse,
)
from decoy_engine.detection._ner_rate import NerRate, RateBucket, ner_min_rate, ner_rates
from decoy_engine.detection.detectors import REGISTERED_DETECTORS, Span
from decoy_engine.detection.domains import DOMAIN_BY_DETECTOR, Domain, domain_for
from decoy_engine.detection.name_hints.loader import load_name_hint_terms
from decoy_engine.detection.ner import NerUnavailableError
from decoy_engine.detection.types import (
    CustomDetectorSpec,
    DetectionSignal,
    DetectorMatch,
    DetectorRun,
    ModelRef,
)

__all__ = [
    "DOMAIN_BY_DETECTOR",
    "REGISTERED_DETECTORS",
    "CustomDetectorSpec",
    "DetectionSignal",
    "DetectorMatch",
    "DetectorRun",
    "Domain",
    "ModelRef",
    "ModelStatus",
    "ModelUnavailableError",
    "NerRate",
    "NerUnavailableError",
    "RateBucket",
    "Span",
    "domain_for",
    "load_name_hint_terms",
    "log_detector_models",
    "log_detector_run",
    "ner_min_rate",
    "ner_model_state",
    "ner_rates",
    "ner_status",
    "qualified",
    "refuse",
]
