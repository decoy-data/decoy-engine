"""The pre-scan model pass: classifier and NER hits for one table's sample frame.

The classifier reads each column's values as a 60-row subsample (`classify_frame(subsample=True)`,
the size it was trained on) and a column whose label is not `none` and whose band is `high` or
`review` yields one hit; a `low` band yields none and one count in the log. NER scores a column
only through `ner_rates`, which holds the free-text rule and the one definition of a hit
(`NerRate.hit`); this module never calls the span iterator itself, so a short-value column of names
cannot reach spaCy by another route.

The result is value-free by construction: a `ModelHit` holds a source, a detector id, a model
ref, a band and a rate bucket, and the log line holds counts. Spans are counted inside
`ner_rates` and dropped. A classifier label with no row in the descriptor map yields no hit and one
`unmapped_labels` count, so a new pack label shows in the log instead of vanishing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

import pandas as pd

from decoy_engine.detection import ModelRef, log_detector_models, ner_rates
from decoy_engine.profiling.model_pack import DetectorSet, classify_frame
from decoy_engine.profiling.recommendations import classifier_detector_id

Band = Literal["high", "review"]
RateBucket = Literal["<10%", "10-50%", ">=50%"]


@dataclass(frozen=True)
class ModelHit:
    """One model's finding on one column. Counts, bands and buckets only; no cell text."""

    source: Literal["classifier", "ner"]
    detector_id: str
    model: ModelRef
    band: Band | None
    rate_bucket: RateBucket | None


@dataclass
class _Counts:
    classifier_hits: int = 0
    classifier_low: int = 0
    ner_hits: int = 0
    ner_cells: int = 0
    unmapped_labels: int = 0


@dataclass(frozen=True)
class ModelPass:
    """The strictly loaded detectors and the NER model name, applied to one table at a time."""

    detectors: DetectorSet
    ner_model: str

    def run(
        self, frame: pd.DataFrame, table: str, position: int
    ) -> dict[str, tuple[ModelHit, ...]]:
        counts = _Counts()
        found: dict[str, list[ModelHit]] = {}
        pack, classifier = self.detectors.classifier_pack, self.detectors.classifier
        if pack is not None and classifier is not None:
            for column, hit in _classifier_hits(pack, classifier, frame, counts):
                found.setdefault(column, []).append(hit)
        if self.detectors.ner is not None:
            for column, hit in self._ner(self.detectors.ner, frame, counts):
                found.setdefault(column, []).append(hit)
        log_detector_models(
            "pre_scan",
            table,
            position,
            {
                "classifier_hits": counts.classifier_hits,
                "classifier_low": counts.classifier_low,
                "ner_hits": counts.ner_hits,
                "ner_cells": counts.ner_cells,
                "unmapped_labels": counts.unmapped_labels,
            },
        )
        return {column: tuple(hits) for column, hits in found.items()}

    def _ner(
        self, ref: ModelRef, frame: pd.DataFrame, counts: _Counts
    ) -> list[tuple[str, ModelHit]]:
        out: list[tuple[str, ModelHit]] = []
        for column in frame.columns:
            series = frame[column]
            if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
                continue
            rates = ner_rates(series, model=self.ner_model)
            counts.ner_cells += max((r.scanned_cells for r in rates.values()), default=0)
            for detector_id, rate in sorted(rates.items()):
                if rate.hit:
                    hit = ModelHit("ner", detector_id, ref, None, cast(RateBucket, rate.bucket))
                    out.append((str(column), hit))
                    counts.ner_hits += 1
        return out


def _classifier_hits(
    pack: dict[str, Any], ref: ModelRef, frame: pd.DataFrame, counts: _Counts
) -> list[tuple[str, ModelHit]]:
    out: list[tuple[str, ModelHit]] = []
    for column, result in classify_frame(pack, frame, subsample=True).items():
        band = result["band"]
        if band == "low":
            counts.classifier_low += 1
            continue
        if result["label"] is None:
            continue
        detector_id = classifier_detector_id(str(result["label"]))
        if detector_id is None:
            counts.unmapped_labels += 1
            continue
        out.append((column, ModelHit("classifier", detector_id, ref, cast(Band, band), None)))
        counts.classifier_hits += 1
    return out
