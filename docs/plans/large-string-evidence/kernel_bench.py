"""Kernel timing: `redact_array` and `truncate_array` on 2M rows, `string` vs `large_string`.

Five timed runs after one warm-up per cell; prints median, min and max.
Usage: python -I kernel_bench.py
"""

import statistics as st
import time

import pyarrow as pa

from decoy_engine.kernel import redact_array, truncate_array

n = 2_000_000
s = pa.array([f"user{i}@example.com" if i % 10 else None for i in range(n)], type=pa.string())
ls = s.cast(pa.large_string())
cases = [
    ("redact", lambda a: redact_array(a, redact_with="X")),
    ("truncate head", lambda a: truncate_array(a, length=4, keep="head")),
    ("truncate tail mask_char", lambda a: truncate_array(a, length=4, keep="tail", mask_char="*")),
    ("cast large_string->string", lambda a: a.cast(pa.string())),
]
for name, fn in cases:
    for lab, arr in (("string", s), ("large_string", ls)):
        if name.startswith("cast") and lab == "string":
            continue
        fn(arr)
        xs = []
        for _ in range(5):
            t = time.perf_counter()
            fn(arr)
            xs.append(time.perf_counter() - t)
        print(
            f"{name:26s} {lab:13s} median {st.median(xs):.3f}s min {min(xs):.3f} max {max(xs):.3f}"
        )
