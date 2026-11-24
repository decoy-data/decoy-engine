"""SOURCE-READ-BOUNDARY S1b-1: no Arrow-to-pandas conversion or pandas file read outside the
choke point (`internal/pandas_compat.py` `arrow_to_frame` and `arrow_to_series`), except the
counted sites in `allowlist.toml`. A bare conversion lets pandas' value-quoting error escape."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.sentry.source_read._scan import package_path, problems, scan_source, scan_tree

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

_ALLOWLIST = tomllib.loads((Path(__file__).parent / "allowlist.toml").read_text(encoding="utf-8"))
# The count on origin/main 4bc582d0a. Lower it with the diff that removes a site; never raise it.
_MAX_AT_BASE = 7
_ALLOWED = Counter(
    {(a["path"], a["function"], a["target"]): a["count"] for a in _ALLOWLIST["allowed"]}
)


def test_the_tree_matches_the_allowlist_exactly() -> None:
    assert problems(scan_tree(), _ALLOWED) == []


def test_the_ratchet_only_goes_down() -> None:
    assert sum(_ALLOWED.values()) == _ALLOWLIST["ratchet_count"] <= _MAX_AT_BASE
    assert all(a["reason"] for a in _ALLOWLIST["allowed"])


_SEEDS = {
    "plain": "def f(t):\n    return t.to_pandas()\n",
    "keyword": "def f(t, m):\n    return t.to_pandas(types_mapper=m)\n",
    "unbound": "import pyarrow as pa\n\ndef f(t):\n    return pa.Table.to_pandas(t)\n",
    "as a value": "import pyarrow as pa\n\ndef f(ts):\n    return list(map(pa.Table.to_pandas, ts))\n",
    "module alias": "import pandas as p\n\ndef f(x):\n    return p.read_parquet(x)\n",
    "from import": "from pandas import read_parquet as rp\n\ndef f(x):\n    return rp(x)\n",
    "as an argument": "import pandas as pd\n\ndef f(g):\n    return g(fn=pd.read_parquet)\n",
    "nested module": "import pandas as pd\n\ndef f(x):\n    return pd.io.parquet.read_parquet(x)\n",
    "adapter": (
        "from decoy_engine.fileaccess.adapters import pandas as pa_\n\n"
        "def f(h):\n    return pa_.read_parquet(h)\n"
    ),
    "relative adapter": "from ..fileaccess.adapters.pandas import read_parquet\n\n"
    "def f(h):\n    return read_parquet(h)\n",
}


@pytest.mark.parametrize("name", sorted(_SEEDS))
def test_each_seeded_spelling_is_a_site(name: str) -> None:
    assert scan_source(_SEEDS[name], "execution/_seed.py"), name


def test_a_second_function_in_the_choke_point_module_is_a_site() -> None:
    source = "def arrow_to_frame(t):\n    return t.to_pandas()\n\ndef other(t):\n    return t.to_pandas()\n"
    assert [h.function for h in scan_source(source, "internal/pandas_compat.py")] == ["other"]


def _after_restoring(relpath: str, routed: str, bare: str) -> list[str]:
    """The tree's problems once `routed` in one real module is put back to `bare`."""
    text = package_path(relpath).read_text(encoding="utf-8")
    assert routed in text, f"{relpath} no longer holds the routed call"
    others = [h for h in scan_tree() if h.path != relpath]
    return problems([*others, *scan_source(text.replace(routed, bare, 1), relpath)], _ALLOWED)


_ROUTED = (
    (
        "execution/_chunked_profile.py",
        "arrow_to_frame(table, on_unrepresentable=source_column_unrepresentable(table_name))",
        "table.to_pandas()",
    ),
    (
        "profile/_cloud_readers.py",
        "table = pq.read_table(io.BytesIO(_s3_full(client, self._bucket, self._key)))\n"
        "        return arrow_to_frame(table, on_unrepresentable=source_column_unrepresentable())",
        "return pd.read_parquet(io.BytesIO(_s3_full(client, self._bucket, self._key)))",
    ),
    (
        "profile/_cloud_readers.py",
        "table = pq.read_table(io.BytesIO(data))\n"
        "        return arrow_to_frame(table, on_unrepresentable=source_column_unrepresentable())",
        "return pd.read_parquet(io.BytesIO(data))",
    ),
    (
        "execution/pipeline/_post_scan.py",
        "arrow_to_frame_pair(\n",
        "(lambda s, o, on_unrepresentable: (s.to_pandas(), o.to_pandas()))(\n",
    ),
)


@pytest.mark.parametrize("case", _ROUTED, ids=["walk_one_table", "s3", "gcs", "post_scan"])
def test_restoring_a_bare_read_at_a_routed_site_fails(case: tuple[str, str, str]) -> None:
    assert _after_restoring(*case)
