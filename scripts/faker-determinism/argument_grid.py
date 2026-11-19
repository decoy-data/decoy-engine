"""The derived caller-argument surface of the Faker output lock, and its grid.

Callers reach Faker with arguments through four seams: YAML `faker_kwargs` into the reflected
wrapper and the separate `address` wrapper, `ProviderSpec.extra` into the V2 adapter, and formula
arguments. This module discovers those targets from the runtime callables and their effective
signatures (never source text), derives one grid of rows, and holds the closed descriptor codec the
lock stores them in. Engine seams arrive as the `access` argument (`_engine_access.py`).
"""

from __future__ import annotations

import inspect
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

# Objects and types Faker accepts that no JSON scalar can carry. The wire format names an entry of
# one of these fixed tables; it never imports, constructs or evaluates anything.
_TZ_BY_NAME: dict[str, Any] = {
    "utc": timezone.utc,
    "plus0530": timezone(timedelta(hours=5, minutes=30)),
}
_CALLABLE_BY_NAME: dict[str, Any] = {"str": str, "int": int, "float": float}
_TYPE_BY_NAME: dict[str, Any] = {"bool": bool, "int": int, "float": float, "str": str}


class _SortedKeysEncoder(json.JSONEncoder):
    """A named `cls` representative whose output differs from the default encoder's."""

    def __init__(self, **kw: Any) -> None:
        kw["sort_keys"] = True
        super().__init__(**kw)


_CLASS_BY_NAME: dict[str, Any] = {"sorted_keys_encoder": _SortedKeysEncoder}
_NAMED_TABLES: dict[str, dict[str, Any]] = {
    "tz": _TZ_BY_NAME,
    "callable": _CALLABLE_BY_NAME,
    "class": _CLASS_BY_NAME,
}

FAMILIES = ("reflected", "address_override", "adapter", "formula")
ARGUMENT_SEEDS = (0, 7)
ROW_LIMIT = 64_000  # locale-case rows
BYTE_LIMIT = 32 * 1024 * 1024  # canonical lock bytes


def text_within_limit(text: str) -> bool:
    return len(text.encode("utf-8")) <= BYTE_LIMIT


_EMPTY = inspect.Parameter.empty
_VAR_KW, _VAR_POS = inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL
_KW_NAME, _POS_NAME = _VAR_KW.name, _VAR_POS.name
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class OutputLockError(RuntimeError):
    """A refusal with a fixed message: no value, no exception text."""


# --- descriptors: strict JSON scalars plus closed date, datetime, tuple and mapping tags ---------


def descriptor_ok(d: object, depth: int = 0) -> bool:
    if d is None or type(d) in (bool, int, str):
        return True
    if type(d) is float:
        return math.isfinite(d)
    if depth > 3 or not isinstance(d, dict) or len(d) != 1:
        return False
    ((tag, body),) = d.items()
    if tag == "date":
        return type(body) is str and _DATE_RE.fullmatch(body) is not None and _parses(date, body)
    if tag == "datetime":
        return (
            type(body) is str
            and _DATETIME_RE.fullmatch(body) is not None
            and _parses(datetime, body)
        )
    if tag in _NAMED_TABLES:
        return type(body) is str and body in _NAMED_TABLES[tag]
    if tag == "types":
        return type(body) is list and all(type(x) is str and x in _TYPE_BY_NAME for x in body)
    if tag == "tuple":
        return type(body) is list and all(descriptor_ok(x, depth + 1) for x in body)
    if tag == "mapping":
        return isinstance(body, dict) and all(
            type(k) is str and descriptor_ok(v, depth + 1) for k, v in body.items()
        )
    return False


def _parses(kind: Any, text: str) -> bool:
    try:
        kind.fromisoformat(text)
    except ValueError:
        return False
    return True


def decode_descriptor(d: Any) -> Any:
    if not descriptor_ok(d):
        raise OutputLockError("an argument descriptor is not accepted")
    if not isinstance(d, dict):
        return d
    ((tag, body),) = d.items()
    if tag == "date":
        return date.fromisoformat(body)
    if tag == "datetime":
        return datetime.fromisoformat(body)
    if tag in _NAMED_TABLES:
        return _NAMED_TABLES[tag][body]
    if tag == "types":
        return tuple(_TYPE_BY_NAME[x] for x in body)
    if tag == "tuple":
        return tuple(decode_descriptor(x) for x in body)
    return {k: decode_descriptor(v) for k, v in body.items()}


def encode_descriptor(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str, float):
        return value
    if isinstance(value, datetime):
        return {"datetime": value.isoformat(timespec="seconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    for tag, table in _NAMED_TABLES.items():
        for name, obj in table.items():
            if value is obj or (tag == "tz" and isinstance(value, timezone) and value == obj):
                return {tag: name}
    if isinstance(value, tuple) and value and all(x in _TYPE_BY_NAME.values() for x in value):
        return {"types": [next(n for n, t in _TYPE_BY_NAME.items() if t is x) for x in value]}
    if isinstance(value, tuple):
        return {"tuple": [encode_descriptor(x) for x in value]}
    if isinstance(value, dict):
        return {"mapping": {k: encode_descriptor(v) for k, v in value.items()}}
    raise OutputLockError("an argument value has no descriptor")


def arguments_ok(v: object) -> bool:
    if not isinstance(v, dict) or set(v) != {"args", "kwargs"}:
        return False
    args, kwargs = v["args"], v["kwargs"]
    return (
        type(args) is list
        and all(descriptor_ok(a) for a in args)
        and isinstance(kwargs, dict)
        and all(type(k) is str and descriptor_ok(x) for k, x in kwargs.items())
    )


# --- the parameter-shape registry ----------------------------------------------------------------

# Kind of a parameter whose default does not decide it (no default, or `None`): the one reviewed
# table. A name missing here fails discovery, so a new parameter is a reviewed edit.
# fmt: off
PARAMETER_KIND_BY_NAME: dict[str, str] = {
    "tzinfo": "tz", "cast_to": "callable", "cls": "class", "card_type": "str",
    "ext_word_list": "seq", "header": "seq", "schemes": "seq", "data_columns": "seq",
    "hue": "str", "luminosity": "str", "gender": "str", "category": "str", "domain": "str",
    "state_abbr": "str", "province_abbr": "str", "region_name": "str", "address_class": "str",
    "part_of_speech": "str", "prefix": "str", "base": "str", "code": "str", "argument": "str",
    "tld": "str", "extension": "str", "private": "str", "group": "str", "formatter": "str",
    "name": "str", "length": "int", "left_digits": "int", "right_digits": "int", "deep": "int",
    "number_system_digit": "int", "year": "int", "month": "int", "day": "int", "indent": "int",
    "center": "float", "min_value": "int", "max_value": "int", "positive": "bool",
    "leading_zero": "bool", "birthdate": "date", "end_datetime": "datetime",
    "start_datetime": "datetime", "date_start": "date", "date_end": "date",
    "datetime_start": "date", "datetime_end": "date", "min_chars": "int", "digits": "int",
    "min": "int", "max": "int", "use_weighting": "bool", "value": "str", "value_types": "types",
    "allowed_types": "types", "province_prefix": "str", "bank_code": "int", "dob": "str",
    "date_of_birth": "datetime", "sex": "str", "pesel": "str", "x": "seq", "birthday": "str",
}
# fmt: on
# Lower/upper pairs that also get ordered and equal-boundary rows.
BOUND_PAIRS = (
    ("min", "max"),
    ("min_value", "max_value"),
    ("min_age", "max_age"),
    ("minimum_age", "maximum_age"),
    ("version_from", "version_to"),
    ("build_from", "build_to"),
    ("start", "end"),
    ("start_date", "end_date"),
    ("start_datetime", "end_datetime"),
    ("date_start", "date_end"),
    ("datetime_start", "datetime_end"),
)
_FLOATS = {"center", "radius"}
_NUMBER_REP = {"ordered": (3, 9), "equal": (7, 7)}
_DATE_REP = {
    "relative": ("-30d", "+30d"),
    "absolute": ("2001-03-04", "2009-10-11"),
    "typed": ({"date": "2001-03-04"}, {"date": "2009-10-11"}),
    "equal": ({"date": "2001-03-04"}, {"date": "2001-03-04"}),
}


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # the inspect kind name
    shape: (
        str  # bool, int, float, str, seq, map, date, datetime, tz, callable, class, types or none
    )
    default_is: str  # the default's type name ("" when it has none)


@dataclass(frozen=True)
class Target:
    family: str
    name: str
    method: str
    params: tuple[Param, ...]
    positional: bool  # formula only: arguments may be positional

    def signature_key(self) -> tuple[Any, ...]:
        return (self.family, self.name, self.method, self.params)


def _shape(p: inspect.Parameter) -> str:
    d = p.default
    if p.kind in (_VAR_KW, _VAR_POS):
        return "map" if p.kind == _VAR_KW else "seq"
    if isinstance(d, str) and "datetime.date" in str(p.annotation):
        return "date"
    if d is not None and d is not _EMPTY:
        for typ, shape in (
            (bool, "bool"),
            (int, "int"),
            (float, "float"),
            (str, "str"),
            (tuple, "seq"),
            (list, "seq"),
            (dict, "map"),
            (datetime, "datetime"),
            (date, "date"),
        ):
            if isinstance(d, typ):
                return shape
        if callable(d):
            return PARAMETER_KIND_BY_NAME.get(p.name, "none")
    if p.name in PARAMETER_KIND_BY_NAME:
        return PARAMETER_KIND_BY_NAME[p.name]
    raise OutputLockError(f"parameter {p.name!r} has no entry in PARAMETER_KIND_BY_NAME")


def params_of(method: Any) -> tuple[Param, ...]:
    out = []
    for p in inspect.signature(method).parameters.values():
        default = p.default
        out.append(
            Param(
                p.name, p.kind.name, _shape(p), "" if default is _EMPTY else type(default).__name__
            )
        )
    return tuple(out)


def _closure(fn: Any, name: str) -> Any:
    code = getattr(fn, "__code__", None)
    if code is None or name not in code.co_freevars:
        raise OutputLockError("a production wrapper does not expose its Faker call")
    return fn.__closure__[code.co_freevars.index(name)].cell_contents


# --- discovery -----------------------------------------------------------------------------------


def discover(access: Any, fake: Any, adapter_names: list[str]) -> list[Target]:
    """Every caller-argument target of one locale, from runtime callables and signatures."""
    out: list[Target] = []
    for name, wrapper in sorted(access.get_faker_providers(fake, provider_snapshot={}).items()):
        if name == "address":
            out.append(
                Target(
                    "address_override",
                    name,
                    name,
                    params_of(_closure(wrapper, "fake").address),
                    False,
                )
            )
        else:
            out.append(
                Target("reflected", name, name, params_of(_closure(wrapper, "method")), False)
            )
    for name in adapter_names:
        method = access.faker_method_map[name]
        target = (
            access.dob_method(fake) if method == "date_of_birth" else getattr(fake, method, None)
        )
        out.append(Target("adapter", name, method, params_of(target) if target else (), False))
    for name, fn in sorted(access.formula_scope(fake).items()):
        found = _formula_target(access, fake, name, fn)
        if found is not None:
            out.append(found)
    return out


def _formula_target(access: Any, fake: Any, name: str, fn: Any) -> Target | None:
    if inspect.ismethod(fn):  # a bound Faker method
        if not (getattr(fn, "__module__", "") or "").startswith("faker."):
            return None
        return Target("formula", name, fn.__name__, params_of(fn), True)
    code = getattr(fn, "__code__", None)
    if code is None:
        return None
    if "anchored_date_of_birth" in code.co_names:
        return Target("formula", name, "date_of_birth", params_of(access.dob_method(fake)), True)
    if "faker" not in code.co_names:
        return None
    if any(p.kind in (_VAR_KW, _VAR_POS) for p in inspect.signature(fn).parameters.values()):
        raise OutputLockError("a formula wrapper has opaque arguments and no effective signature")
    return Target("formula", name, name, params_of(fn), True)


# --- row derivation ------------------------------------------------------------------------------


def _scalar_rep(p: Param) -> Any:
    if p.shape == "bool":
        return True
    if p.shape in ("int", "float"):
        return 0.5 if p.shape == "float" or p.name in _FLOATS else 7
    if p.shape == "str":
        return "q"
    if p.shape == "seq":
        return {"tuple": ["a", "b"]}
    if p.shape == "map":
        return {"mapping": {"delimiter": ";"}} if p.kind == _KW_NAME else {"mapping": {"a": 1}}
    if p.shape == "date":
        return "-30d"
    if p.shape == "datetime":
        return {"datetime": "2001-03-04T05:06:07"}
    if p.shape == "tz":
        return {"tz": "plus0530"}
    if p.shape == "callable":
        return {"callable": "int"}
    if p.shape == "class":
        return {"class": "sorted_keys_encoder"}
    if p.shape == "types":
        return {"types": ["str", "int"]}
    return None


def _row(label: str, covers: list[str], args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"label": label, "covers": covers, "arguments": {"args": args, "kwargs": kwargs}}


def derive_rows(t: Target) -> list[dict[str, Any]]:
    """The rows one target needs: every settable parameter appears in some row's `covers`."""
    ps = [p for p in t.params if p.kind not in (_POS_NAME,)]
    named = {p.name: p for p in ps if p.kind != _KW_NAME}
    rows: list[dict[str, Any]] = []
    if not ps and t.family in ("address_override", "adapter"):
        return [_row("unexpected_keyword", [], [], {"unexpected_keyword": 1})]
    done: set[str] = set()
    for lo, hi in BOUND_PAIRS:
        if lo in named and hi in named:
            done |= {lo, hi}
            kinds = {named[lo].shape, named[hi].shape}
            if kinds <= {"int", "float"}:
                for tag, (a, b) in _NUMBER_REP.items():
                    rows.append(_row(f"{lo}_{hi}_{tag}", [lo, hi], [], {lo: a, hi: b}))
            else:
                for tag, (da, db) in _DATE_REP.items():
                    rows.append(_row(f"{lo}_{hi}_{tag}", [lo, hi], [], {lo: da, hi: db}))
    for p in ps:
        if p.name in done:
            continue
        if p.kind == _KW_NAME:
            rows.append(_row(f"{p.name}_mapping", [p.name], [], _unpack(_scalar_rep(p))))
        elif p.shape == "bool":
            rows += [
                _row(f"{p.name}_{v}", [p.name], [], {p.name: v == "true"})
                for v in ("false", "true")
            ]
        elif p.shape == "date":
            for tag, (da, _) in _DATE_REP.items():
                if tag != "equal":
                    rows.append(_row(f"{p.name}_{tag}", [p.name], [], {p.name: da}))
        else:
            rows.append(_row(f"{p.name}_set", [p.name], [], {p.name: _scalar_rep(p)}))
    pos = [p for p in t.params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    if t.positional and pos:
        rows.append(
            _row(
                "positional_" + "_".join(p.name for p in pos),
                [p.name for p in pos],
                [_positional_rep(p) for p in pos],
                {},
            )
        )
    return rows


def _unpack(rep: Any) -> dict[str, Any]:
    return dict(rep["mapping"])


def _positional_rep(p: Param) -> Any:
    low = {lo for lo, _ in BOUND_PAIRS}
    if p.shape in ("int", "float"):
        return (
            3 if p.name in low else 9 if p.name in {hi for _, hi in BOUND_PAIRS} else _scalar_rep(p)
        )
    return _scalar_rep(p)


def analyze(
    access: Any, locales: list[str]
) -> tuple[dict[str, Any], dict[tuple[str, str, str], set[str]]]:
    """`(grid, provenance)`: the case-id to row map for the locales (identical rows coalesce with
    their locale lists), and `(locale, family, target) -> settable parameter names`.

    A case id names the family, target and row label, and a row's arguments and covers depend only
    on the parameter names and shapes, so one id never carries two definitions (checked)."""
    names = [c.provider for c in access.default_registry().faker_providers()]
    grid: dict[str, Any] = {}
    provenance: dict[tuple[str, str, str], set[str]] = {}
    for locale in sorted(locales):
        for target in discover(access, access.make_faker(locale), names):
            settable = {p.name for p in target.params if p.kind != _POS_NAME}
            provenance[(locale, target.family, target.name)] = settable
            for row in derive_rows(target):
                case_id = f"{target.family}.{target.name}.{row['label']}"
                mine = {
                    "family": target.family,
                    "target": target.name,
                    "method": target.method,
                    "covers": sorted(row["covers"]),
                    "arguments": row["arguments"],
                }
                seen = grid.setdefault(case_id, {**mine, "locales": []})
                if {k: seen[k] for k in mine} != mine:
                    raise OutputLockError("a grid case id has two different row definitions")
                seen["locales"].append(locale)
    return {k: grid[k] for k in sorted(grid)}, provenance


def derive_grid(access: Any, locales: list[str]) -> dict[str, Any]:
    return analyze(access, locales)[0]


def projected_rows(grid: dict[str, Any]) -> int:
    return sum(len(r["locales"]) for r in grid.values())


def check_caps(grid: dict[str, Any]) -> None:
    if projected_rows(grid) > ROW_LIMIT:
        raise OutputLockError("the derived argument grid exceeds the locale-case row cap")


def uncovered(grid: dict[str, Any], provenance: dict[tuple[str, str, str], set[str]]) -> list[str]:
    """`locale family target parameter` names no grid row covers (names only)."""
    covered = {
        (loc, r["family"], r["target"], c)
        for r in grid.values()
        for loc in r["locales"]
        for c in r["covers"]
    }
    return sorted(
        f"{loc} {fam} {tgt} {param}"
        for (loc, fam, tgt), params in provenance.items()
        for param in params
        if (loc, fam, tgt, param) not in covered
    )


def stray(grid: dict[str, Any], provenance: dict[tuple[str, str, str], set[str]]) -> list[str]:
    """Rows that name a locale, target or parameter that discovery does not find."""
    out: set[str] = set()
    for r in grid.values():
        for loc in r["locales"]:
            have = provenance.get((loc, r["family"], r["target"]))
            if have is None:
                out.add(f"{loc} {r['family']} {r['target']}")
                continue
            out.update(
                f"{loc} {r['family']} {r['target']} {c}" for c in r["covers"] if c not in have
            )
    return sorted(out)


def grid_row_ok(row: object) -> bool:
    keys = {"family", "target", "method", "locales", "covers", "arguments"}
    if not isinstance(row, dict) or set(row) != keys:
        return False
    texts = all(type(row[k]) is str for k in ("target", "method"))
    lists = all(
        type(row[k]) is list and all(type(x) is str for x in row[k]) for k in ("locales", "covers")
    )
    return texts and lists and row["family"] in FAMILIES and arguments_ok(row["arguments"])
