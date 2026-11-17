"""Which common writers produce `large_string`, plus a one-run kernel ratio and a cast-parity check.

Usage: python -I source_types.py WORKDIR
"""

import sys
import time

import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from decoy_engine.kernel import redact_array, truncate_array

d = sys.argv[1]
n = 2_000_000
vals = [f"user{i}@example.com" if i % 10 else None for i in range(n)]
s = pa.array(vals, type=pa.string())
ls = s.cast(pa.large_string())
# Which real sources produce large_string?
pl.DataFrame({"c": vals[:1000]}).write_parquet(f"{d}/polars.parquet")
print(
    "polars parquet -> pq.read_table:", pq.read_table(f"{d}/polars.parquet").schema.field("c").type
)
pdf = pd.DataFrame({"c": pd.array(vals[:1000], dtype="string[pyarrow]")})
print("pandas string[pyarrow] -> from_pandas:", pa.Table.from_pandas(pdf).schema.field("c").type)
pdf.to_parquet(f"{d}/pd.parquet")
print(
    "pandas string[pyarrow] parquet -> read:",
    pq.read_table(f"{d}/pd.parquet").schema.field("c").type,
)
print("pl.DataFrame.to_arrow:", pl.DataFrame({"c": vals[:10]}).to_arrow().schema.field("c").type)
print("pyarrow.csv.read_csv default:", end=" ")
with open(f"{d}/x.csv", "w") as fh:
    fh.write("c\na\nb\n")
print(pcsv.read_csv(f"{d}/x.csv").schema.field("c").type)
for name, fn in [
    ("redact", lambda a: redact_array(a, redact_with="X")),
    ("truncate", lambda a: truncate_array(a, length=4, keep="head")),
    ("truncate mask", lambda a: truncate_array(a, length=4, keep="tail", mask_char="*")),
]:
    t = time.perf_counter()
    a = fn(s)
    t1 = time.perf_counter() - t
    t = time.perf_counter()
    b = fn(ls)
    t2 = time.perf_counter() - t
    c = fn(ls.cast(pa.string()))
    print(
        f"{name}: string {t1:.3f}s  large_string {t2:.3f}s  ratio {t2 / t1:.0f}x  out types {a.type}/{b.type}  cast-parity {b.equals(c)}"
    )
t = time.perf_counter()
ls.cast(pa.string())
print(f"cast large->string {time.perf_counter() - t:.3f}s")
