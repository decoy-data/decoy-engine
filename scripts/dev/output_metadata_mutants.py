"""Mutation runner for the output-metadata choke point (OUTPUT-METADATA-LEAK E1).

Each mutant rewrites one source site, runs the tests that must catch it, restores the file and
checks that it did. Run it against a scratch worktree, never the tree being committed:

    python scripts/dev/output_metadata_mutants.py <worktree> <python> [name-filter ...]

Pattern: the one-at-a-time, restore-and-verify runner of `secret_census_mutants.py`. Prints one
`MUT <name> | RED|GREEN(!) | <summary> | <failing tests>` line per mutant; any GREEN line is a gap.
"""

import hashlib
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
py = sys.argv[2]
only = sys.argv[3:]

FM = "src/decoy_engine/safe_output/_file_metadata.py"
ARROW = "src/decoy_engine/fileaccess/adapters/arrow.py"
SINK = "src/decoy_engine/execution/_transactional_sink.py"
PUB = "src/decoy_engine/publication/_publish.py"
INIT = "src/decoy_engine/__init__.py"
DESC = "src/decoy_engine/_pandas_meta/_descriptors.py"
T_FM = ["tests/unit/safe_output/test_file_metadata.py"]
T_W = ["tests/fileaccess/test_output_writers.py"]
T_S1 = ["tests/sentry/defects/test_output_metadata_choke_point.py"]
T_S1_PATH = T_S1[0]
CANARY = "tests/security/test_output_metadata_canary.py"
RULES = ("is_struct", "is_list", "is_large_list", "is_fixed_size_list", "is_list_view")
RULES += ("is_large_list_view", "is_map", "is_union", "is_dictionary", "is_run_end_encoded")


def rep(old, new):
    def edit(src):
        if old not in src:
            raise SystemExit(f"patch does not apply: {old[:60]!r}")
        return src.replace(old, new, 1)

    return edit


def drop_rule(name):
    """Delete one `_RULES` row (a tuple that starts with the predicate name)."""

    def edit(src):
        m = re.search(rf'^    \(\n?\s*"{name}",', src, re.M)
        if m is None:
            raise SystemExit(f"rule {name} not found")
        nxt = re.compile(r'^(    \(\n? *"is_|\)\n)', re.M).search(src, m.end())
        return src[: m.start()] + src[nxt.start() :]

    return edit


MUTANTS = [
    (
        "AT-M1 strip top-level only",
        FM,
        rep("_type(field.type), nullable", "field.type, nullable"),
        T_FM,
    )
]
MUTANTS += [(f"AT-M1 omit {n} branch", FM, drop_rule(n), T_FM) for n in RULES]
MUTANTS += [
    ("AT-M1 map key not recursed", FM, rep("_field(t.key_field), _field(t.item_field)", "t.key_field, _field(t.item_field)"), T_FM),
    ("AT-M1 map item not recursed", FM, rep("_field(t.key_field), _field(t.item_field)", "_field(t.key_field), t.item_field"), T_FM),
    ("AT-M1 dictionary value not recursed", FM, rep("pa.dictionary(t.index_type, _type(t.value_type), t.ordered)", "pa.dictionary(t.index_type, t.value_type, t.ordered)"), T_FM),
    ("AT-M1 child rebuild without _type (grandchildren)", FM, rep("[_field(t.field(i)) for i in range(t.num_fields)]", "[t.field(i).remove_metadata() for i in range(t.num_fields)]"), T_FM),
    ("H1 delete the extension branch", FM, rep("    if isinstance(t, pa.BaseExtensionType):\n        return _extension(t)\n", ""), [*T_FM, f"{CANARY}::test_route_is_clean[extension_types_publish]"]),
    ("H1 keep every extension", FM, rep("return t if keep and storage.equals", "return t if storage.equals"), T_FM),
    ("H1 skip the pandas parameter check", FM, rep("keep = t.extension_name in _PLAIN_EXTENSIONS and _params_ok(t)", "keep = t.extension_name in _PLAIN_EXTENSIONS"), T_FM),
    ("TZ timestamp zone not checked", FM, rep("return t if t.tz is None or _tz_known(t.tz) else pa.timestamp(t.unit)", "return t"), T_FM),
    ("TZ every zone known", FM, rep("    if not _TZ_SHAPE.fullmatch(tz):\n        return False\n", "    return True\n"), T_FM),
    ("TZ shape check only", FM, rep("    try:\n        pc.assume_timezone(pa.array([0], pa.timestamp(\"s\")), tz)\n    except (pa.ArrowInvalid, pa.ArrowNotImplementedError):\n        return False\n", ""), T_FM),
    ("TZ timestamp branch removed from _type", FM, rep("    if pa.types.is_timestamp(t):\n        return _timestamp(t)\n", ""), T_FM),
    ("TZ interval subtype check and storage comparison both removed", FM, lambda src: rep("            and isinstance(subtype, pa.DataType)\n            and _type(subtype).equals(subtype, check_metadata=True)\n", "")(rep("return t if keep and storage.equals(t.storage_type, check_metadata=True) else storage", "return t if keep else storage")(src)), T_FM),
    ("S1 sentry misses query()", T_S1_PATH, rep('{"execute", "sql", "query", "from_query"}', '{"execute", "sql", "from_query"}'), T_S1),
    ("S1 sentry misses from_query()", T_S1_PATH, rep('{"execute", "sql", "query", "from_query"}', '{"execute", "sql", "query"}'), T_S1),
    ("SUB subset writes raw Arrow", "src/decoy_engine/subset/_materialize.py", rep("arrow_adapter.write_output_table(frame.to_arrow()", "arrow_adapter.write_table(frame.to_arrow()"), [*T_S1, CANARY, "-k", "subset or choke"]),
    ("SUB baseline re-exempts subset", "tests/sentry/baselines/parquet-intermediate-writers.json", rep('    "decoy_engine/vault/_writer.py', '    "decoy_engine/subset/_materialize.py::materialize_subset": {"category": "intermediate", "max": 1, "reason": "reinstated exemption for mutation"},\n    "decoy_engine/vault/_writer.py'), T_S1),
    ("AT-M2 allow PANDAS_ATTRS", FM, rep("    _PANDAS: _sanitize_pandas_blob,\n", '    _PANDAS: _sanitize_pandas_blob,\n    b"PANDAS_ATTRS": lambda raw, schema: raw,\n'), T_FM),
    ("AT-M3 keep attributes", FM, rep('"attributes": {},', '"attributes": source.get("attributes", {}),'), T_FM),
    ("AT-M3 other separators", FM, rep("return json.dumps(blob).encode()", 'return json.dumps(blob, separators=(",", ":")).encode()'), T_FM),
    ("AT-M3 from_arrays instead of cast", FM, rep("else table.cast(target)", "else pa.Table.from_arrays(table.columns, schema=target)"), T_FM + T_W),
    ("AT-M4 copy any numpy_type", FM, rep("kind, numpy = pair if pair in pairs else pairs[0]", "kind, numpy = pair if pair else pairs[0]"), T_FM),
    ("AT-M4 copy column metadata", FM, rep('"metadata": column_metadata(field.type),', '"metadata": next((e.get("metadata") for e in source.get("columns", []) if isinstance(e, dict) and e.get("field_name") == field.name), column_metadata(field.type)),'), T_FM),
    ("AT-M4 copy pandas_version", FM, rep('"pandas_version": version,', '"pandas_version": source.get("pandas_version", version),'), T_FM),
    ("AT-M4 copy creator", FM, rep('"creator": {"library": "pyarrow", "version": pa.__version__},', '"creator": source.get("creator", {"library": "pyarrow", "version": pa.__version__}),'), T_FM),
    ("AT-M4 accept non-object top level", FM, rep("if not isinstance(source, dict) or version is None:", "if version is None:"), T_FM),
    ("AT-M5 keep range-index objects", FM, rep("[c for c in dict.fromkeys(c for c in stored if isinstance(c, str)) if c in entries]", "[c for c in stored if (isinstance(c, str) and c in entries) or isinstance(c, dict)]"), T_FM),
    ("H2 remove the index filter", FM, rep("if c in entries]", "]"), T_FM),
    ("H2 keep duplicate index entries", FM, rep("dict.fromkeys(c for c in stored if isinstance(c, str))", "(c for c in stored if isinstance(c, str))"), T_FM),
    ("L3 drop the real index name", FM, rep("return real if isinstance(real, str) and real in names and real != field else None", "return None"), T_FM),
    ("AT-M6 writer from raw schema", ARROW, rep("parquet_writer(txn, component, output_schema(schema))", "parquet_writer(txn, component, schema)"), T_W + T_S1),
    ("AT-M6 write_output_table skips output_table", ARROW, rep("write_table(output_table(table), txn, component)", "write_table(table, txn, component)"), T_W + T_S1),
    ("AT-S1 StagedParquetWriter.write raw adapter", SINK, rep("arrow_adapter.write_output_table(data, txn, component)", "arrow_adapter.write_table(data, txn, component)"), [*T_S1, CANARY, "-k", "sequential or choke"]),
    ("AT-S1 StagedParquetWriter.write_batches raw adapter", SINK, rep("arrow_adapter.output_parquet_writer(txn, component, schema)", "arrow_adapter.parquet_writer(txn, component, schema)"), [*T_S1, CANARY, "-k", "out_of_core_fk or choke"]),
    ("AT-S1 writer passed to a wrapper (reference)", SINK, rep("arrow_adapter.write_output_table(data, txn, component)", "guarded(1, 2, arrow_adapter.write_table, data, txn, component)"), T_S1),
    ("AT-E1 publish_tables raw adapter", PUB, rep("arrow_adapter.write_output_table(tables[name], txn, component)", "arrow_adapter.write_table(tables[name], txn, component)"), [*T_S1, CANARY, "-k", "publish_unit or choke"]),
    ("AT-P1 drop output_table export", INIT, rep('    "output_table",\n    "parse_pipeline_config",', '    "parse_pipeline_config",'), ["tests/unit/test_public_api.py::test_all_lists_every_public_name"]),
    ("AT-R1 change admission int64 pair", DESC, rep('pa.int64(): ("int64", "int64"),', 'pa.int64(): ("int64", "int32"),'), ["tests/unit/execution/native/test_admission_descriptor_parity.py", "tests/unit/pandas_meta"]),
]  # fmt: skip

for name, rel, edit, tests in MUTANTS:
    if only and not any(o in name for o in only):
        continue
    path = root / rel
    orig = path.read_bytes()
    try:
        path.write_text(edit(orig.decode()))
        run = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                py,
                "-m",
                "pytest",
                *tests,
                "-q",
                "-p",
                "no:cacheprovider",
                "--no-header",
                "--tb=no",
                "-rfE",
            ],
            capture_output=True,
            text=True,
            cwd=root,
        )
    finally:
        path.write_bytes(orig)
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(orig).digest():
        raise SystemExit(f"{rel} was not restored")
    reds = [
        ln.split(" - ")[0].split("::", 1)[-1]
        for ln in run.stdout.splitlines()
        if ln.startswith(("FAILED", "ERROR"))
    ]
    last = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    verdict = "RED" if run.returncode != 0 else "GREEN(!)"
    print("MUT", name, "|", verdict, "|", last, "|", "; ".join(reds)[:400], flush=True)
print("DONE")
