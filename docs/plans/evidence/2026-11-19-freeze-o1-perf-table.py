"""Join the head and origin/main perf rows (same directory) into one comparison table."""

import json
from pathlib import Path

HERE = Path(__file__).parent


def load(name: str) -> dict[tuple[str, str, int, str], dict[str, float]]:
    rows = (json.loads(x) for x in (HERE / name).read_text().splitlines() if x.startswith("{"))
    return {(r["route"], r["cls"], r["rows"], r["variant"]): r for r in rows}


head, main = (
    load("2026-11-19-freeze-o1-perf-head.jsonl"),
    load("2026-11-19-freeze-o1-perf-main.jsonl"),
)
print("route cls rows variant | main +MB wall eval | head +MB wall eval frame | d+MB dEval")
for key in sorted(head):
    if key not in main:
        continue
    a, b = main[key], head[key]
    ar, br = a["peak_rss_mb"] - a["rss_before_mb"], b["peak_rss_mb"] - b["rss_before_mb"]
    print(
        *key, "|", ar, a["wall_s"], a["eval_s"], "|", br, b["wall_s"], b["eval_s"], b["frame_s"],
        "|", br - ar, round(b["eval_s"] - a["eval_s"], 3),
    )  # fmt: skip
