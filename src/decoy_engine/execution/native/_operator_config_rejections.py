"""Per-operator config/type admission gates for the native planning boundary.

The categorical / bucket_perturb / group_key / date_shift
``*_config_rejection`` resolvers plus the small constants and helpers they own.
Each returns the coded reason a column cannot run on its native operator, or
None when it can. Both native admission boundaries (the compiler's
``_config_gate_rejection`` and the config-only ``native_route_eligibility``
query) call these SAME functions so they can never reach a different verdict for
the same column.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import pyarrow as pa

from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution.native._categorical_prepared import prepare_categorical
from decoy_engine.execution.native._requirements import resolve_input_arrow_type
from decoy_engine.transforms.fpe import resolve_fpe_charset

# Mirrors the oracle's `transforms.bucket_perturb._VALID_BUCKETS`; kept local to
# avoid importing the transforms module into the planning boundary.
_VALID_BUCKET_PERTURB_BUCKETS = frozenset({"week", "month", "quarter"})


# pandas `format=` values that are NOT strptime directives: "mixed" infers a
# format per element and "ISO8601" accepts any ISO shape. Neither is an explicit
# format in the v1 sense, so both decline.
_PANDAS_SPECIAL_DATE_FORMATS = frozenset({"mixed", "ISO8601"})


def is_deterministic_categorical(resolved_config: Any) -> bool:
    """Whether a categorical column's resolved config selects the deterministic
    (source-keyed, row-local) path -- the SINGLE source of truth the native
    determinism gate consults at the config-only boundary.

    Reproduces the seed envelope's own determinism computation for a column
    (`plan/_seed_envelope.py`): the first-class `deterministic: bool` field,
    OR the `allow_collisions: true` alias that forces deterministic reuse. So
    `ColumnSeed.deterministic == is_deterministic_categorical(col_config)` by
    construction (pinned by a test), letting the config-only native-route query
    decide determinism without a compiled `ColumnSeed`.
    """
    get = resolved_config.get if hasattr(resolved_config, "get") else (lambda _k, _d=None: _d)
    return bool(get("deterministic", False)) or bool(get("allow_collisions", False))


def categorical_config_rejection(
    name: str,
    *,
    deterministic: bool,
    namespace: str | None,
    provider_config: dict[str, Any],
) -> str | None:
    """The coded reason a `categorical` column cannot run on the native
    operator, or None when it can (Phase 5 Track B). Delegates to
    `prepare_categorical`, the one validation both admission and execution use."""
    _artifact, reason = prepare_categorical(
        name,
        deterministic=deterministic,
        namespace=namespace,
        provider_config=provider_config,
    )
    return reason


def bucket_perturb_config_rejection(
    name: str,
    table: str,
    profile: Any | None,
    *,
    namespace: str | None,
    provider_config: dict[str, Any],
    resident_sources: Mapping[str, Any] | None = None,
) -> str | None:
    """The coded reason a `bucket_perturb` column cannot run natively, or None.

    v1 admits ONLY the string-source, explicit-`date_format`, tz-free,
    valid-bucket, namespaced variant; everything else declines to the oracle. The
    oracle defaults a missing bucket to "month" (`_bucket_perturb.py:54`) and
    treats a missing/empty/non-string `date_format` as autodetect (an
    order-dependent parity hazard). A non-string source declines (`astype(str)`
    is an identity only for strings, which keeps canonicalization byte-parity-
    safe). Both native boundaries call this ONE resolver so they never diverge.
    """
    if not namespace:
        return f"bucket_perturb_requires_namespace:{name}"
    bucket = str(provider_config.get("bucket", "month"))
    if bucket not in _VALID_BUCKET_PERTURB_BUCKETS:
        return f"bucket_perturb_unsupported_bucket:{name}"
    date_format = provider_config.get("date_format")
    if not isinstance(date_format, str) or not date_format:
        return f"bucket_perturb_requires_date_format:{name}"
    # A tz directive (%z/%Z) declines: the oracle reduces each value to a naive
    # `datetime.date` before strftime (dropping time AND tz) while the native
    # kernel keeps tz-aware Timestamps. Imported lazily so the pandas-bearing
    # kernel module stays off the planning boundary's module-load path.
    from decoy_engine.execution.native._bucket_perturb_ext import has_timezone_directive
    from decoy_engine.transforms.bucket_perturb import bucket_perturb_date_format_problem
    from decoy_engine.transforms.date_preserve import preserve_config_problem

    if has_timezone_directive(date_format):
        return f"bucket_perturb_timezone_directive:{name}"
    # Pandas parses these per element and accepts mixed UTC offsets that the native
    # DatetimeIndex build rejects, so the oracle must run them.
    if date_format in _PANDAS_SPECIAL_DATE_FORMATS:
        return f"bucket_perturb_special_date_format:{name}"
    # The shared rule compile and the handlers apply, so compile rejection
    # implies native rejection; the declines above stay native-only.
    if bucket_perturb_date_format_problem(date_format) is not None:
        return f"bucket_perturb_date_format_unsupported:{name}"
    # An invalid `preserve_values` declines so the oracle raises its coded config error; a valid
    # one is admitted (the wrapper carves the sentinel rows out around the kernel).
    if preserve_config_problem(provider_config) is not None:
        return f"bucket_perturb_preserve_values_invalid:{name}"
    # With neither a profile nor a resident source, the input type is
    # unknowable; defer to the unified-slice resident-type gate (matches
    # hash). A RESOLVED non-string type is rejected here, early.
    # `resident_sources`, when given, makes the resolution resident-Arrow-
    # authoritative (Track A Option 2); in the unified-slice lane it is
    # always given, so this deferral never actually fires there.
    if profile is not None or resident_sources is not None:
        resolved = resolve_input_arrow_type(table, name, profile, resident_sources=resident_sources)
        if resolved is not None and resolved != pa.string():
            return f"bucket_perturb_source_not_string:{name}:{resolved!s}"
    return None


# Distinguishes an ABSENT bound (the oracle applies its default) from one set
# explicitly to null (the oracle's `int(None)` raises), which `.get()` conflates.
_ABSENT = object()


def _date_shift_bound_rejection(name: str, key: str, value: Any) -> str | None:
    # The native lane takes plain integer bounds. A float or numeric string keeps its window on
    # the oracle, which coerces it the way `shift_window` does.
    if value is _ABSENT:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return f"date_shift_{key}_not_int:{name}"
    return None


def date_shift_config_rejection(
    name: str,
    table: str,
    profile: Any | None,
    *,
    namespace: str | None,
    provider_config: dict[str, Any],
    resident_sources: Mapping[str, Any] | None = None,
) -> str | None:
    """The coded reason a `date_shift` column cannot run natively, or None.

    v1 admits ONLY the namespaced, string-source, explicit-`date_format`,
    tz-free, no-`group_by` variant with integer day bounds. A missing format only
    reaches here for a top-level column whose declared parse format supplies it (plan compile
    refuses every other one), and that stays on the oracle; so does a truthy `group_by`, a
    pre-mask sibling anchor. `min_days`/`max_days` pass through the
    oracle's `int()`, which also accepts floats and numeric strings; v1 narrows
    to real ints so the native bound resolution cannot diverge from it.
    """
    if not namespace:
        return f"date_shift_requires_namespace:{name}"
    if provider_config.get("group_by"):
        return f"date_shift_group_by_not_native:{name}"
    date_format = provider_config.get("date_format")
    if not isinstance(date_format, str) or not date_format:
        return f"date_shift_requires_date_format:{name}"
    if date_format in _PANDAS_SPECIAL_DATE_FORMATS:
        return f"date_shift_special_date_format:{name}"
    from decoy_engine.execution.native._bucket_perturb_ext import has_timezone_directive

    if has_timezone_directive(date_format):
        return f"date_shift_timezone_directive:{name}"
    from decoy_engine.transforms.date_preserve import preserve_config_problem

    if preserve_config_problem(provider_config) is not None:
        return f"date_shift_preserve_values_invalid:{name}"
    # Imported lazily: the transform module pulls in pandas, which the planning boundary keeps
    # off its module-load path.
    from decoy_engine.transforms.date_shift import WINDOW_BOUND_KEYS, shift_window_problem

    for key in WINDOW_BOUND_KEYS:
        reason = _date_shift_bound_rejection(name, key, provider_config.get(key, _ABSENT))
        if reason is not None:
            return reason
    problem = shift_window_problem(provider_config)
    if problem is not None:
        return f"date_shift_{problem}:{name}"
    # With neither a profile nor a resident source, the input type is
    # unknowable and this defers to the unified-slice resident-type gate
    # (matches hash/bucket_perturb); a RESOLVED non-string type rejects here.
    # `resident_sources` makes the resolution resident-Arrow-authoritative
    # (Track A Option 2); the unified-slice lane always gives it, so this
    # deferral never actually fires there.
    if profile is not None or resident_sources is not None:
        resolved = resolve_input_arrow_type(table, name, profile, resident_sources=resident_sources)
        if resolved is not None and resolved != pa.string():
            return f"date_shift_source_not_string:{name}:{resolved!s}"
    return None


# The native group_key route admits ONLY these sibling resident types in v1.
# The full stringify-safe set is larger (`_chunked_group_key.group_by_type_is_safe`:
# integer, bool, string, large_string, date, timestamp), and the operator itself
# masks all of them byte-identically -- but the sibling MUST be an unmasked
# passthrough node, and passthrough's own production resident set is exactly
# {string, int64, bool} (`_unified_slice_resident_types._ADMITTED_RESIDENT_TYPES`).
# So a large_string/int32/uint64/date/timestamp sibling could never activate
# end-to-end anyway; admitting it here would over-advertise. Narrow to the
# intersection so admission is honest; float/decimal/dictionary stay excluded
# (str()/collision + exact-type-map reasons). Extending passthrough's resident
# set + end-to-end coverage for the wider set is a later slice.
def group_key_sibling_types(
    passthrough_types: frozenset[pa.DataType] | None,
) -> frozenset[pa.DataType]:
    """The intersection described above: passthrough's resident set narrowed to the types
    group_key can stringify safely, so widening passthrough never admits a float sibling.
    An unset passthrough domain admits no sibling (fail closed)."""
    from decoy_engine.execution._chunked_group_key import group_by_type_is_safe

    return frozenset(t for t in (passthrough_types or frozenset()) if group_by_type_is_safe(t))


_NATIVE_GROUP_KEY_SIBLING_TYPES = group_key_sibling_types(
    OPERATORS["passthrough"].unified_resident_types
)


def group_key_sibling_type_admitted(arrow_type: pa.DataType) -> bool:
    """Whether a group_by sibling's Arrow type is admitted to the native
    group_key route in v1: exactly `{string, int64, bool}` (see
    `_NATIVE_GROUP_KEY_SIBLING_TYPES`). Everything else -- including the wider
    stringify-safe types the operator supports but production passthrough cannot
    yet carry -- declines to the oracle."""
    return arrow_type in _NATIVE_GROUP_KEY_SIBLING_TYPES


def group_key_config_rejection(
    name: str,
    table: str,
    profile: Any | None,
    *,
    provider_config: dict[str, Any],
    resident_sources: Mapping[str, Any] | None = None,
) -> str | None:
    """The coded reason a `group_key` column cannot run natively, or None.

    v1 admits ONLY a column whose `group_by` sibling is present and resolves to
    a safe Arrow type (integer/bool/string/large_string/date/timestamp;
    float/decimal/dictionary excluded), with a valid even `length` in `[8, 64]`.
    `group_by` and `length` are already validated at plan-compile
    (`GroupKeyConfig.from_dict`), so those checks are defensive; the load-bearing
    gate here is the SIBLING type. With neither a profile nor a resident source,
    the sibling type is unknowable, so this defers to the unified-slice
    resident-type gate (matching hash) rather than guessing; `resident_sources`
    makes the resolution resident-Arrow-authoritative (Track A Option 2) and is
    always given in that lane. The order-dependence decline (the sibling must
    not itself be masked by another node) needs cross-node visibility the config
    boundary lacks and is enforced at `resident_contract_admission`, the
    full-visibility shadow-vs-oracle arbiter."""
    group_by = provider_config.get("group_by")
    if not isinstance(group_by, str) or not group_by:
        return f"group_key_requires_group_by:{name}"
    length = provider_config.get("length", 16)
    if isinstance(length, bool) or not isinstance(length, int):
        return f"group_key_length_not_int:{name}"
    if length % 2 != 0 or length < 8 or length > 64:
        return f"group_key_length_out_of_range:{name}"
    if profile is not None or resident_sources is not None:
        resolved = resolve_input_arrow_type(
            table, group_by, profile, resident_sources=resident_sources
        )
        if resolved is not None and not group_key_sibling_type_admitted(resolved):
            return f"group_key_group_by_type_not_native:{name}:{group_by}:{resolved!s}"
    return None


def text_redact_config_rejection(name: str, provider_config: Mapping[str, Any]) -> str | None:
    """The coded reason a `text_redact` column cannot run natively, or None.

    The native operator is the plain configuration: no `ner` (a model load per run), a string
    `token`, and `detectors` absent, null, a list or a tuple. The oracle leaves the source
    column untouched for a non-string token or a malformed `detectors`, so admitting either
    would stringify cells it never touches. Both config dispatchers call this ONE predicate.
    """
    if provider_config.get("ner"):
        return f"text_redact_ner_not_native:{name}"
    if "token" in provider_config and not isinstance(provider_config["token"], str):
        return f"text_redact_token_not_string:{name}"
    detectors = provider_config.get("detectors")
    if detectors is not None and not isinstance(detectors, (list, tuple)):
        return f"text_redact_detectors_malformed:{name}"
    return None


_ASCII_DIGITS = "0123456789"
_ASCII_ALPHANUM = _ASCII_DIGITS + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
# The oracle normalizes a checksum value before it validates it (stdnum `compact`, Unicode
# digits, Python `upper`). The native path skips that normalization, so it admits only a charset
# where every such step is the identity or ASCII uppercase: ASCII digits, and for vin ASCII
# letters too.
_NATIVE_CHECKSUM_ALPHABET: dict[str, str] = {"vin": _ASCII_ALPHANUM}

FpeChecksumContext = Literal["payload", "key"]


def fpe_checksum_rejection(
    column: str,
    scheme: str | None,
    resolved_charset: str,
    *,
    context: FpeChecksumContext,
) -> str | None:
    """The coded reason an fpe column with a `checksum` scheme stays on the oracle, or None.

    The one checksum decision: every route, the wrapper backstop and (later) text_mask detector
    eligibility call it, so a scheme can only become native in one place. An absent scheme
    passes. A key context declines first (FK parents and REMAP orphans stay on Python), then a
    scheme the registry does not list, then any charset symbol outside the native alphabet."""
    if not scheme:
        return None
    reason = f"fpe_checksum_not_native:{column}"
    if context == "key":
        return reason
    # A non-string scheme is malformed config: decline it coded instead of hashing it.
    if not isinstance(scheme, str) or scheme not in OPERATORS["fpe"].checksum_schemes:
        return reason
    allowed = _NATIVE_CHECKSUM_ALPHABET.get(scheme, _ASCII_DIGITS)
    if not resolved_charset or any(ch not in allowed for ch in resolved_charset):
        return reason
    return None


def fpe_checksum_config_rejection(
    column: str, provider_config: Mapping[str, Any], *, context: FpeChecksumContext
) -> str | None:
    """`fpe_checksum_rejection` for a provider-config mapping: reads the scheme, resolves the
    charset without raising (config validation stays at its own gate) and forwards both. An
    absent scheme is forwarded too: the shared decision alone says an absent scheme passes."""
    scheme = provider_config.get("checksum") or None
    spec = provider_config.get("charset", "digits")
    charset = resolve_fpe_charset(spec) if isinstance(spec, str) else ""
    return fpe_checksum_rejection(column, scheme, charset, context=context)


def text_mask_config_rejection(name: str, provider_config: Mapping[str, Any]) -> str | None:
    """The coded reason a `text_mask` column cannot run natively, or None.

    The native ARROW_PYTHON wrapper runs the FULL shipped handler per cell, including the faker,
    date_shift, fpe and sub-floor span branches, so the only config that declines is a TRUTHY
    `ner`: only the `ner` branch loads a spaCy model and supplies `extra_spans`, which the native
    wrapper does not reproduce (C6b-ii territory). Unlike text_redact, a non-string token or a
    malformed `detectors` does NOT decline here: text_mask normalizes a non-list `detectors` to
    "all detectors" and `str()`-coerces the token, the same as the oracle, so admitting them keeps
    byte parity. Both config dispatchers call this ONE predicate."""
    if provider_config.get("ner"):
        return f"text_mask_ner_not_native:{name}"
    return None


__all__ = [
    "FpeChecksumContext",
    "bucket_perturb_config_rejection",
    "categorical_config_rejection",
    "date_shift_config_rejection",
    "fpe_checksum_config_rejection",
    "fpe_checksum_rejection",
    "group_key_config_rejection",
    "group_key_sibling_type_admitted",
    "is_deterministic_categorical",
    "text_mask_config_rejection",
    "text_redact_config_rejection",
]
