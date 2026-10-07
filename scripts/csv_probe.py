"""Side check: why pandas' pyarrow CSV engine beat Polars at reading the orders CSV.

Times several ways of reading the same file (1 warm-up + 5 timed runs each, after the
same quiet-machine gate as bench_time.py). Appends to results/csv_probe.jsonl.

Usage: python csv_probe.py 50M
"""

from __future__ import annotations

import gc
import json
import statistics as st
import sys
import time

import pandas as pd
import polars as pl
import pyarrow.csv as pacsv

from bench_time import cpu_seconds, sys_busy, wait_for_quiet
from common import RESULTS, paths

size = sys.argv[1] if len(sys.argv) > 1 else "50M"
f = str(paths(size)["orders_csv"])

VARIANTS = {
    "polars read_csv, try_parse_dates=True (benchmark setting)": lambda: pl.read_csv(f, try_parse_dates=True),
    "polars read_csv, ts left as text": lambda: pl.read_csv(f),
    "polars read_csv, ts typed via schema_overrides": lambda: pl.read_csv(f, schema_overrides={"ts": pl.Datetime("us")}),
    "polars scan_csv(...).collect() (streaming), try_parse_dates=True": lambda: pl.scan_csv(f, try_parse_dates=True).collect(),
    "pandas read_csv engine=pyarrow, parse_dates (benchmark setting)": lambda: pd.read_csv(f, engine="pyarrow", parse_dates=["ts"]),
    "pyarrow.csv.read_csv (Arrow table, no pandas)": lambda: pacsv.read_csv(f),
    "pyarrow.csv.read_csv -> pl.from_arrow": lambda: pl.from_arrow(pacsv.read_csv(f)),
}

RESULTS.mkdir(parents=True, exist_ok=True)
with open(RESULTS / "csv_probe.jsonl", "a") as out:
    for name, fn in VARIANTS.items():
        wait_for_quiet(name)
        walls, cores, bgs = [], [], []
        for i in range(6):
            gc.collect()
            b0, c0, w0 = sys_busy(), cpu_seconds(), time.perf_counter()
            res = fn()
            wall = time.perf_counter() - w0
            cpu = cpu_seconds() - c0
            bg = max(0.0, sys_busy() - b0 - cpu) / wall
            del res
            if i == 0:
                continue
            walls.append(wall)
            cores.append(cpu / wall)
            bgs.append(bg)
        rec = {"size": size, "variant": name, "walls_s": walls, "median_s": st.median(walls),
               "cores_busy": st.median(cores), "bg_cores_median": st.median(bgs), "unix_time": time.time()}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(f"{size} {name:66s} median={rec['median_s']:.3f}s [{min(walls):.3f}-{max(walls):.3f}] cores={rec['cores_busy']:.1f} bg={rec['bg_cores_median']:.1f}", flush=True)
