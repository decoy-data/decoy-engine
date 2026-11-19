"""The persisted core of `scan-set/v1`: the one definition of the value-free scan record.

The write models refuse unknown fields; `ScanSetCoreRead` is derived from `ScanSetCore` with
unknown fields ignored, so an older reader accepts a newer record (compatibility contract
section 3.1). Nothing here can carry a cell value: the models hold counts, rates, type labels,
detector ids and column names. `scan_set.py` builds these models from a scan.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic_core import PydanticCustomError

from decoy_engine import reasons
from decoy_engine._value_free import (
    ReadUnknownAs,
    SharedRules,
    StrictReadBase,
    WriteRules,
    derive_read,
)
from decoy_engine.detection._ner_rate import RateBucket
from decoy_engine.profiling._basis import Basis
from decoy_engine.profiling._model_pass import Band
from decoy_engine.profiling._scan_integrity import Status

Strategy = Literal["head", "random", "full"]

# ---------------------------------------------------------------------------
# The persisted core
# ---------------------------------------------------------------------------


class _Core(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _WarningRules(WriteRules):
    @model_validator(mode="after")
    def _known(self) -> _WarningRules:
        # Write side only: the read model does not inherit write rules, so an older reader still
        # accepts a code a newer registry added.
        reasons.require_known(reasons.ReasonRef(self.namespace, self.code))  # type: ignore[attr-defined]
        return self


class WarningRefCore(_Core, _WarningRules):
    namespace: str
    code: str


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


def _refuse(text: str) -> PydanticCustomError:
    # Fixed text: a PydanticCustomError template is never built from the payload.
    return PydanticCustomError("scan_core_table", text)


class _TableCoreRules(SharedRules):
    """The relations between a table's row counts and its basis, on write and on read."""

    @model_validator(mode="before")
    @classmethod
    def _legacy_null_count(cls, data: Any) -> Any:
        # A record written before the basis labels has neither member. A missing `scanned_rows`
        # is admitted only for that legacy shape, checked on the raw basis: an unknown basis
        # would otherwise fall back to `sample` on read and hide a missing count.
        if isinstance(data, dict) and data.get("scanned_rows") is None:
            if "basis" in data and data["basis"] != "sample":
                raise _refuse("scanned_rows is required unless the basis is sample")
        return data

    @model_validator(mode="after")
    def _row_relations(self) -> _TableCoreRules:
        t: Any = self
        if t.row_count < 0:
            raise _refuse("row_count is negative")
        scanned = t.scanned_rows
        if scanned is None:
            if t.basis != "sample":
                raise _refuse("a whole basis needs scanned_rows")
            return self
        if not 0 <= scanned <= t.row_count:
            raise _refuse("scanned_rows is outside 0..row_count")
        if t.basis == "whole" and not (t.row_count_exact and scanned == t.row_count):
            raise _refuse("a whole basis needs an exact row_count equal to scanned_rows")
        return self


class TableCore(_Core, _TableCoreRules):
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
    # Defaults keep a record written before the basis labels readable, as a sample.
    basis: Annotated[Basis, ReadUnknownAs("sample")] = "sample"
    scanned_rows: int | None = None


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


ScanSetCoreRead: Final = derive_read(ScanSetCore, base=StrictReadBase, token=None, module=__name__)
