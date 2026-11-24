"""F31 audit: mark each exception-text copy with the slice that removes it, or V2-LOG.

Usage: python3 triage.py <copies.tsv> <repo: engine|cli> <out.tsv>

Rules, in order: a copy whose sink is a raise (engine) or a terminal call (CLI) is removed by
AE3b or AC3; a copy named in COVERED is handled by the named slice; every other copy stays, is
outside the guarantee, and is logged V2-LOG. The guarantee covers only corpus shapes plus
ratcheted sites, so V2-LOG rows are counted by the ratchet but not claimed safe.
"""

import sys
from collections import Counter

COVERED = {
    "engine": {
        "execution/native/_fpe_ext.py": "AE4 native canary",
        "execution/native/_crypto_ext.py": "AE4 native canary",
        "execution/native/_group_key_ext.py": "AE4 native canary",
        "execution/native/_index_ext.py": "AE4 native canary",
        "execution/native/_text_mask_route.py": "AE4 native canary",
    },
    "cli": {
        "cli/run/_errors.py": "AC1 fail() renders",
        "cli/_sources.py": "AC1 refusal_message renders",
        "cli/run/_value_free.py": "AC1 fail() renders",
    },
}
src, repo, out = sys.argv[1], sys.argv[2], sys.argv[3]
removed_sink = "raise" if repo == "engine" else "terminal"
rows = [line.split("\t") for line in open(src).read().splitlines()[1:]]
with open(out, "w") as fh:
    fh.write("file\tline\tform\tbinding\tsink\tstatus\n")
    tally = Counter()
    for f, line, form, binding, sink in rows:
        if sink == removed_sink:
            status = "AE3b" if repo == "engine" else "AC3"
        else:
            status = COVERED[repo].get(f, "V2-LOG")
        tally[status] += 1
        fh.write("\t".join([f, line, form, binding, sink, status]) + "\n")
print(repo, dict(tally))
