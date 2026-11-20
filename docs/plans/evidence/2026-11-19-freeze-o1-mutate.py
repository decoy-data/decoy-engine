"""Apply one named O1 mutation in place (inside a throwaway snapshot). Usage: mutate.py <name>"""

import sys
from pathlib import Path

E = Path("src/decoy_engine/execution")
M = {
    # name: (file, old, new)
    "skip_object_path": (
        E / "_when_gate.py",
        "    if wide:\n        obj = pd.Series(",
        "    if False:\n        obj = pd.Series(",
    ),
    "drop_literal_check": (
        E / "_when_gate.py",
        "wide = wide_col or any(isinstance(x, int) and abs(x) > _EXACT_FLOAT_INT for x in nums)",
        "wide = wide_col",
    ),
    "drop_value_check": (
        E / "_when_gate.py",
        "wide = {c: _is_wide(pdf[c]) for c in ints}",
        "wide = {c: False for c in ints}",
    ),
    "float_bound_rounds_down": (E / "_when_gate.py", '(">=", floor + 1)', '(">=", floor)'),
    "non_integral_ne_false": (
        E / "_when_gate.py",
        '        if op == "!=":\n            return True',
        '        if op == "!=":\n            return False',
    ),
    "blank_never_selected": (E / "_when_gate.py", 'null_out = op == "!="', "null_out = False"),
    "float_copy_returns": (E / "_when_gate.py", "    if not ints or any(", "    if True or any("),
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
