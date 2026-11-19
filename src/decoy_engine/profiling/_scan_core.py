"""The persisted core of `scan-set/v1`: the one definition of the value-free scan record.

The write models refuse unknown fields; `ScanSetCoreRead` is derived from `ScanSetCore` with
unknown fields ignored, so an older reader accepts a newer record (compatibility contract
section 3.1). Nothing here can carry a cell value: the models hold counts, rates, type labels,
detector ids and column names. `scan_set.py` builds these models from a scan.
"""

from __future__ import annotations

import types
from typing import Annotated, Any, Final, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, model_validator

from decoy_engine import reasons
from decoy_engine.detection._ner_rate import RateBucket
from decoy_engine.profiling._model_pass import Band
from decoy_engine.profiling._scan_integrity import Status

Strategy = Literal["head", "random", "full"]

# ---------------------------------------------------------------------------
# The persisted core
# ---------------------------------------------------------------------------


class _Core(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WarningRefCore(_Core):
    namespace: str
    code: str

    @model_validator(mode="after")
    def _known(self) -> WarningRefCore:
        # Write side only: the read variant drops validators, so an older reader still
        # accepts a code a newer registry added.
        reasons.require_known(reasons.ReasonRef(self.namespace, self.code))
        return self


class ModelRefCore(_Core):
    id: str
    version: str


class ModelHitCore(_Core):
    source: Literal["classifier", "ner"]
    detector_id: str
    model: ModelRefCore
    band: Band | None
    rate_bucket: RateBucket | None


class RegexRunCore(_Core):
    source: Literal["regex"]
    model: None


class ModelRunCore(_Core):
    source: Literal["classifier", "ner"]
    model: ModelRefCore


# Tagged on `source`, so a regex run cannot carry a model and a model run cannot lack one.
_DetectorRunCore = Annotated[Union[RegexRunCore, ModelRunCore], Field(discriminator="source")]  # noqa: UP007
_RUN_CORE: TypeAdapter[Any] = TypeAdapter(_DetectorRunCore)


class FieldCore(_Core):
    name: str
    dtype: str
    null_count: int
    null_rate: float | None
    distinct_count: int
    pii_score: float | None
    pii_candidate: bool
    detector_hits: list[str]
    leading_zero_count: int | None
    # Defaults keep a record written before M3a readable and valid.
    model_hits: list[ModelHitCore] = Field(default_factory=list)


class TableCore(_Core):
    name: str
    descriptor: dict[str, Any]
    row_count: int
    row_count_exact: bool
    sample_strategy: Strategy
    sample_row_cap: int | None
    fields: list[FieldCore]
    key_candidates: list[str]
    warnings: list[WarningRefCore]
    reid_risk_score: float | None
    quasi_identifier_groups: list[list[str]]


class ChildFactsCore(_Core):
    table: str
    columns: list[str]
    rows: int | None
    null_key_rows: int | None
    orphan_rows: int | None
    orphan_distinct_keys: int | None


class RelationshipFactsCore(_Core):
    parent: str
    parent_columns: list[str]
    children: list[ChildFactsCore]
    status: Status
    parent_rows: int | None
    parent_null_key_rows: int | None
    parent_duplicate_excess: int | None
    exact: bool
    bounded: bool
    warnings: list[WarningRefCore]


class ScanSetCore(_Core):
    scan_schema: Literal["scan-set/v1"]
    engine_version: str
    scanned_at: str
    tables: list[TableCore]
    relationships: list[RelationshipFactsCore]
    detectors: list[_DetectorRunCore] = Field(default_factory=list)


def _relaxed(model: type[BaseModel]) -> type[BaseModel]:
    """`model` with unknown fields ignored, nested models included."""

    def swap(annotation: Any) -> Any:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return _relaxed(annotation)
        origin = get_origin(annotation)
        if origin is None:
            return annotation
        args = tuple(swap(a) for a in get_args(annotation))
        if origin in (Union, types.UnionType):
            return Union[args]  # noqa: UP007 - built from a runtime tuple
        return origin[args]

    fields: dict[str, Any] = {
        name: (swap(info.annotation), info) for name, info in model.model_fields.items()
    }
    config = ConfigDict(extra="ignore", frozen=True, strict=True)
    return create_model(f"{model.__name__}Read", __config__=config, **fields)


ScanSetCoreRead: Final = _relaxed(ScanSetCore)
