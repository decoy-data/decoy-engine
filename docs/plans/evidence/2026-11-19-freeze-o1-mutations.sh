#!/bin/bash
# Run inside a throwaway snapshot with $PY set. For each named mutation: apply it to src/, run the
# O1 owners, and report RED (killed) or SURVIVED. Restores src/ at the end.
D=docs/plans/evidence
TESTS="tests/sentry/defects/test_lossless_int_columns.py tests/sentry/defects/test_group_by_single_reader.py tests/unit/execution/test_o1_when_eval_frame.py tests/unit/execution/test_o1_when_routes.py tests/unit/execution/test_group_key_chunked.py"
rm -rf /tmp/o1-src-orig && cp -r src /tmp/o1-src-orig
for n in $NAMES; do
  rm -rf src && cp -r /tmp/o1-src-orig src
  $PY $D/2026-11-19-freeze-o1-mutate.py "$n" >/dev/null || { echo "MUTATION $n APPLY-FAILED"; continue; }
  out=$($PY -m pytest $TESTS -q -x -p no:cacheprovider 2>&1 | tail -6)
  if echo "$out" | grep -qE "[0-9]+ failed|[0-9]+ error"; then
    echo "MUTATION $n RED: $(echo "$out" | grep -E '^FAILED|^ERROR' | head -1 | cut -c1-150)"
  else
    echo "MUTATION $n SURVIVED: $(echo "$out" | tail -1)"
  fi
done
rm -rf src && cp -r /tmp/o1-src-orig src
