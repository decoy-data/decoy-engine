"""Pins the DRAW_SITES catalogue byte for byte.

Determinism depends on the catalogue's exact contents AND order (providers and
the coverage maps index into it). The digests below were captured from the
catalogue before it was split into per-family data modules: the whole tuple's
repr, each element's repr, the ordered ids, and the coverage maps. Any edit to
an entry, a reordering, or a dropped/duplicated site fails here.
"""

from __future__ import annotations

import hashlib

from decoy_engine.execution.native import _determinism_protocol as protocol


def _digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def test_catalogue_length_and_order_are_unchanged() -> None:
    assert len(protocol.DRAW_SITES) == len(_ORDERED_IDS) == 42
    assert [site.draw_site_id for site in protocol.DRAW_SITES] == _ORDERED_IDS


def test_catalogue_repr_is_byte_identical() -> None:
    assert _digest(protocol.DRAW_SITES) == _CATALOGUE_DIGEST


def test_each_entry_is_byte_identical() -> None:
    assert [_digest(site) for site in protocol.DRAW_SITES] == _ENTRY_DIGESTS


def test_coverage_maps_and_enums_are_unchanged() -> None:
    assert _digest(protocol.MASK_STRATEGY_TO_SITE) == _MAP_DIGESTS["MASK_STRATEGY_TO_SITE"]
    assert _digest(protocol.GEN_KIND_TO_SITE) == _MAP_DIGESTS["GEN_KIND_TO_SITE"]
    assert _digest(protocol.PROVIDER_IDENTIFIER_SITES) == _MAP_DIGESTS["PROVIDER_IDENTIFIER_SITES"]
    assert _digest(sorted(protocol.FAMILIES)) == _MAP_DIGESTS["FAMILIES"]
    assert _digest(sorted(protocol.ENTROPY_ROOTS)) == _MAP_DIGESTS["ENTROPY_ROOTS"]
    assert _digest(sorted(protocol.IDENTITIES)) == _MAP_DIGESTS["IDENTITIES"]
    assert _digest(protocol.DETERMINISTIC_NO_DRAW) == _MAP_DIGESTS["DETERMINISTIC_NO_DRAW"]


def test_lookup_by_id_returns_the_catalogued_entry() -> None:
    for site in protocol.DRAW_SITES:
        assert protocol.draw_site_by_id(site.draw_site_id) is site


# Re-pinned at the GEN-C1 main merge: carries the shuffle and derive_context re-pins plus the moved gen call sites.
# Re-pinned 2026-11-09: gen.reference records the fitted fan-out shuffles on its stream.
# Re-pinned 2026-11-09: gen.statistical_per_row records the fitted cell format draws.
# Re-pinned for GEN-WINDOWED-BATCH S2: mask.windowed_date draws from the keyed index kernel (family, derivation,
# call site, provider version, notes).
# Re-pinned for FK-FANOUT E2b: gen.reference call site and fingerprint source.
# Re-pinned for GEN-NUM-SHAPE: gen.statistical_per_row call shape text.
# Re-pinned for GEN-UNIQUE E2: four unique-draw sites, the moved synthesize.py call sites, and the shared attempt limit.
# Re-pinned for GEN-TYPES E1: gen.distribution appended at the end of the catalogue.
# Re-pinned for GEN-TYPES E3: gen.lookup appended after gen.distribution.
# Re-pinned for B-6: mask.tokenize derives under the vault-scoped subkey (call site moved).
# Re-pinned for DUP-FREEZE E2: two joint_mask stream sites after mask.joint_mask_keyed_row, and the
# gen.composite_build_pool seed text names resolve_seed. MASK_STRATEGY_TO_SITE maps each strategy to
# one site, so its digest does not move.
# Re-pinned for row 24zb: mask.date_shift metadata (call site, seed text, notes) only.
# Re-pinned at the GEN-REL E1 main merge: carries row 24zb's mask.date_shift and gen.reference.
# Re-pinned at the GEN-REL E2 main merge: carries row 24zb's mask.date_shift and this slice's re-pin.
# Re-pinned for row 24ze G1: every call_site and mirror_call_sites entry is now `path::function[#n]`
# instead of `path:line`. Metadata only: the output-bearing digests below stay byte-identical.
# Re-pinned at the GEN-INHERIT E2 main merge: row 24ze G1's form plus GEN-REL's gen.reference sites.
# Re-pinned at the GEN-INHERIT E2 merge of GEN-REL E3b: gen.reference sites after the E3b merge.
# Re-pinned for GEN-REL E1: gen.reference notes and mirror call sites name the moved cardinality repair.
# Re-pinned for GEN-REL E2: gen.reference notes and mirror call sites name the self-reference tree draw.
# Re-pinned for E-F0: only the mask.text_mask_date_shift entry moves (an unparseable span now becomes
# the redaction token, not its real text), and with it the catalogue digest.
# Re-pinned at the GEN-REL E2 main merge: both changes together.
# Re-pinned at the GEN-INHERIT E2 main merge: the E-F0 date-shift entry joins the GEN-REL sites.
# Re-pinned for GEN-WINDOWED-BATCH S2 at the main merge: the windowed_date draw sites moved too.
_CATALOGUE_DIGEST = "4cc3254a9c2ebce984ea0aed98259bba482b356a8ede94d421c1bf98efc18469"

_ORDERED_IDS = [
    "mask.shuffle",
    "mask.hash",
    "mask.categorical_deterministic",
    "mask.categorical_nondeterministic",
    "mask.fpe",
    "mask.date_shift",
    "mask.bucket_perturb",
    "mask.group_key",
    "mask.code_set",
    "mask.joint_mask_keyed_row",
    "mask.joint_mask_null_fallback",
    "mask.joint_mask_gen_row",
    "mask.text_mask_date_shift",
    "mask.text_mask_faker",
    "mask.grouped_series_monotone_walk",
    "mask.windowed_date",
    "gen.faker_per_row",
    "gen.categorical",
    "gen.reference",
    "gen.formula_per_row",
    "gen.statistical_per_row",
    "gen.null_probability",
    "gen.distribution_snapshot",
    "gen.pool_deterministic",
    "gen.pool_nondeterministic",
    "gen.composite_build_pool",
    "gen.faker_unique_retry",
    "gen.categorical_unique",
    "gen.reference_unique",
    "gen.unique_pair",
    "mask.faker",
    "gen.pool_build_faker",
    "gen.identifier_deterministic",
    "gen.identifier_nondeterministic",
    "gen.derive_context",
    "mask.formula",
    "gen.faker_pool_build",
    "gen.faker_pool_selection",
    "mask.faker_nondeterministic",
    "mask.tokenize",
    "gen.distribution",
    "gen.lookup",
]

_ENTRY_DIGESTS = [
    "e20e8ee9afc564f34870205cabb2d7ce4da58b391e4d8c5cc754a77eca2185bf",  # mask.shuffle
    "46f06d1dbc4e5d0fbdb0eeac203fbdba6d6d157c9b4b46f0971f48d66a284e5a",  # mask.hash
    "bd06bcb22c55f7423682660accf32079fce98bc13403eb3f1111aeabcc764b70",  # mask.categorical_deterministic
    "9aa436b5ecf26021ee8649c0ea47eec71f92064699828e183046db70d0f66412",  # mask.categorical_nondeterministic
    "1250c6e03f61cdc000a73f7f8f76088402fb6f5407e40d8a31e58052130bc571",  # mask.fpe
    "28a6b8a9a742bab28c5bbcea40da447b80719c66f8961a1a24735b955559d0fc",  # mask.date_shift
    "cf19b2a7dc1493488a94dbedc1b93847dfabd350632c42e444ca53da16a02292",  # mask.bucket_perturb
    "be0d33334a0efdd646507ec6e9f691a8c268785af8764f079e1a84c6377c75de",  # mask.group_key
    "33bb9e2c0f66453881e672d9e2923c811b778adc597d1974fbb10bee4263cd2d",  # mask.code_set
    "dfa795f581a81ffc81d668aac8669215dd62c577df7cdf3be702a317b31ea758",  # mask.joint_mask_keyed_row
    "71a6ecef1fb21899f869296e386b309004f2760a90ed24deb3c0b217c7385681",  # mask.joint_mask_null_fallback
    "ded3f195ad06b5b96de97035e9386102fbcacd718b699a7a3a6256915a53d1e8",  # mask.joint_mask_gen_row
    "05c78dbb9a24f8e6e60a356b45ca143b4f33af8f60638689a2ca92fd306ac65b",  # mask.text_mask_date_shift
    "568b337638c888c7dfd5cc616c5924d9827319202d43382ea821a884efe401c4",  # mask.text_mask_faker
    "2c7733e97f6e0dab2366a8d80b147025b26b19cf8c358fe51a0e815683476efc",  # mask.grouped_series_monotone_walk
    "be681b808e8b20697ba82f1eca89d9b9e9973bb56c16fa54de62c35bdc5b664b",  # mask.windowed_date
    "b22ab37e973ad02b943c741bf53e598e9e213a56df6e184144ad95adeca516fd",  # gen.faker_per_row
    "c26b56c364cecf593b15abddab6bb7a4ca9ada7a578b0748f714e4637cd4c7fa",  # gen.categorical
    # gen.reference carries GEN-REL E1/E2 (relational repair, self-reference) in path::function form.
    "d708861d65e4f7efd8c6b39464a1200a8e2158e1c7b5862f7bbf40a84bbafe4e",  # gen.reference
    "8b47094cdc123d559a1b924657ac2d84aa012ed0d92fe1a4030b763b04c55f1c",  # gen.formula_per_row
    "8eee3a31f0bf72952a59e8528cecfda9a4d05e97b123e382b2cab08c76c1e1b9",  # gen.statistical_per_row
    "c5a8c289a8a94d363e365084d2148580330cdccdc27d4144bc983f482ddaab17",  # gen.null_probability
    "fc5e96755c56b1f7e9ce4aa51d224dd3f3b0902e7ba55255f6c877dec13e5d35",  # gen.distribution_snapshot
    "ee9e6455a43a920d72e77cf6f7c843a86912152573ffde62a8652c98ec19d876",  # gen.pool_deterministic
    "64a2a8b88ba7657a760d89c136230a79182a89ef1cfd99b088cd13fc5c69f9ac",  # gen.pool_nondeterministic
    "5508629296e713d4cda31e2cefe194f311df6be2ae5a65347b28e87d7bdffe3f",  # gen.composite_build_pool
    "1b7a80122a1415d8db205339ae13be155654245bd097b7b3dcd4d77f46890245",  # gen.faker_unique_retry
    "931a64ec2c34e8a8fba15a40515bfd857eee935fd30dc23c5cc2f2db6c1c7694",  # gen.categorical_unique
    "60d3a8236357b837990a978b3b84fa9681dfca409cf1896d13a3cc9e30d6079e",  # gen.reference_unique
    "81257af1bd65184ee366d01bd5f28e89bb58d7c09ab47e0c0543776a945453ba",  # gen.unique_pair
    "916ebf46efe090c9bffbef46663ff183797ad0adb588e13e0a560bc3a6e2fbed",  # mask.faker
    "cb0c2d260f36b7d2f4e2d1f0755896e082e01822075e5073b6c76ceb08316b60",  # gen.pool_build_faker
    "e5e15c7f6cf521636920a2d6c4141e63ff8a49bb8256385c4a5230c577376146",  # gen.identifier_deterministic
    "c175f6bbb2e582aff8d45beee43466397a3c29ed6b0b5e8986d7863cf6909f57",  # gen.identifier_nondeterministic
    "5e6fa8311c566b1ffeb9e2d8496d76ee0bb91b37827e074b587384b90b9c3328",  # gen.derive_context
    "7f1198095c8c582ff3d9e340712005d1afa7d6d6198887418f8e33b93bfffa03",  # mask.formula
    "ab83162c11f2c4dbe9ca55d9c2e90f288f472fb41eb843b9284c4fa4ad71d609",  # gen.faker_pool_build
    "bc47a0a423b34fc0ebdc2dca30eadf3e9c47ad29713a63937844fe48d7d57d81",  # gen.faker_pool_selection
    "e49b4f3e3eeb2f621368bb10b751a73087ba63f4d4b4794f0ed49418af92858f",  # mask.faker_nondeterministic
    "abea5ec5c7f29142ce8bf7c344245c68fa73d17eed4cc3633a9129b6a4a74c2c",  # mask.tokenize
    "448b2f19f340635c8e5ae9505271bcf521b1f1a1e08dd48c2392847d20b88cb5",  # gen.distribution
    "853a020843acba06217afc3f99579ab0118fe54ca0b08b5316744425376a95c2",  # gen.lookup
]

_MAP_DIGESTS = {
    "MASK_STRATEGY_TO_SITE": "e42b340fc017f0608c08ec988fb697bb52c84f5cbb657dfa99b9531cd56681e9",
    # GEN_KIND_TO_SITE re-pinned for GEN-TYPES E1 (constant, distribution), E3 (lookup),
    # GEN-PROVIDERS E1 (provider, mapped to the existing gen.derive_context) and GEN-INHERIT E1
    # (inherit, mapped to DETERMINISTIC_NO_DRAW).
    "GEN_KIND_TO_SITE": "44971684eca62ff4ae73fdac34c988332d12ad8689da63de4974c0cf7fe19bc0",
    "PROVIDER_IDENTIFIER_SITES": "19593ad7e4ac52025cdc024aa16bdb04ab776755b83e6f7c0e546210b6fc7cd6",
    "FAMILIES": "cbbf3f70f90b3995c7bb16f11bf1560ce135af11761cc6444aa41feaf659e811",
    "ENTROPY_ROOTS": "4f3fdb974258ed94e92188bd4dd456363696dba2d2a4a90a4f744c53879949f8",
    "IDENTITIES": "802762f296f31c9788f734245459e4480e13ea2a69c20cd43ab0c54b161a558a",
    "DETERMINISTIC_NO_DRAW": "1700d4ac7218adaf8022c7d6b1cd3424bf8b29871c28b67a312d9f07064e745e",
}
