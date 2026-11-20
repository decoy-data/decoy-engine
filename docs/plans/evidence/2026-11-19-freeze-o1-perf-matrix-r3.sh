#!/bin/bash
# Round 3: only the cells the exact integer evaluator changes, 10M rows. Run inside the snapshot dir.
S=$1
run() { PYTHONPATH=$PWD/src:$PWD $PY $S "$@" 2>&1 | tail -1; }
for c in plain fk declared anchor; do
  for v in float_literal object_literal; do run full_frame $c 10000000 $v; done
done
run unified plain 10000000 numexpr
