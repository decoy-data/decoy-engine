#!/bin/bash
# usage: matrix.sh <script path>; run inside the snapshot dir
S=$1
run() { PYTHONPATH=$PWD/src:$PWD $PY $S "$@" 2>&1 | tail -1; }
for n in 1000000 10000000; do
  for c in plain fk declared anchor; do
    for v in numexpr object_value object_literal float_literal; do run full_frame $c $n $v; done
    for v in numexpr object_value; do run chunked $c $n $v; done
  done
  for c in plain declared; do run unified $c $n numexpr; done
done
