"""Native-route admission decided from real types, not profile labels.

The static admission (`_static_route_decision`) reads the profile's coarse dtype
labels. Five things it cannot see decide whether the compiled path matches the
oracle, so `plan_native_route` checks them here once it has the first chunk:

- a hash column's real Arrow type (a dictionary-encoded string, a date32 or a
  decimal128 profiles as `object` or a numeric label and passes the static
  check, but the compiled hash kernel does not take it while the oracle hashes
  it);
- a categorical column's real source type (the compiled index kernel's admitted
  input is `string`; a numeric or dictionary source reroutes to the oracle);
- a bucket_perturb column's real source type (the native operator takes exactly
  `string`; an Arrow `large_string` profiles as `object`, which maps back to
  `string`, so only the real schema can tell the two apart);
- a date_shift column's real source type (the native operator takes exactly `string`,
  and a non-string source keeps running on the oracle, which is what it ran on before
  date_shift left the chunked veto set);
- a text_redact column's real source type (the native operator takes exactly `string`; the
  oracle stringifies any other cell, which the string-only kernel contract does not reproduce
  for a decimal, date or dictionary source, so a non-string source keeps running on the oracle);
- a group_key column's real SIBLING type (the native operator takes exactly
  `{string, int64, bool}`, the one domain where the oracle's raw-value cache cannot collide;
  a wider oracle-safe sibling such as int32, uint64, large_string, dictionary, date or
  timestamp keeps running on the oracle, as it did before group_key left the chunked veto
  set), and that the sibling is in the first chunk at all;
- a faker column's provider name (the pool is built as strings, which is right
  only for the providers C1 admits; any other provider, for example a
  date-of-birth provider, produces values the string pool cannot hold). The
  provider's actual output under the caller's registry is checked separately,
  on the resolved pool, by `_chunked_pools.resolve_admitted_pools`.

A rejection reroutes the whole table to the oracle with a coded reason, so the
two routes agree on the input instead of the native one failing after the first
chunk was accepted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

import pyarrow as pa

from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution.native._chunked_group_key_gate import group_by_columns
from decoy_engine.execution.native._operator_config_rejections import (
    group_key_sibling_type_admitted,
)
from decoy_engine.execution.native._provider_class import (
    FakerVariant,
    computed_output_decline,
    resolve_faker_variant,
)
from decoy_engine.execution.native._requirements import hash_config_rejection
from decoy_engine.execution.native._route_decline_codes import CodedDecline, RouteDeclineCode, coded
from decoy_engine.providers_v2 import ProviderRegistry, custom_provider_names, get_default_registry

# The frozen C1 recipe's faker providers, from the operator registry (edit the registry). An
# unset allowlist admits no provider, so a registry edit cannot widen admission by accident.
C1_PROVIDER_ALLOWLIST: Final[frozenset[str]] = OPERATORS["faker"].provider_allowlist or frozenset()

# The strategies whose native source domain is exactly `string` (checked by
# `string_source_type_rejection`). Route-specific, so not an operator-registry field: the
# chunked route keeps its own source-type gates with coded reasons (the unified domain for
# these four happens to be `{string}` too, but the two routes are gated separately).
_STRING_SOURCE_STRATEGIES: Final = frozenset(
    {"categorical", "bucket_perturb", "date_shift", "text_redact", "fpe", "text_mask"}
)


def _fpe_checksum_decline(config: dict[str, Any], table: str, column: str) -> str | None:
    """The coded reason an fpe column declines to the oracle for a configured `checksum` mode,
    or None. Checksum modes stay on the Python path (C6a plan §3g): the compiled FF1 kernel has
    no checksum path, so a column with `checksum` set runs the whole table on the oracle."""
    for table_cfg in config.get("tables") or ():
        if not isinstance(table_cfg, dict) or table_cfg.get("name") != table:
            continue
        for col in table_cfg.get("columns") or ():
            if not isinstance(col, dict) or col.get("name") != column:
                continue
            pc = col.get("provider_config")
            if isinstance(pc, dict) and pc.get("checksum"):
                return f"fpe_checksum_not_native:{column}"
    return None


def _column_values(config: dict[str, Any], table: str, key: str) -> dict[str, Any]:
    """`key` of every column entry of `table` in the raw config, by column name."""
    for table_cfg in config.get("tables") or ():
        if isinstance(table_cfg, dict) and table_cfg.get("name") == table:
            return {
                c["name"]: c.get(key)
                for c in table_cfg.get("columns") or ()
                if isinstance(c, dict) and "name" in c
            }
    return {}


def _binding_matches_stock(
    provider: object,
    provider_config: Mapping[str, Any] | None,
    variant: FakerVariant,
    registry: ProviderRegistry | None,
) -> bool:
    """True when the live binding draws as the stock one does: the same variant, and for a pool
    the same adapter class and no registered callback, since the C1 allowlist's string-output guarantee belongs to the stock
    backends. A rebinding to an adapter that returns other types fails this check."""
    if variant != resolve_faker_variant(provider, provider_config):
        return False
    if variant.kind != "pool":
        return True
    # A callback registered under the stock name replaces the string-returning method inside the
    # stock adapter, so the adapter class alone does not prove the output type.
    if isinstance(provider, str) and provider in custom_provider_names():
        return False
    if registry is None:
        return True
    stock = get_default_registry()
    if not (isinstance(provider, str) and registry.has(provider) and stock.has(provider)):
        return True
    return type(registry.get_adapter(provider)) is type(stock.get_adapter(provider))


def faker_provider_decline(
    column: str,
    provider: object,
    provider_config: Mapping[str, Any] | None,
    *,
    runs_computed: bool,
    registry: ProviderRegistry | None = None,
    stock_only: bool = False,
) -> tuple[str, RouteDeclineCode] | None:
    """The reason and decline code a route gives a faker column's provider, or None to admit it.

    The live binding decides the variant (`resolve_faker_variant`). A pool provider must be on
    the C1 allowlist. A computed draw has no pool: a route that `runs_computed` admits it when
    its output is exact `string`, and every route declines any other output type (E11 and E13).
    A route that does not run computed draws yet declines an exact-string one, and a computed
    binding with no descriptor, as not native. `stock_only` is for a route whose schema is read
    from the stock binding (out-of-core): a rebound provider that resolves to another variant than
    the stock registry's is declined, and so is a pool binding on another adapter class than the stock
    one, because only the stock pool bindings guarantee string output. The schema and the draw
    cannot then disagree."""
    variant = resolve_faker_variant(provider, provider_config, registry)
    if stock_only and not _binding_matches_stock(provider, provider_config, variant, registry):
        return (
            f"faker_provider_not_native:{column}:{provider}",
            RouteDeclineCode.FAKER_PROVIDER_NOT_NATIVE,
        )
    if variant.kind == "computed":
        reason = computed_output_decline(column, provider, provider_config, registry)
        if reason is not None:
            return reason, RouteDeclineCode.FAKER_COMPUTED_OUTPUT_TYPE_UNSUPPORTED
        if runs_computed:
            return None
    elif variant.kind == "pool" and provider in C1_PROVIDER_ALLOWLIST:
        return None
    return (
        f"faker_provider_not_native:{column}:{provider}",
        RouteDeclineCode.FAKER_PROVIDER_NOT_NATIVE,
    )


def string_source_type_rejection(strategy: str, column: str, schema: pa.Schema) -> str | None:
    """The coded reason a `strategy` column's real source type is not the one its native
    operator takes, or None. categorical, bucket_perturb, date_shift and text_redact all take
    exactly `string`, the domain the full-frame route proves (`_unified_slice_admission`); any
    other type, including `large_string` (which passes the upstream chunk-safety gate for the
    oracle route), declines to the oracle before masking instead of failing inside the
    kernel."""
    typ = schema.field(column).type
    return None if typ == pa.string() else f"{strategy}_source_type_not_string:{column}:{typ}"


# Thin per-strategy names kept only because existing tests import them (plan R1 3f); the
# production caller uses `string_source_type_rejection` directly.
def bucket_perturb_source_type_rejection(column: str, schema: pa.Schema) -> str | None:
    return string_source_type_rejection("bucket_perturb", column, schema)


def date_shift_source_type_rejection(column: str, schema: pa.Schema) -> str | None:
    return string_source_type_rejection("date_shift", column, schema)


def group_key_sibling_type_rejection(column: str, group_by: str, schema: pa.Schema) -> str | None:
    """The coded reason a group_key column's real SIBLING type is not one the native operator
    takes, or None. The domain is `{string, int64, bool}`, the full-frame route's domain and
    the collision-free one; any other type (a null-typed first chunk included) declines to the
    oracle. A sibling the first chunk does not carry declines cleanly instead of raising."""
    if group_by not in schema.names:
        return f"group_key_sibling_missing_not_native_chunked_route:{column}:{group_by}"
    typ = schema.field(group_by).type
    if group_key_sibling_type_admitted(typ):
        return None
    return f"group_key_sibling_type_not_native:{column}:{group_by}:{typ}"


def real_type_decline(
    config: dict[str, Any],
    node_routes: Iterable[Any],
    first_schema: pa.Schema,
    *,
    table: str,
    profile: Any,
    registry: ProviderRegistry | None = None,
) -> CodedDecline | None:
    """The first real-type decline as its legacy reason plus a structured record, or None.
    The column is the node under test, so attribution never reparses the reason string."""
    node_routes = tuple(node_routes)
    # Only the hash columns are read from the resident table (`hash_config_rejection`
    # resolves one column's type). `Schema.empty_table` raises for a union or a
    # run-end-encoded string_view field, so building it over the whole schema would turn
    # a carried passthrough column of that type into a crash at admission.
    resident = {
        table: pa.schema(
            [first_schema.field(n.column) for n in node_routes if n.strategy == "hash"]
        ).empty_table()
    }
    providers = _column_values(config, table, "provider")
    provider_configs = _column_values(config, table, "provider_config")
    group_by_of = group_by_columns(config, table)
    for node in node_routes:
        column = node.column
        if node.strategy == "fpe":
            # A checksum mode declines before the string-source check below runs, so a checksum
            # column over a non-string source still reports the checksum reason (both decline).
            checksum_reason = _fpe_checksum_decline(config, table, column)
            if checksum_reason is not None:
                return coded(
                    checksum_reason, RouteDeclineCode.FPE_CHECKSUM_NOT_NATIVE, table, column
                )
        if node.strategy == "hash":
            reason = hash_config_rejection(column, table, profile, resident_sources=resident)
            if reason is not None:
                return coded(reason, RouteDeclineCode.HASH_CONFIG_REJECTED, table, column)
        elif node.strategy == "faker" and (
            provider_decline := faker_provider_decline(
                column,
                providers.get(column),
                provider_configs.get(column),
                runs_computed=False,
                registry=registry,
            )
        ):
            reason, code = provider_decline
            return coded(reason, code, table, column)
        elif node.strategy in _STRING_SOURCE_STRATEGIES:
            reason = string_source_type_rejection(node.strategy, column, first_schema)
            if reason is not None:
                return coded(reason, RouteDeclineCode.SOURCE_TYPE_NOT_STRING, table, column)
        elif node.strategy == "group_key" and column in group_by_of:
            reason = group_key_sibling_type_rejection(column, group_by_of[column], first_schema)
            if reason is not None:
                code = (
                    RouteDeclineCode.GROUP_KEY_SIBLING_MISSING
                    if group_by_of[column] not in first_schema.names
                    else RouteDeclineCode.GROUP_KEY_SIBLING_TYPE_NOT_NATIVE
                )
                return coded(reason, code, table, column)
    return None


def real_type_rejection(
    config: dict[str, Any],
    node_routes: Iterable[Any],
    first_schema: pa.Schema,
    *,
    table: str,
    profile: Any,
) -> str | None:
    """The coded reason an admitted table must run on the oracle, or None."""
    decline = real_type_decline(config, node_routes, first_schema, table=table, profile=profile)
    return None if decline is None else decline.reason
