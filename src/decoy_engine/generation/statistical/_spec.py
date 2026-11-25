"""Statistical column spec: validate config + snapshot into a sampler plan.

The spec layer owns every "is this config + artifact coherent?" question
so `_sample.py` can be pure draw logic and the plan compiler's
`check_statistical_columns` can reuse the same validation (one set of
error codes, raised here, surfaced either at compile time or at
generation time for unvalidated-dict callers).

Privacy gate: a categorical snapshot's `top_values` contain REAL values
from the source frame. Emitting them is a deliberate disclosure the
operator must opt into with `allow_real_categories: true`; without it
the spec refuses to load (`statistical_real_categories_not_allowed`).
Differential privacy lives at FIT time (`quality.dp.fit_dp_snapshot`);
the spec layer consumes exact and DP-fit snapshots identically EXCEPT
for one exemption: a categorical column whose snapshot the COMPILER has
already verified as an OpenDP-certified `dps-marginal/v3` release
(`dp_verified=True`, threaded in by the caller -- never inferred by
reading the snapshot's own `dp` key, guide section 5) does not need the
`allow_real_categories` consent gate, because there is no real vocabulary
in a verified DP artifact for it to release. `load_spec` never reopens a
snapshot path itself (guide section 4.7): the caller passes the already
pinned/parsed snapshot mapping.

`high_cardinality: true` (HC-5) opts a column into the FULL retained
vocabulary a fit step produced with `compute_distribution_snapshot(...,
high_cardinality_columns=...)` (quality/snapshot.py) -- it carries no
weight here beyond validating the config is coherent with that intent:
the flag requires `allow_real_categories: true` (retaining every
category is a LARGER disclosure than the top-K default, so it needs the
same consent gate, checked first for a specific error) and only makes
sense against a categorical snapshot kind. The sampler itself
(_sample.py) needs no high_cardinality-specific code: it already draws
over whatever `top_values` list the snapshot carries.

Freetext (deferred follow-up 4, 2026-06-12) is LENGTH-ONLY: the sampler
draws a target length from the fitted length histogram and fills with
deterministic lorem tokens. No source tokens are stored in the snapshot
(only length stats), so freetext needs no disclosure gate; a word-level
Markov mode that would store real n-grams is a recorded follow-up
behind its own opt-in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from decoy_engine import fileaccess, reasons
from decoy_engine._config_text import (
    Expected,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.contracts import distribution_snapshot as dsc
from decoy_engine.errors import DecoyError
from decoy_engine.fileaccess import FileRole
from decoy_engine.generation.statistical._cell_format import (
    CellFormat,
    cell_format_from_dict,
    decode_cell_format,
)
from decoy_engine.generation.statistical._degenerate import column_label
from decoy_engine.generation.statistical._numeric_shape import (
    decode_numeric_shape,
    numeric_shape_withheld,
)
from decoy_engine.generation.statistical._snapshot_io import parse_snapshot_json
from decoy_engine.generation.statistical._spec_refusals import (
    dp_carrier_refusal,
    withheld_values_refusal,
)

_SUPPORTED_KINDS = ("numeric", "categorical", "datetime", "freetext")
# `empty` (an all-null source column) is sampled only when the snapshot carries a `cell_format`
# block, which is what makes "all null" a stated fact rather than a missing histogram.
_EMPTY_KIND = "empty"
_OTHER_MODES = ("redistribute", "emit")

# The placeholder emitted for tail mass under other_mode="emit".
OTHER_TOKEN = "__other__"  # noqa: S105 -- a column placeholder value, not a credential


class StatisticalSpecError(DecoyError):
    """Config/artifact mismatch for a statistical column. Machine-readable code."""

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _refuse(code: str, refusal: Refusal) -> StatisticalSpecError:
    return StatisticalSpecError(code=code, message=refusal.text)


@dataclass(frozen=True)
class StatisticalSpec:
    """Everything `sample_column` needs, validated."""

    column: str
    source_column: str
    kind: str  # numeric | categorical | datetime
    dtype: str
    stats: dict[str, Any]
    other_mode: str
    condition_on: str | None
    joint: dict[str, Any] | None  # the snapshot joint entry when condition_on
    parent_first: bool  # joint key order: True when condition_on is key[0]
    # The pinned snapshot's SHA-256 hex digest (guide section 4.7's read-once
    # pass), or None when this spec was built outside that pass (a direct/
    # unvalidated-dict caller with no Plan). Generation-time seed derivation
    # (`generators.derivation.strategy_config_fingerprint`) needs a content
    # digest for its `snapshot_file` fingerprint input; without this field it
    # had no pinned digest to reuse and fell back to re-opening
    # `col_cfg["snapshot_file"]` from disk at generate time -- a real TOCTOU
    # reopen of a path the Plan already pinned (guide section 4.7/4.8, defect
    # F4). Carrying the digest here lets the statistical generator branch
    # reuse it instead, closing that reopen without touching the sampler.
    snapshot_digest: str | None = None
    # DPS-CODEC phase 6 (guide section 3.4/3.9): the column's typed DP carrier
    # (`number`/`flag`/`text`), or None. `None` is the legacy non-DP sampling
    # path (every `distribution-snapshot/v1` column, unconditionally -- a
    # stray `carrier` key there is never honored, see `load_spec`); a set
    # carrier is the codec path a verified `dps-marginal/v3` DP release uses.
    # The sampler (`_sample.py`) dispatches on `carrier is None` for exactly
    # this reason, so legacy behavior stays byte-identical.
    carrier: str | None = None
    # Fitted cell shape (`generation/statistical/_cell_format.py`); None for a snapshot without the
    # block, which keeps the old draw sequence byte for byte.
    cell_format: CellFormat | None = None
    # Year ranges from the contract decoder; admission and the sampler read these, not `year_bins`.
    datetime_buckets: tuple[dsc.DatetimeBucket, ...] | None = None


def spec_to_dict(spec: StatisticalSpec) -> dict[str, Any]:
    """Plain-dict form of a validated `StatisticalSpec`, for embedding into
    `PinnedStatisticalSpec.spec` (guide section 4.7). `dataclasses.asdict` is exact here because
    every field is a JSON-shaped value. `carrier` (a DP-v3-only field), `cell_format`,
    `datetime_buckets` and an unset `cell_format.char_class` are dropped when `None`, so a spec
    without them serializes exactly as before and an older serialized Plan deserializes unchanged."""
    data = asdict(spec)
    if data.get("carrier") is None:
        del data["carrier"]
    if data.get("cell_format") is None:
        del data["cell_format"]
    elif data["cell_format"].get("char_class") is None:
        del data["cell_format"]["char_class"]
    if data.get("datetime_buckets") is None:
        del data["datetime_buckets"]
    return data


def spec_from_dict(data: Mapping[str, Any]) -> StatisticalSpec:
    """Inverse of `spec_to_dict`: reconstruct a `StatisticalSpec` from its
    plain-dict (or thawed frozen-mapping) form. A missing `carrier` key
    (every pre-phase-6 serialized spec, and every legacy non-DP spec)
    defaults to `None`, matching `spec_to_dict`'s omission."""
    return StatisticalSpec(
        column=str(data["column"]),
        source_column=str(data["source_column"]),
        kind=str(data["kind"]),
        dtype=str(data["dtype"]),
        stats=dict(data["stats"]),
        other_mode=str(data["other_mode"]),
        condition_on=data["condition_on"],
        joint=dict(data["joint"]) if data.get("joint") is not None else None,
        parent_first=bool(data["parent_first"]),
        snapshot_digest=data.get("snapshot_digest"),
        carrier=data.get("carrier"),
        cell_format=cell_format_from_dict(
            column_label(data["column"]), str(data["kind"]), data.get("cell_format")
        ),
        datetime_buckets=dsc.pinned_buckets(
            str(data["kind"]), dict(data["stats"]), data.get("datetime_buckets")
        ),
    )


# `_load_snapshot` is the sole `open()` site for a snapshot artifact in this package (guide section
# 4.7 item 3). `load_spec` never calls it: it takes the snapshot the compiler already read and
# pinned. It remains for compile-time callers that must read a path, and for tests building fixtures.
def _load_snapshot(path: str, field_key: str = "snapshot_file") -> tuple[str, dict[str, Any]]:
    """Read + parse a snapshot artifact. Returns `(content_sha256, parsed)`.
    No caching: every call is a fresh read + hash + parse."""
    key = fileaccess.position_key(field_key)
    at_snapshot = config_position(Name(field_key))
    # Reading and parsing run through `read_config`, so the refusal holds a position and no
    # exception text, and has no cause or context.
    raw = read_config(
        lambda: fileaccess.read_all(FileRole.SNAPSHOT, path, key),
        at_snapshot,
        lambda r: _refuse(reasons.plan.STATISTICAL_SNAPSHOT_UNREADABLE, r),
    )
    digest = hashlib.sha256(raw).hexdigest()
    snap = parse_snapshot_json(raw, shown=field_key)
    if not isinstance(snap, dict):
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_SNAPSHOT_SCHEMA_MISMATCH,
                config_refusal(
                    at_snapshot,
                    Problem.WRONG_TYPE,
                    expected=Expected.MAPPING,
                    got=snap,
                    hint="The snapshot must be a JSON object at the top level",
                ),
            )
        )
    version = snap.get("schema_version")
    if version not in dsc.ACCEPTED_SCHEMA_VERSIONS:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_SNAPSHOT_SCHEMA_MISMATCH,
                config_refusal(
                    config_position(Name(field_key), "schema_version"),
                    Problem.MISMATCH,
                    expected=Expected.SCHEMA_VERSION,
                    hint="This engine consumes only the accepted schema versions",
                ),
            )
        )
    return digest, snap


def load_spec(
    col_cfg: dict[str, Any],
    *,
    snapshot: Mapping[str, Any],
    dp_verified: bool = False,
    snapshot_digest: str | None = None,
) -> StatisticalSpec:
    """Validate a `type: statistical` generate column into a sampler spec.

    Args:
        col_cfg: The generate-column config entry (name, source_column,
            other_mode, condition_on, allow_real_categories,
            high_cardinality).
        snapshot: The ALREADY parsed, already pinned snapshot artifact
            (guide section 4.7) -- this function never opens
            `col_cfg["snapshot_file"]` itself.
        dp_verified: Whether the PLAN COMPILER has verified this exact
            snapshot as an OpenDP-certified `dps-marginal/v3` release for
            this column (guide section 5). Never derived by reading
            `snapshot["dp"]` here -- an unverified `dp`-shaped key in an
            otherwise ordinary snapshot must not exempt anything; only the
            compiler's own verdict does.
        snapshot_digest: The pinned snapshot's SHA-256 hex digest, when the
            caller read it through the compile-time read-once pass
            (`plan._generation.read_and_pin_snapshots`). Carried onto the
            returned spec so generation-time seed derivation can reuse it
            instead of reopening `snapshot_file` (see `StatisticalSpec.
            snapshot_digest`).

    Raises StatisticalSpecError with a stable code on every mismatch;
    the plan compiler surfaces the same codes at validate time.
    """
    name = col_cfg.get("name", "<unnamed>")
    snap = snapshot
    # The raw config object, never `str(...)` of it: converting a list or a mapping would turn
    # its items into text that then looks like an approvable name.
    source_column = col_cfg.get("source_column") or name
    column_text = column_label(name)
    at_source = config_position("statistical", Name(name), "source_column")
    if type(source_column) is not str:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_COLUMN_NOT_IN_SNAPSHOT,
                config_refusal(
                    at_source, Problem.WRONG_TYPE, expected=Expected.STRING, got=source_column
                ),
            )
        )
    col_entry = (snap.get("columns") or {}).get(source_column)
    if col_entry is None:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_COLUMN_NOT_IN_SNAPSHOT,
                config_refusal(
                    config_position(
                        "statistical", Name(name), "source_column", Name(source_column)
                    ),
                    Problem.NOT_FOUND,
                    hint="The source column is not in the snapshot",
                ),
            )
        )
    carrier, dp_refusal = dp_carrier_refusal(
        snap, col_entry, source_column, at_source, dp_verified=dp_verified
    )
    if dp_refusal is not None:
        raise_bare(_refuse(*dp_refusal))

    kind = col_entry.get("kind")
    cell_format = (
        decode_cell_format(
            column_text,
            str(kind),
            col_entry,
            snapshot=snap,
            # `null_probability` is None-means-absent: any other value, 0 included, owns the nulls.
            apply_nulls=col_cfg.get("null_probability") is None,
        )
        if kind in (*_SUPPORTED_KINDS, _EMPTY_KIND)
        else None
    )
    if kind not in _SUPPORTED_KINDS and not (kind == _EMPTY_KIND and cell_format is not None):
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_KIND_UNSUPPORTED,
                config_refusal(
                    at_source,
                    Problem.NOT_ALLOWED,
                    choices=_SUPPORTED_KINDS,
                    hint="The snapshot kind has no sampler",
                ),
            )
        )

    high_cardinality = col_cfg.get("high_cardinality")
    if high_cardinality is not None and not isinstance(high_cardinality, bool):
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_HIGH_CARDINALITY_INVALID_TYPE,
                config_refusal(
                    config_position("statistical", Name(name), "high_cardinality"),
                    Problem.WRONG_TYPE,
                    expected=Expected.BOOLEAN,
                    got=high_cardinality,
                ),
            )
        )
    high_cardinality = bool(high_cardinality)

    # HIGH-1 (gate remediation): `bool("false")` is True, so a truthy
    # non-bool string/int would otherwise sail through the consent gates
    # below. Validate the type up front (same shape as high_cardinality
    # above) and gate on `is True` identity, never `bool(...)` coercion.
    allow_real = col_cfg.get("allow_real_categories")
    if allow_real is not None and not isinstance(allow_real, bool):
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_ALLOW_REAL_CATEGORIES_INVALID_TYPE,
                config_refusal(
                    config_position("statistical", Name(name), "allow_real_categories"),
                    Problem.WRONG_TYPE,
                    expected=Expected.BOOLEAN,
                    got=allow_real,
                ),
            )
        )

    # A conditioning request is validated before anything reads it: the withheld-values check
    # below compares it to the snapshot's column lists, and a mistyped one must be refused as
    # mistyped, not as a withheld column, whatever else is wrong with the snapshot.
    condition_on = col_cfg.get("condition_on")
    if condition_on is not None:
        at_condition = config_position("statistical", Name(name), "condition_on")
        if kind != "categorical":
            raise_bare(
                _refuse(
                    reasons.plan.STATISTICAL_CONDITION_KIND_INVALID,
                    config_refusal(
                        at_condition,
                        Problem.NOT_ALLOWED,
                        hint="condition_on is supported for categorical columns only",
                    ),
                )
            )
        if type(condition_on) is not str:
            raise_bare(
                _refuse(
                    reasons.plan.STATISTICAL_JOINT_MISSING,
                    config_refusal(
                        at_condition,
                        Problem.WRONG_TYPE,
                        expected=Expected.STRING,
                        got=condition_on,
                    ),
                )
            )

    col_stats = col_entry.get("stats") if isinstance(col_entry.get("stats"), dict) else {}
    withheld = withheld_values_refusal(
        name,
        snap,
        source_column=source_column,
        kind=kind,
        dp_verified=dp_verified,
        condition_on=condition_on,
        holds_numeric_shape=kind == "numeric"
        and not dp_verified
        and numeric_shape_withheld(col_stats),
    )
    if withheld is not None:
        raise_bare(_refuse(reasons.plan.STATISTICAL_SNAPSHOT_VALUES_REDACTED, withheld))

    if high_cardinality and col_cfg.get("allow_real_categories") is not True:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_HIGH_CARDINALITY_REQUIRES_REAL_CATEGORIES,
                config_refusal(
                    config_position("statistical", Name(name), "high_cardinality"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "high_cardinality retains the FULL observed category vocabulary "
                        "(no top-K collapse), a larger disclosure than the default; it "
                        "requires `allow_real_categories: true` on the same column "
                        "(explicit disclosure opt-in)"
                    ),
                ),
            )
        )

    if (
        kind == "categorical"
        and not dp_verified
        and col_cfg.get("allow_real_categories") is not True
    ):
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_REAL_CATEGORIES_NOT_ALLOWED,
                config_refusal(
                    config_position("statistical", Name(name), "allow_real_categories"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "The snapshot's top_values contain REAL source values; emitting "
                        "them requires `allow_real_categories: true` on the column "
                        "(explicit disclosure opt-in), unless the compiler has verified "
                        "this snapshot as an OpenDP-certified DP release"
                    ),
                ),
            )
        )

    if high_cardinality and kind != "categorical":
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_HIGH_CARDINALITY_KIND_INVALID,
                config_refusal(
                    config_position("statistical", Name(name), "high_cardinality"),
                    Problem.MISMATCH,
                    hint=(
                        "high_cardinality requires a categorical snapshot kind. Re-fit the "
                        "source column with high_cardinality set so the fit step forces it "
                        "categorical"
                    ),
                ),
            )
        )

    # HIGH-2 (gate remediation): `high_cardinality: true` on the generate
    # side is a promise that the FIT step retained the full vocabulary
    # (quality/snapshot.py::_high_cardinality_categorical_stats stamps a
    # `high_cardinality: true` marker on the column stats for exactly this
    # reason). A snapshot fit WITHOUT that flag -- ordinary top-K collapse,
    # `other_count` possibly > 0 -- must not be silently accepted here: the
    # tail is already gone from the artifact, so redistribution would
    # permanently drop it. Provenance marker, not `other_count`, is the
    # source of truth (DP snapshots deep-copy the marker through noising).
    if high_cardinality and col_stats.get("high_cardinality") is not True:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_HIGH_CARDINALITY_SNAPSHOT_MISMATCH,
                config_refusal(
                    config_position("statistical", Name(name), "high_cardinality"),
                    Problem.MISMATCH,
                    hint=(
                        "high_cardinality is set but the snapshot column was not fit with "
                        "full-vocabulary retention (no `high_cardinality` marker on the "
                        "column stats). Re-fit the source column with "
                        "`compute_distribution_snapshot(..., high_cardinality_columns=[...])` "
                        "before setting high_cardinality: true here"
                    ),
                ),
            )
        )

    if kind == "numeric":
        decode_numeric_shape(column_text, col_stats, carrier)  # refuse a malformed block at load

    other_mode = str(col_cfg.get("other_mode") or "redistribute")
    if other_mode not in _OTHER_MODES:
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_OTHER_MODE_INVALID,
                config_refusal(
                    config_position("statistical", Name(name), "other_mode"),
                    Problem.NOT_ALLOWED,
                    choices=_OTHER_MODES,
                ),
            )
        )

    # `emit` inserts OTHER_TOKEN ("__other__") as a sampled value, which is not
    # a flag value -- a bool column has exactly two categories and no tail
    # placeholder to emit. Flag columns redistribute tail mass across
    # true/false instead (guide section 3.4).
    if carrier == "flag" and other_mode == "emit":
        raise_bare(
            _refuse(
                reasons.plan.STATISTICAL_FLAG_OTHER_MODE_EMIT_INVALID,
                config_refusal(
                    config_position("statistical", Name(name), "other_mode"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "other_mode='emit' is not valid for a `flag` carrier column "
                        "('__other__' is not a bool value); use other_mode='redistribute' "
                        "(the default) for flag columns"
                    ),
                ),
            )
        )

    joint: dict[str, Any] | None = None
    parent_first = False
    if condition_on is not None:
        # Only a plain string names a column: the raw value is looked at as it is, never
        # converted, so a list or a mapping cannot turn its items into a name.
        assert isinstance(condition_on, str)  # noqa: S101 - refused above
        pair = sorted((condition_on, source_column))
        for entry in snap.get("joints") or []:
            if list(entry.get("columns") or []) == pair:
                joint = entry
                break
        if joint is None:
            raise_bare(
                _refuse(
                    reasons.plan.STATISTICAL_JOINT_MISSING,
                    config_refusal(
                        config_position(
                            "statistical", Name(name), "condition_on", Name(condition_on)
                        ),
                        Problem.NOT_FOUND,
                        hint=(
                            "The snapshot has no joint contingency for this column pair. "
                            "Re-fit with `decoy fit --joint <condition_on>,<source_column>`"
                        ),
                    ),
                )
            )
        parent_first = joint["columns"][0] == condition_on

    buckets = None
    if kind == "datetime":
        buckets = dsc.decoded_or_none(snap.get("schema_version"), col_stats)
        if buckets is None:
            raise_bare(
                _refuse(
                    reasons.plan.STATISTICAL_SNAPSHOT_SCHEMA_MISMATCH,
                    config_refusal(
                        at_source,
                        Problem.MISMATCH,
                        hint=(
                            "The snapshot schema_version or the datetime year_bins is not "
                            "a supported shape"
                        ),
                    ),
                )
            )
    return StatisticalSpec(
        column=str(name),
        source_column=source_column,
        kind=str(kind),
        dtype=str(col_entry.get("dtype") or ""),
        stats=dict(col_entry.get("stats") or {}),
        other_mode=other_mode,
        condition_on=condition_on,
        joint=joint,
        parent_first=parent_first,
        snapshot_digest=snapshot_digest,
        carrier=carrier,
        cell_format=cell_format,
        datetime_buckets=buckets,
    )
