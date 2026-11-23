"""Draw-site entries for the computed Faker draws (uuid, bounded integer, element choice).

A computed draw has no pool: the value is a pure function of its key. Masking draws it in
`computed_mask_draw` (`execution/_strategies/_faker_positional.py`), either keyed on the source
value (`mask.faker_computed_value`, under the mask key) or on the row's full-table number
(`mask.faker_computed_position`, under the job seed). Appended after the first catalogue cut, as
`_determinism_protocol.py` requires.
"""

from __future__ import annotations

from decoy_engine.execution.native._draw_site_types import _V6, DrawSite

COMPUTED_DRAW_SITES: tuple[DrawSite, ...] = (
    DrawSite(
        draw_site_id="mask.faker_computed_value",
        family="source_keyed_hmac",
        call_site="execution/_strategies/_faker_positional.py::computed_mask_draw#1",
        entropy_root="mask_key",
        seed_derivation=(
            "derive_index(mask_key, selection_namespace + '/computed:' + provider, "
            "canonical(source), pool_size=count)  # int, choice; uuid: "
            "derive(mask_key, same namespace, canonical(source)).hex()[:32] as 16 bytes"
        ),
        api_operation="determinism.derive_index -> index in [0, count); uuid: derive -> 16 bytes",
        call_shape="int: lo + index * step | choice: elements[index] | uuid: RFC 9562 v4 layout",
        consumes_variable_draws=False,
        identity="source_value",
        null_draw_behavior="null source rows re-emit null and consume no derivation",
        partitionable=True,
        config_fingerprint_source="namespace_registry(namespace)+provider+min/max/step or elements",
        provider_version=_V6,
        notes=(
            "Deterministic mode of the masking faker strategy on uuid, random_int_range and "
            "random_choice. The namespace suffix keeps the draw apart from any pool selection "
            "in the same column namespace."
        ),
    ),
    DrawSite(
        draw_site_id="mask.faker_computed_position",
        family="source_keyed_hmac",
        call_site="execution/_strategies/_faker_positional.py::computed_mask_draw#2",
        entropy_root="job_seed",
        seed_derivation=(
            "derive_index(job_seed, selection_namespace + '/computed:' + provider, "
            "encode_int(row_offset + i), pool_size=count)  # uuid: derive(...).hex()[:32]"
        ),
        api_operation="determinism.derive_index -> index in [0, count); uuid: derive -> 16 bytes",
        call_shape="int: lo + index * step | choice: elements[index] | uuid: RFC 9562 v4 layout",
        consumes_variable_draws=False,
        identity="global_row_number",
        null_draw_behavior="null source rows re-emit null; the null still consumes its row number",
        partitionable=True,
        config_fingerprint_source="plan.namespace or the table/column default+provider+args",
        provider_version=_V6,
        notes=(
            "Non-deterministic reuse mode. Keyed on job_seed, not mask_key, because it generates "
            "values and does not re-identify a source value (same stance as "
            "mask.faker_nondeterministic)."
        ),
    ),
)

__all__ = ["COMPUTED_DRAW_SITES"]
