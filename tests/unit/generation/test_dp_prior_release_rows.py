"""A release re-pin adds certified rows; it never retires a prior release's rows.

The certified fingerprint hashes the installed distribution set, which includes the
engine's own version string, so every release bump moves it with no proof-critical
library change. A snapshot fit under 0.17.0 records the 0.17.0 rows; replacing them
made every such snapshot fail plan compilation with `dp_snapshot_provenance_uncertified`.
"""

from __future__ import annotations

import pytest

from decoy_engine.plan import compile_plan
from decoy_engine.quality import dp_provenance as prov
from tests.unit.generation.test_generate_dp_contract import (
    _cfg_with_artifact,
    _numeric_dp_artifact,
    _profile,
)

# The two rows v0.17.0 certified (engine dev/CI profile, decoy-cli runtime profile).
_V0_17_0_ROWS = (
    "5a76ea92769d62cb0124d89d24c2ec0e4116828e34e0611d80bf5e36edef1a23",
    "a7b40d54f68488ecbcc253c35a03517eefc456625a9b0240470e765e2bbc4476",
)
# The two rows v0.18.0 certified.
_V0_18_0_ROWS = (
    "31ecf94503eff107631191426072eee757af72a2229ab594d2fc2e8e6bfac7b1",
    "b643894ded2ab84c4a0a9d9032a1de3d2330db89161f231e509024428b7533f3",
)
# The two rows v0.19.0 certified (docs/records/release-r0190-facts.md).
_V0_19_0_ROWS = (
    "7d1c1a2a2be450a59fa17d810663a7bfe5e825204cca99bfe039ba12b6226aed",
    "795732eb0808001d9c4591f3693637187637bb383a87b8caa95b8f2f269f9211",
)
# The engine dev/CI profile on 0.19.0 once pytest-xdist joined `dev` (79 dists; ENGINE-PAR P2).
_XDIST_DEV_ROW = "78af2b5a1bb11c826f1d3918f705dc7edada72a081804e74d55e37938d8300b6"
# The two rows v0.20.0 certified: the xdist lock with the engine at 0.20.0, and the CLI runtime
# profile on engine 0.20.0.
_V0_20_0_ROWS = (
    "176aff0bf8727f2fe64e0bddd4febb487aeaa05daa97547143ec6cc4230200cc",
    "725f80a30807dee263ee9404c05829d4947870b2600ab0a165c0fa7951b91268",
)
# The two rows v0.21.0 certified: the dev/CI lock with the engine at 0.21.0, and the CLI runtime
# profile on engine 0.21.0.
_V0_21_0_ROWS = (
    "4560f601e6f299e4c586ce9d795dbaea8e14ac5dc8b5d0e1310b57913e25eac9",
    "aa038ddd1d2e783042e34c75c313921f19b8e1dc580559cf8d5081ed19ea11e1",
)
# The two rows v0.22.0 certified: the dev/CI lock with the engine at 0.22.0, and the CLI runtime
# profile on engine 0.22.0.
_V0_22_0_ROWS = (
    "fcf186c32c5dd41eba586238760f12c481171e908082dbc31d3295b387be7cf0",
    "d5898d1ff084203f455907d8648e59e0156e320d0e5a12ba1e22aeba8ad6675d",
)
# The two rows v0.23.0 certified: the dev/CI lock with the engine at 0.23.0, and the CLI
# runtime profile (with the classifier stack) on engine 0.23.0.
_V0_23_0_ROWS = (
    "bdec8dd8c27cfa533b9cea788c7254b66957977f9670c7004a4dc90028929224",
    "73acf493827ce8dbd72c6da486eb4f30e72a66cf7abb90b0127cef3e14f75eec",
)
# The two rows v0.24.0 certified: the dev/CI lock with the engine at 0.24.0, and the CLI
# runtime profile on engine 0.24.0.
_V0_24_0_ROWS = (
    "044f8c7b26dfaac7e0bc3973ee3a355e64379ede67a596410aceed74acf6c366",
    "620a48a5b979d483aa3522900590c4fe5a376aeb9cedbd16a415639522c1204b",
)
# The two rows v0.25.0 certified: the dev/CI lock with the engine at 0.25.0, and the CLI
# runtime profile on engine 0.25.0.
_V0_25_0_ROWS = (
    "f921d069fb3cd5baebc6940de37076103ba6a663c977db346c81fd6cdcbfc326",
    "c80550ef3c56387ba81dd1a9ff709cb24a7ee7b55d607a01a43613a8a550045a",
)
# The two rows v0.26.0 certified: the dev/CI lock with the engine at 0.26.0, and the CLI
# runtime profile on engine 0.26.0.
_V0_26_0_ROWS = (
    "883833b50ebe1262aff8afcfb4c92a577b18541c03636185b903748ec83351b3",
    "dceac0cd1161a28d6c2c949cf88531d08ad5348c0d460f9bc44f83d02818dee3",
)
# The two rows v0.27.0 certified: the dev/CI lock with the engine at 0.27.0, and the CLI
# runtime profile on engine 0.27.0.
_V0_27_0_ROWS = (
    "9dba072fe68a9047392848f3a0eaac3dedcdf496beda7965c10059b868a9fc00",
    "789b1eae03d7cd382f34e704aa510d1b9559178223f4d170fffd20f724de2e9f",
)
# The three rows this release certifies: the dev/CI lock with the engine at 0.28.0, the CLI
# runtime profile on engine 0.28.0, and row F (that profile with certifi 2026.10.18, cryptography
# 50.0.0, pyasn1 0.6.5 and urllib3 2.8.0, roadmap row 24zc).
_V0_28_0_ROWS = (
    "0e2e91aab6ea145c7531ff0068f05097068c8e56c0ba9a69cfcc1fd4a5d5e6bd",
    "e7b15fa4f275ef7f7d981a6a84298015423182848ca29bfb11995fdcae3fc092",
    "c479d1def48ac303249d4917cc1baf49fa640adad05824d3512329d93be4420e",
)
_ALL_ROWS = (
    _V0_17_0_ROWS
    + _V0_18_0_ROWS
    + _V0_19_0_ROWS
    + (_XDIST_DEV_ROW,)
    + _V0_20_0_ROWS
    + _V0_21_0_ROWS
    + _V0_22_0_ROWS
    + _V0_23_0_ROWS
    + _V0_24_0_ROWS
    + _V0_25_0_ROWS
    + _V0_26_0_ROWS
    + _V0_27_0_ROWS
    + _V0_28_0_ROWS
)


@pytest.mark.parametrize("fingerprint", _ALL_ROWS)
def test_a_snapshot_recording_a_released_row_compiles(tmp_path, fingerprint: str) -> None:
    artifact = _numeric_dp_artifact(epsilon_total=0.5)
    artifact["dp"]["provenance"]["fingerprint"] = fingerprint
    cfg, _ = _cfg_with_artifact(tmp_path, artifact)
    plan = compile_plan(cfg, _profile(), decoy_engine_version="test")
    assert plan is not None


@pytest.mark.parametrize("fingerprint", _ALL_ROWS)
def test_recorded_provenance_admits_every_released_row(fingerprint: str) -> None:
    (plat, cpython), _ = next(iter(prov._CERTIFIED_STACKS.items()))
    prov.validate_recorded_provenance(
        {"platform": dict(plat._asdict()), "cpython": cpython, "fingerprint": fingerprint}
    )
