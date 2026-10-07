"""Summarise results/timings.jsonl and results/memory.jsonl.

Timing: per (size, mode, op, tag) over the timed (non-warm-up) runs:
  median, min, max, q1, q3, IQR as % of median, median cores busy (cpu/wall).
Speedup = pandas median / Polars median (same size, same op).
Memory: per (size, mode, op): median / min / max peak RSS growth over the reps.

Writes results/summary.json and results/summary.md.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from collections import defaultdict

from common import RESULTS
from ops import IO_OPS, MEM_OPS, PIPE_OPS

OP_ORDER = IO_OPS + ["read_csv_arrow"] + MEM_OPS + PIPE_OPS + ["pipeline_parquet_tuned", "pipeline_csv_tuned"]
MODES = ["pandas", "polars-eager", "polars-lazy", "polars-lazy-inmem"]


def quantiles(xs: list[float]) -> tuple[float, float]:
    if len(xs) < 4:
        return min(xs), max(xs)
    q = st.quantiles(xs, n=4, method="inclusive")
    return q[0], q[2]


def load(name: str) -> list[dict]:
    path = RESULTS / name
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def main() -> None:
    global RESULTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", type=Path, default=RESULTS)
    a = ap.parse_args()
    RESULTS = a.results_dir
    raw = load("timings.jsonl")
    if not raw:
        raise SystemExit(f"No timing records in {RESULTS}")
    timings = [r for r in raw if not r["warmup"] and r.get("accepted", True)]
    rejected = [r for r in raw if not r.get("accepted", True)]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in timings:
        groups[(r["size"], r["mode"], r["op"], r["tag"])].append(r)

    tsum = {}
    for (size, mode, op, tag), rs in groups.items():
        w = [r["wall_s"] for r in rs]
        med = st.median(w)
        q1, q3 = quantiles(w)
        tsum[f"{size}|{mode}|{op}|{tag}"] = {
            "size": size, "mode": mode, "op": op, "tag": tag, "n": len(w),
            "median_s": med, "min_s": min(w), "max_s": max(w), "q1_s": q1, "q3_s": q3,
            "iqr_pct": 100 * (q3 - q1) / med if med else 0,
            "range_pct": 100 * (max(w) - min(w)) / med if med else 0,
            "cores_busy": st.median(r["cpu_s"] / r["wall_s"] for r in rs if r["wall_s"] > 0),
            "rows_out": rs[0]["rows_out"],
            "bg_cores_batch": rs[0].get("batch_bg_cores"),
            "bg_cores_max_run": max(r.get("bg_cores", 0) for r in rs),
            "flag": rs[0].get("flag", ""),
        }

    speed = {}
    for k, v in tsum.items():
        if v["mode"] == "pandas" or v["tag"]:
            continue
        base = tsum.get(f"{v['size']}|pandas|{v['op']}|")
        if base:
            speed[k] = base["median_s"] / v["median_s"]

    mem_rows = load("memory.jsonl")
    mgroups: dict[tuple, list[dict]] = defaultdict(list)
    for r in mem_rows:
        mgroups[(r["size"], r["mode"], r["op"])].append(r)
    msum = {}
    for (size, mode, op), rs in mgroups.items():
        d = [r["peak_delta_sampled"] for r in rs]
        msum[f"{size}|{mode}|{op}"] = {
            "size": size, "mode": mode, "op": op, "n": len(d),
            "median_peak_mb": st.median(d) / 1e6, "min_peak_mb": min(d) / 1e6, "max_peak_mb": max(d) / 1e6,
            "median_maxrss_mb": st.median(r["peak_delta_maxrss"] for r in rs) / 1e6,
            "result_mb": st.median(r["result_bytes"] for r in rs) / 1e6,
            "input_mb": st.median(r["input_bytes"] for r in rs) / 1e6,
            "baseline_mb": st.median(r["baseline_rss"] for r in rs) / 1e6,
        }

    bg = sorted(v["bg_cores_batch"] for v in tsum.values() if v["bg_cores_batch"] is not None)
    noise = {
        "timed_runs_kept": len(timings),
        "runs_discarded_for_background_load": len(rejected),
        "background_cores_per_batch_median": st.median(bg) if bg else None,
        "background_cores_per_batch_max": max(bg) if bg else None,
        "batches_flagged": [k for k, v in tsum.items() if v["flag"]],
    }
    (RESULTS / "summary.json").write_text(
        json.dumps({"timing": tsum, "speedup_vs_pandas": speed, "memory": msum, "noise": noise}, indent=1)
    )

    out = ["# Polars 2.0 vs pandas - summary of measured runs", "", f"Background load: {json.dumps(noise)}", ""]
    sizes = [s for s in ("1M", "10M", "50M") if any(v["size"] == s for v in tsum.values())]
    for size in sizes:
        out += [f"## Timing, {size} rows (median seconds [min-max], IQR % of median, cores busy)", "",
                "| op | " + " | ".join(MODES) + " | best Polars speedup |", "|---" * (len(MODES) + 2) + "|"]
        for op in OP_ORDER:
            cells, best = [], None
            for mode in MODES:
                v = tsum.get(f"{size}|{mode}|{op}|")
                if not v:
                    cells.append("")
                    continue
                cells.append(f"{v['median_s']:.4f} [{v['min_s']:.4f}-{v['max_s']:.4f}] {v['iqr_pct']:.0f}% x{v['cores_busy']:.1f}")
                sp = speed.get(f"{size}|{mode}|{op}|")
                if sp and (best is None or sp > best[0]):
                    best = (sp, mode)
            if any(cells):
                out.append(f"| {op} | " + " | ".join(cells) + f" | {f'{best[0]:.1f}x ({best[1]})' if best else ''} |")
        out.append("")
    one = [v for v in tsum.values() if v["tag"] == "1-thread"]
    if one:
        out += ["## Polars pinned to 1 thread, 10M rows (median s) vs 18 threads and pandas", "",
                "| op | pandas | polars-eager 1 thread | polars-eager 18 | polars-lazy 1 thread | polars-lazy 18 |", "|---|---|---|---|---|---|"]
        for op in OP_ORDER:
            g = lambda m, t: tsum.get(f"10M|{m}|{op}|{t}")  # noqa: E731
            row = [g("pandas", ""), g("polars-eager", "1-thread"), g("polars-eager", ""), g("polars-lazy", "1-thread"), g("polars-lazy", "")]
            if row[1]:
                out.append(f"| {op} | " + " | ".join(f"{x['median_s']:.4f}" if x else "" for x in row) + " |")
        out.append("")
    for size in ("10M", "50M"):
        if not any(v["size"] == size for v in msum.values()):
            continue
        out += [f"## Peak memory growth, {size} rows (median MB over reps [min-max]; result frame MB)", "",
                "| op | " + " | ".join(MODES) + " |", "|---" * (len(MODES) + 1) + "|"]
        for op in OP_ORDER:
            cells = []
            for mode in MODES:
                v = msum.get(f"{size}|{mode}|{op}")
                cells.append(f"{v['median_peak_mb']:.0f} [{v['min_peak_mb']:.0f}-{v['max_peak_mb']:.0f}]; out {v['result_mb']:.0f}" if v else "")
            if any(cells):
                out.append(f"| {op} | " + " | ".join(cells) + " |")
        inp = {m: msum.get(f"{size}|{m}|filter", {}).get("input_mb") for m in MODES}
        out += ["", f"In-memory size of the {size} orders frame as reported by each library: " + ", ".join(f"{m} {v:.0f} MB" for m, v in inp.items() if v), ""]
    (RESULTS / "summary.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
