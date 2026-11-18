"""`scan_baseline`: the optional pointer from a pipeline to the scan record it was built from.

`decoy scan --emit-config` writes it; `decoy scan --compare` reads it, and `decoy run` reads it
only when `on_drift` is set (or evidence asks for the baseline's hash). The record is a
`scan-set/v1` object in the scan library and its path already encodes the record id, so the
block has no id member. The tag is a closed literal: a baseline of another schema is refused.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError

from decoy_engine import reasons

# The tag equals `profiling.scan_set.SCAN_SET_SCHEMA` (a test pins that); config does not import
# profiling.
ScanBaselineSchema = Literal["scan-set/v1"]
OnDrift = Literal["warn", "fail"]


class ScanBaselineConfig(BaseModel):
    """`scan_baseline: {path, schema, on_drift, sha256}`. YAML says `schema`; the field is `schema_tag` because
    `schema` would shadow a pydantic model attribute, and the dump writes `schema` back."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    path: str
    schema_tag: ScanBaselineSchema = Field(alias="schema")
    # Opt-in drift check at run start: `warn` reports, `fail` stops the run. Absent means no check.
    on_drift: OnDrift | None = None
    # The SHA-256 of the baseline file's bytes. Setting it binds the baseline: a run whose file
    # hashes differently stops. Required under `on_drift: fail`; a quoted string, so an
    # all-digit digest is not read as an integer.
    sha256: str | None = Field(default=None, strict=True, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fail_needs_a_digest(self) -> ScanBaselineConfig:
        # `on_drift: fail` without a pinned baseline would let a rescan into the same path
        # approve the drift it should stop.
        if self.on_drift == "fail" and self.sha256 is None:
            raise PydanticCustomError(
                str(reasons.config.SCAN_BASELINE_UNBOUND),
                "scan_baseline.on_drift: fail needs scan_baseline.sha256.",
            )
        return self

    @model_serializer(mode="wrap")
    def _dump_schema_key(self, handler: Any) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        # by_alias=True already names the key `schema`; a plain dump names it `schema_tag`.
        if "schema_tag" in data:
            data["schema"] = data.pop("schema_tag")
        # An unset check leaves the old dump (and so the plan hash and YAML round trip) as it was.
        if data.get("on_drift") is None:
            data.pop("on_drift", None)
        if data.get("sha256") is None:
            data.pop("sha256", None)
        return data

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        from decoy_engine.config._declared_casting import recover_serialization_schema

        return recover_serialization_schema(core_schema, handler)
