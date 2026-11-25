"""Pool Manager: pool-backed sampling primitives for V2 strategies.

Public API:

    from decoy_engine.generation.pool import (
        ValuePool,
        PoolBuilder,
        PoolCache,
        PoolSampler,
        PoolAdapter,
        CardinalityMode,
        GenerationError,
        PoolCapacityError,
        QualityWarning,
        get_default_pool_cache,
    )

Public names are all in `__all__`. PoolAdapter is the first concrete
`BackendAdapter` (S4 Protocol) that declares
`supports_deterministic: True` for the poolable subset of the catalog;
it wraps another adapter (typically FakerAdapter) and routes
deterministic calls through a pool indexed by `derive_index`.

Source patterns:
- Bulk-fill: SDV `SingleTablePreset` build-and-sample; Faker batch usage.
- Bytes-bounded LRU: pandas `io.parquet.row_group_size`, Polars
  `set_global_string_cache` budget pattern (per best-practices §6.2).
- NEP-19 (`numpy.random.default_rng`): the seed-stability contract.
- Adapter wrapping: V1 strategy decorators; SDV's `SingleTablePreset`
  wrapping `GaussianCopulaSynthesizer`.

References:
- Spec: docs/v2/sprints/engine-v2/sprint-05-pool-manager.md
- Cross-sprint contracts §2.4 (cardinality mode), §2.5 (pool identity),
  §2.6 (sampler), §4 row 7 (pool_capacity_pre_flight), R3 (canonicalize
  envelope), R6 (R6 reshape).
"""

from __future__ import annotations

from decoy_engine.generation.pool._builder import PoolBuilder
from decoy_engine.generation.pool._cache import (
    CacheStats,
    PoolCache,
    get_default_pool_cache,
)
from decoy_engine.generation.pool._capacity import unique_capacity_ok
from decoy_engine.generation.pool._cardinality import CardinalityMode
from decoy_engine.generation.pool._computed_draw import (
    COMPUTED_NAMESPACE_MARKER,
    INT64_MAX,
    INT64_MIN,
    ComputedDrawSpec,
    DrawRefusal,
    choice_from_index,
    computed_draw_spec,
    computed_selection_namespace,
    draw_kwargs,
    int_from_index,
    parse_computed_draw,
    uuid_from_bits,
    uuid_from_hex,
)
from decoy_engine.generation.pool._errors import (
    GenerationError,
    PoolCapacityError,
    raise_uniqueness_impossible,
)
from decoy_engine.generation.pool._events import (
    DetailValue,
    QualityWarning,
    emit_generation_warning,
)
from decoy_engine.generation.pool._identity import effective_pool_size
from decoy_engine.generation.pool._pool_adapter import PoolAdapter
from decoy_engine.generation.pool._resident import (
    STR_OBJECT_OVERHEAD_BYTES,
    PoolResidentParts,
    faker_pool_resident_bytes,
    faker_pool_resident_parts,
    provider_init_bound,
    provider_init_bytes,
    run_faker_footprint,
)
from decoy_engine.generation.pool._runtime_pool_size import DEFAULT_POOL_SIZE
from decoy_engine.generation.pool._sampler import (
    PoolSampler,
    derive_pool_indices,
    derive_validated_indices,
)
from decoy_engine.generation.pool._validate import check_pool_capacity_pre_flight
from decoy_engine.generation.pool._value_pool import ValuePool, pool_take

__all__ = [
    "COMPUTED_NAMESPACE_MARKER",
    "DEFAULT_POOL_SIZE",
    "INT64_MAX",
    "INT64_MIN",
    "STR_OBJECT_OVERHEAD_BYTES",
    "CacheStats",
    "CardinalityMode",
    "ComputedDrawSpec",
    "DetailValue",
    "DrawRefusal",
    "GenerationError",
    "PoolAdapter",
    "PoolBuilder",
    "PoolCache",
    "PoolCapacityError",
    "PoolResidentParts",
    "PoolSampler",
    "QualityWarning",
    "ValuePool",
    "check_pool_capacity_pre_flight",
    "choice_from_index",
    "computed_draw_spec",
    "computed_selection_namespace",
    "derive_pool_indices",
    "derive_validated_indices",
    "draw_kwargs",
    "effective_pool_size",
    "emit_generation_warning",
    "faker_pool_resident_bytes",
    "faker_pool_resident_parts",
    "get_default_pool_cache",
    "int_from_index",
    "parse_computed_draw",
    "pool_take",
    "provider_init_bound",
    "provider_init_bytes",
    "raise_uniqueness_impossible",
    "run_faker_footprint",
    "unique_capacity_ok",
    "uuid_from_bits",
    "uuid_from_hex",
]
