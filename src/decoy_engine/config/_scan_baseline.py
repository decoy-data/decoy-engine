"""`scan_baseline`: the optional pointer from a pipeline to the scan record it was built from.

`decoy scan --emit-config` writes it; `decoy scan --compare` reads it, and `decoy run` reads it
only when `on_drift` is set (or evidence asks for the baseline's hash). The record is a
`scan-set/v1` object in the scan library and its path already encodes the record id, so the
block has no id member. The tag is a closed literal: a baseline of another schema is refused.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

# The tag equals `profiling.scan_set.SCAN_SET_SCHEMA` (a test pins that); config does not import
# profiling.
ScanBaselineSchema = Literal["scan-set/v1"]
OnDrift = Literal["warn", "fail"]


class ScanBaselineConfig(BaseModel):
    """`scan_baseline: {path, schema, on_drift}`. YAML says `schema`; the field is `schema_tag` because
    `schema` would shadow a pydantic model attribute, and the dump writes `schema` back."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    path: str
    schema_tag: ScanBaselineSchema = Field(alias="schema")
    # Opt-in drift check at run start: `warn` reports, `fail` stops the run. Absent means no check.
    on_drift: OnDrift | None = None

    @model_serializer(mode="wrap")
    def _dump_schema_key(self, handler: Any) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        # by_alias=True already names the key `schema`; a plain dump names it `schema_tag`.
        if "schema_tag" in data:
            data["schema"] = data.pop("schema_tag")
        # An unset check leaves the old dump (and so the plan hash and YAML round trip) as it was.
        if data.get("on_drift") is None:
            data.pop("on_drift", None)
        return data

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        from decoy_engine.config._declared_casting import recover_serialization_schema

        return recover_serialization_schema(core_schema, handler)
