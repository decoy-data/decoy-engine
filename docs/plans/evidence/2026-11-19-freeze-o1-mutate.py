"""Apply one named O1 mutation in place (inside a throwaway snapshot). Usage: mutate.py <name>"""

import sys
from pathlib import Path

E = Path("src/decoy_engine/execution")
M = {
    # name: (file, old, new)
    "skip_object_path": (
        E / "_when_gate.py",
        "    if wide:\n        values = col.to_numpy(dtype=object",
        "    if False:\n        values = col.to_numpy(dtype=object",
    ),
    "drop_literal_check": (
        E / "_when_gate.py",
        "        isinstance(x, float) or (isinstance(x, int) and abs(x) > _EXACT_FLOAT_INT)\n        for x in literals",
        "        False\n        for x in literals",
    ),
    "drop_value_check": (
        E / "_when_gate.py",
        "        wide = low is not pd.NA and (int(low) < -_EXACT_FLOAT_INT or int(high) > _EXACT_FLOAT_INT)",
        "        wide = wide",
    ),
    "float_literal_not_object": (
        E / "_when_gate.py",
        "isinstance(x, float) or (isinstance(x, int)",
        "(isinstance(x, int)",
    ),
    "restore_pd_na": (
        E / "_when_gate.py",
        "    if not pd.api.types.is_integer_dtype(col.dtype):\n        return col\n",
        "    if not pd.api.types.is_integer_dtype(col.dtype) or not isinstance(col.dtype, np.dtype):\n        return col\n",
    ),
    "drop_fk": (
        E / "_fk_keys.py",
        "            exact[table] = exact.get(table, set()) | fk_columns_for_table(graph.edges, table)",
        "            exact[table] = exact.get(table, set())",
    ),
    "drop_anchor": (
        E / "_fk_keys.py",
        "        source_anchor_columns(plan, registry),\n",
        "        {},\n",
    ),
    "drop_top_code": (
        E / "_fk_keys.py",
        "        top_code_columns(plan, registry),\n",
        "        {},\n",
    ),
    "drop_group_key": (
        E / "_fk_keys.py",
        "        group_key_group_by_columns(plan, registry),\n",
        "        {},\n",
    ),
    "drop_declared": (
        E / "_fk_keys.py",
        "        declared_integer_columns(plan),\n",
        "        {},\n",
    ),
    "drop_when_read": (
        E / "_fk_keys.py",
        "    when_read = _when_read_columns(\n        (table, ((n, seed.when) for n, seed in table_seed.per_column))",
        "    when_read = _when_read_columns(\n        (table, ())  # mutated\n        if True else (table, ((n, seed.when) for n, seed in table_seed.per_column))",
    ),
    "set_by_hand": (
        E / "_chunked_carry.py",
        "    return lossless_int_columns(plan, registry, graph).for_table(table)",
        "    from decoy_engine.execution._fk_keys import fk_columns_for_table\n\n    return set(fk_columns_for_table(graph.edges, table))",
    ),
    "new_caller": (
        E / "_runner.py",
        "def group_by_sibling(",
        "def _extra_ingest(t):\n    from decoy_engine.execution._fk_keys import to_pandas_fk_safe\n\n    return to_pandas_fk_safe(t, set())\n\n\ndef group_by_sibling(",
    ),
    "group_by_sibling_none": (
        E / "_runner.py",
        '    group_by = (provider_config or {}).get("group_by")\n    return group_by if isinstance(group_by, str) and group_by else None',
        "    return None",
    ),
}
name = sys.argv[1]
f, old, new = M[name]
t = f.read_text()
if t.count(old) != 1:
    raise SystemExit(f"mutation {name}: pattern found {t.count(old)} times")
f.write_text(t.replace(old, new))
print("mutated", name, f)
