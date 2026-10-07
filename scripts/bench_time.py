"""Time every op for one (mode, size) in a fresh process.

For each op: `warmup` untimed runs, then `repeats` timed runs. Each run is preceded
by gc.collect() (not timed). We record wall time (perf_counter) and process CPU time
(user+sys over all threads) so we can report how many cores were busy on average.

This Mac is a live desktop that other jobs share, so every run also records how many
cores *other* processes kept busy while it ran (system busy CPU minus our own CPU,
divided by wall time). Rules, fixed before any results were seen:
  * before each op's batch, wait until other processes use <= GATE_MAX cores (2 s sample)
  * a single run of >= 1 s with other processes above BG_MAX cores is discarded and redone
  * a whole batch (>= 1 s of timed runs) that saw > BG_MAX background cores on average is redone
    (max 3 batch attempts; the last attempt is kept and flagged)
Discarded runs stay in the file with accepted=false.

Appends one JSON line per run to results/timings.jsonl.

Usage: python bench_time.py --mode polars-eager --size 10M [--warmup 1 --repeats 5 --ops a,b --tag x]
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import time

import psutil

from common import RESULTS, paths
from ops import IO_OPS, MEM_OPS, PANDAS_EXTRA, PIPE_OPS, get_ops

GATE_MAX = 2.5  # cores used by other processes, to start a batch
BG_MAX = 3.0  # cores used by other processes, to accept a run / batch
GATE_TIMEOUT_S = 20 * 60
LONG_RUN_S = 1.0  # CPU-time counters update too coarsely to judge shorter spans
MAX_RUN_RETRIES = 3
MAX_BATCH_ATTEMPTS = 3


def cpu_seconds() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def sys_busy() -> float:
    t = psutil.cpu_times()
    return t.user + t.system + getattr(t, "nice", 0.0)


def background_cores(interval: float = 2.0) -> float:
    b0, c0 = sys_busy(), cpu_seconds()
    time.sleep(interval)
    return (sys_busy() - b0 - (cpu_seconds() - c0)) / interval


def wait_for_quiet(label: str) -> tuple[float, float]:
    """Block until other processes are quiet. Returns (seconds waited, last bg reading)."""
    t0 = time.perf_counter()
    while True:
        bg = background_cores()
        waited = time.perf_counter() - t0
        if bg <= GATE_MAX or waited > GATE_TIMEOUT_S:
            if waited > 5:
                print(f"     waited {waited:5.0f}s for a quiet machine before {label} (bg {bg:.1f} cores)", flush=True)
            return waited, bg
        time.sleep(5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True)
    ap.add_argument("--size", required=True)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--ops", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=str(RESULTS / "timings.jsonl"))
    a = ap.parse_args()

    ops = get_ops(a.mode)
    names = a.ops.split(",") if a.ops else IO_OPS + MEM_OPS + PIPE_OPS + (PANDAS_EXTRA if a.mode == "pandas" else [])
    names = [n for n in names if n in ops]
    p = paths(a.size)

    t0 = time.perf_counter()
    ctx = {"p": p, **ops["_load"](p)}
    load_s = time.perf_counter() - t0

    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(a.out, "a") as out:
        for op in names:
            fn = ops[op]
            for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
                waited, gate_bg = wait_for_quiet(f"{a.mode} {op}")
                recs: list[dict] = []
                i = run_retries = 0
                while i < a.warmup + a.repeats:
                    gc.collect()
                    b0, c0, w0 = sys_busy(), cpu_seconds(), time.perf_counter()
                    res = fn(ctx)
                    wall = time.perf_counter() - w0
                    cpu = cpu_seconds() - c0
                    bg_s = max(0.0, sys_busy() - b0 - cpu)
                    rows = len(res)
                    del res
                    warm = i < a.warmup
                    rec = {
                        "size": a.size, "mode": a.mode, "op": op, "tag": a.tag,
                        "run": i - a.warmup, "warmup": warm, "attempt": attempt,
                        "wall_s": wall, "cpu_s": cpu, "bg_cpu_s": bg_s, "bg_cores": bg_s / wall,
                        "rows_out": rows, "gate_wait_s": waited, "gate_bg_cores": gate_bg,
                        "polars_max_threads": os.environ.get("POLARS_MAX_THREADS", ""),
                        "input_load_s": load_s, "unix_time": time.time(), "accepted": True,
                    }
                    if not warm and wall >= LONG_RUN_S and rec["bg_cores"] > BG_MAX and run_retries < MAX_RUN_RETRIES:
                        rec["accepted"] = False
                        rec["reject_reason"] = "run_background"
                        out.write(json.dumps(rec) + "\n")
                        run_retries += 1
                        print(f"     redo {op} run {i - a.warmup}: other processes used {rec['bg_cores']:.1f} cores", flush=True)
                        wait_for_quiet(f"{a.mode} {op} redo")
                        continue
                    recs.append(rec)
                    i += 1
                timed = [r for r in recs if not r["warmup"]]
                batch_bg = sum(r["bg_cpu_s"] for r in timed) / sum(r["wall_s"] for r in timed)
                measurable = sum(r["wall_s"] for r in timed) >= LONG_RUN_S
                ok = not measurable or batch_bg <= BG_MAX or attempt == MAX_BATCH_ATTEMPTS
                for r in recs:
                    r["batch_bg_cores"] = batch_bg if measurable else None
                    r["accepted"] = ok
                    if not ok:
                        r["reject_reason"] = "batch_background"
                    elif measurable and batch_bg > BG_MAX:
                        r["flag"] = "background_above_limit_after_retries"
                    out.write(json.dumps(r) + "\n")
                out.flush()
                med = sorted(r["wall_s"] for r in timed)[len(timed) // 2]
                print(
                    f"{a.size:>4} {a.mode:18s} {a.tag:9s} {op:24s} median={med:8.4f}s "
                    f"cores={timed[0]['cpu_s'] / timed[0]['wall_s']:5.1f} bg={batch_bg:4.1f}"
                    + ("" if ok else "  -> background too high, redoing batch"),
                    flush=True,
                )
                if ok:
                    break


if __name__ == "__main__":
    main()
