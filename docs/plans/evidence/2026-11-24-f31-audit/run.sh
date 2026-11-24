#!/bin/sh
# Re-run the F31 audit counts. Usage: run.sh <engine checkout> <cli checkout>
set -eu
here=$(dirname "$0")
python3 -I "$here/copies.py" "$1/src/decoy_engine" "$here/engine-copies.tsv"
python3 -I "$here/copies.py" "$2/src/decoy" "$here/cli-copies.tsv"
python3 -I "$here/triage.py" "$here/engine-copies.tsv" engine "$here/engine-triage.tsv"
python3 -I "$here/triage.py" "$here/cli-copies.tsv" cli "$here/cli-triage.tsv"
python3 -I "$here/registry_share.py" "$1/src/decoy_engine" "$here/engine-copies.tsv" "$here/engine-registry-share.tsv"
python3 -I "$here/sites.py" "$1/src/decoy_engine" "$here/engine-sites.json"
python3 -I "$here/sites.py" "$2/src/decoy" "$here/cli-sites.json"
