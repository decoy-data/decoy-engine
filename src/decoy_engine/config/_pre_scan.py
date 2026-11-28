"""`pre_scan`: opt-in detector choice for the Pre-scan phase.

`detectors` picks which sources look for PII when a source is scanned: `regex` (always on in
V1), the lgbm `classifier` and spaCy `ner`. Writing the block turns the run-start pre-scan on
(`pre_scan_requested`), so a written block stays in the dump even when every field is the default.
`on_findings` is `warn` (report and continue) or `fail` (stop before the source load). Under `warn`
the block is left out of the plan hash (`plan/_compile._hash_config`); under `fail` its effective
detectors, model and policy are hashed because they decide whether a run blocks.
The checks here are shape only; whether a model is installed is a preflight
(`profiling/model_pack/_detectors.load_detectors`), never a config rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError

from decoy_engine import reasons
from decoy_engine.detection.ner import DEFAULT_NER_MODEL, NerModelNameError, is_default_ner_model
from decoy_engine.detection.types import (
    DETECTOR_ORDER,
    DetectorSource,
    validate_ner_model_name,
)


def canonical_detectors(value: tuple[DetectorSource, ...]) -> tuple[DetectorSource, ...]:
    """No duplicates, `regex` always present, in the canonical order (dumps and hashes stay stable).

    Regex always runs, so a list without it is completed rather than refused. This is the one
    place that adds it."""
    if len(set(value)) != len(value):
        raise PydanticCustomError(
            str(reasons.config.DETECTORS_INVALID), "detectors must not repeat a source."
        )
    chosen = {*value, "regex"}
    return tuple(source for source in DETECTOR_ORDER if source in chosen)


def checked_ner_model(value: Any) -> str:
    """The model name, or a custom error carrying `config.ner_model_invalid` and no part of it."""
    try:
        return validate_ner_model_name(value)
    except NerModelNameError as exc:
        raise PydanticCustomError(
            str(exc.code), "ner_model must be a plain package name."
        ) from None


def inactive(field: str, needs: str) -> PydanticCustomError:
    """A chosen setting that would be silently ignored; names the field, never a value."""
    return PydanticCustomError(str(reasons.config.POST_SCAN_INACTIVE), f"{field} needs {needs}.")


def pre_scan_requested(config: Mapping[str, Any]) -> bool:
    """True when a validated config dict wrote a `pre_scan` block, even an empty one.

    The one reader of the on/off switch. Presence is the switch, so `{}` counts."""
    return isinstance(config.get("pre_scan"), Mapping)


def hash_input_of(scan: PreScanConfig | None) -> dict[str, Any] | None:
    """What the plan hash takes from a parsed `pre_scan` block, or `None` when it takes nothing.

    Only `on_findings: fail` counts: under `fail` the detectors and the model decide whether a run
    blocks. Values come from `PreScanConfig` itself, so a changed default moves the hash input
    with it. `ner_model` is included only when `ner` runs. The block is parsed by
    `_parse.pre_scan_hash_input`, the one validation route."""
    if scan is None:
        return None
    if scan.on_findings != "fail":
        return None
    hashed: dict[str, Any] = {"on_findings": "fail", "detectors": list(scan.detectors)}
    if "ner" in scan.detectors:
        hashed["ner_model"] = scan.ner_model
    return hashed


class PreScanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    detectors: tuple[DetectorSource, ...] = ("regex",)
    ner_model: str = DEFAULT_NER_MODEL
    on_findings: Literal["warn", "fail"] = "warn"

    @field_validator("detectors")
    @classmethod
    def _detectors(cls, value: tuple[DetectorSource, ...]) -> tuple[DetectorSource, ...]:
        return canonical_detectors(value)

    @field_validator("ner_model", mode="before")
    @classmethod
    def _ner_model(cls, value: Any) -> str:
        return checked_ner_model(value)

    @model_validator(mode="after")
    def _ner_model_needs_ner(self) -> PreScanConfig:
        if "ner_model" in self.model_fields_set and "ner" not in self.detectors:
            raise PydanticCustomError(
                str(reasons.config.PRE_SCAN_NER_INACTIVE),
                "pre_scan.ner_model needs ner in pre_scan.detectors.",
            )
        return self

    @model_serializer(mode="wrap")
    def _omit_default_model(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # An explicit default model would re-validate as "a set ner_model" and trip the rule above.
        data: dict[str, Any] = handler(self)
        if is_default_ner_model(data.get("ner_model", "")):
            data.pop("ner_model")
        if data.get("on_findings") == "warn":
            data.pop("on_findings", None)
        return data

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        from decoy_engine.config._declared_casting import recover_serialization_schema

        return recover_serialization_schema(core_schema, handler)
