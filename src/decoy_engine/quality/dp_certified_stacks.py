"""The certified DP lock fingerprints, one set per CPython patch, and nothing else.

Release prep (`scripts/release/stamp_release.py`, through `scripts/release/dp_rows.py`) adds rows to
this file every release and never removes one, so it is kept apart from the gate logic in
`dp_provenance.py`: that module stays a fixed size and this one carries only data. The sets must
stay checked-in literals, never values computed at import time (see `dp_provenance`, "The STATIC
certified manifest"). `dp_provenance._CERTIFIED_STACKS` keys these sets by the certified platform.
"""

from __future__ import annotations

CERTIFIED_ROWS: dict[str, frozenset[str]] = {
    "3.10.20.final": frozenset(
        {
            # decoy-engine dev/CI profile (`uv sync --frozen --extra dev --extra lint --extra vault
            # --extra cloud`, Python 3.10.20). Re-pin from a fresh sync (installed_distribution_set,
            # compute_lock_fingerprint). A stamp moves only the engine version; old snapshots stay.
            "ecfe28a04fb5a65d4bc7a9c00ba51d2df642e30148e2f45a8702e6767120d48c",
            "9663ac0b8ad7dfef3d635a8d3f848722169209fd03c293af4a7b453cfbcb3204",
            "bd14c8a5cc2d3896547f743150fdf35d340c1f2e95e923dcba6c00065bb53cfd",
            "de716a40f24aec0d103467665b0a2cd4a9eaa4682e581c2907a7e732218363e2",
            "376aa20958b1df452478752ec08a5634adfafc4b80fcaeef01c69869b1aad87d",
            "8e4bb9802809c624b81bac40e84ecd660c6e54e39fb2b80a6920789128d89d6e",
            "b2d12cff2b9b1cb32a7fdd14227befe5b7767a389de47a8d1b3ebd70822c9be1",
            "0a373cf26022ec43eb0cb60f89026d9e5878471110b7263f5c28d4bde2fc4897",
            "0e2e91aab6ea145c7531ff0068f05097068c8e56c0ba9a69cfcc1fd4a5d5e6bd",
            "decae234fdd19a744ec2eea4da4b42c906359400b6eda07e475cfcc321a92f5c",
            "9dba072fe68a9047392848f3a0eaac3dedcdf496beda7965c10059b868a9fc00",
            "883833b50ebe1262aff8afcfb4c92a577b18541c03636185b903748ec83351b3",
            "f921d069fb3cd5baebc6940de37076103ba6a663c977db346c81fd6cdcbfc326",
            "044f8c7b26dfaac7e0bc3973ee3a355e64379ede67a596410aceed74acf6c366",
            "bdec8dd8c27cfa533b9cea788c7254b66957977f9670c7004a4dc90028929224",
            "e738e729ab9d2ad7710ab51cb774adb274ffa3256cf4c4ef4cea1fcbd1790b44",
            "5253dc7923b3bbe72ca7866460aa3d556735851ffb304534834c7103fd665950",
            "fcf186c32c5dd41eba586238760f12c481171e908082dbc31d3295b387be7cf0",
            "4560f601e6f299e4c586ce9d795dbaea8e14ac5dc8b5d0e1310b57913e25eac9",
            "176aff0bf8727f2fe64e0bddd4febb487aeaa05daa97547143ec6cc4230200cc",
            "78af2b5a1bb11c826f1d3918f705dc7edada72a081804e74d55e37938d8300b6",
            "7d1c1a2a2be450a59fa17d810663a7bfe5e825204cca99bfe039ba12b6226aed",
            "b9b42047dc09ce89593e0be2dc6f7125a91af661bbb644b3a27342c84fd44ab0",
            "31ecf94503eff107631191426072eee757af72a2229ab594d2fc2e8e6bfac7b1",
            "5a76ea92769d62cb0124d89d24c2ec0e4116828e34e0611d80bf5e36edef1a23",
            "502037cad62e1e645a666eb088b0bc9f69fec82d2ac980b0c2d52a2cc707a7f1",
            "c12baeadc1c64e00df81c3d359ec58eaeef24a7d62a02c2d31098c37bfaa5241",
            "f9708482fe4f95139ce9a1272f0110b38b8de83e8d2a567cca5b5f7c1f1ad2bf",
            # decoy-cli pristine RUNTIME profile: engine + CLI (typer/rich/duckdb) + the DP closure, no dev
            # tooling, pinned in the CLI repo's requirements-certified.txt (reproduce: `--no-dev` install on
            # 3.10.20, then cert_smoke.py). All stay, newest first; 0.28.0 lacks joserfc.
            "4a1765c991568cd68b07a079d5f85b897df0b50251c2106eb11d1af08671bda1",
            "a4aad6c7f862083285736bdac3e176baff40b382439429e7abd2c46ec615acaf",
            "228ed71e6f0a6ba9d62c25abeff6e668a53a8851d68e313a2f946367b33d631a",
            "44aaa90fef509a80a7c3def099592c6c4326d47d8bbf79d9043171f8e3a61ba9",
            "b61dcfd6431f18667d85921b8aa71a78ccc92ebff0dfd46c76b8e04c4bd17c02",
            "00f45dee9db696a2951d0a66e4fb67e7918008682dfb00d966ef2faebc804d5c",
            "e7b15fa4f275ef7f7d981a6a84298015423182848ca29bfb11995fdcae3fc092",
            "c479d1def48ac303249d4917cc1baf49fa640adad05824d3512329d93be4420e",
            "789b1eae03d7cd382f34e704aa510d1b9559178223f4d170fffd20f724de2e9f",
            "dceac0cd1161a28d6c2c949cf88531d08ad5348c0d460f9bc44f83d02818dee3",
            "c80550ef3c56387ba81dd1a9ff709cb24a7ee7b55d607a01a43613a8a550045a",
            "620a48a5b979d483aa3522900590c4fe5a376aeb9cedbd16a415639522c1204b",
            "73acf493827ce8dbd72c6da486eb4f30e72a66cf7abb90b0127cef3e14f75eec",
            "1db3e3daf52c2b3944393f8a90e98d7519f50540191c6aefc9a987d097a2998f",
            "d5898d1ff084203f455907d8648e59e0156e320d0e5a12ba1e22aeba8ad6675d",
            "aa038ddd1d2e783042e34c75c313921f19b8e1dc580559cf8d5081ed19ea11e1",
            "725f80a30807dee263ee9404c05829d4947870b2600ab0a165c0fa7951b91268",
            "795732eb0808001d9c4591f3693637187637bb383a87b8caa95b8f2f269f9211",
            "b643894ded2ab84c4a0a9d9032a1de3d2330db89161f231e509024428b7533f3",
            "a7b40d54f68488ecbcc253c35a03517eefc456625a9b0240470e765e2bbc4476",
        }
    ),
}
