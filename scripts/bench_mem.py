"""Measure peak memory of one op in a fresh child process.

Parent: starts a child, waits until the child has loaded its inputs and reports its
resident set size (baseline), tells it to run the op once, and polls the child's RSS
every ~1 ms from outside the child (so the GIL cannot hide peaks). Peak working memory
= max sampled RSS - baseline. For file-reading ops the child loads nothing beforehand,
so its own ru_maxrss (kernel-tracked peak) - baseline is exact; we record both.

Appends one JSON line per measurement to results/memory.jsonl.

Usage:
  python bench_mem.py --size 10M --modes pandas,polars-eager --ops filter,join --reps 3
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time

from common import RESULTS, paths


def child(mode: str, size: str, op: str) -> None:
    import gc

    import psutil

    from ops import IO_OPS, PANDAS_EXTRA, PIPE_OPS, frame_bytes, get_ops

    ops = get_ops(mode)
    p = paths(size)
    from_files = op in IO_OPS or op in PIPE_OPS or op in PANDAS_EXTRA
    ctx = {"p": p} if from_files else {"p": p, **ops["_load"](p)}
    input_bytes = 0 if from_files else frame_bytes(ctx["orders"])
    gc.collect()
    proc = psutil.Process()
    base = proc.memory_info().rss
    print(json.dumps({"ready": base}), flush=True)
    sys.stdin.readline()  # "go"
    t0 = time.perf_counter()
    res = ops[op](ctx)
    wall = time.perf_counter() - t0
    after = proc.memory_info().rss
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":  # KiB on Linux, bytes on macOS
        maxrss *= 1024
    print(
        json.dumps(
            {
                "done": True,
                "rss_after": after,
                "ru_maxrss": maxrss,
                "wall_s": wall,
                "rows_out": len(res),
                "result_bytes": frame_bytes(res),
                "input_bytes": input_bytes,
            }
        ),
        flush=True,
    )
    sys.stdin.readline()  # "exit"


def measure(mode: str, size: str, op: str) -> dict:
    import psutil

    env = dict(os.environ)
    cp = subprocess.Popen(
        [sys.executable, __file__, "--child", mode, size, op],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    ready = json.loads(cp.stdout.readline())
    base = ready["ready"]
    pp = psutil.Process(cp.pid)
    done = {}
    finished = threading.Event()

    def reader():
        done.update(json.loads(cp.stdout.readline()))
        finished.set()

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    cp.stdin.write("go\n")
    cp.stdin.flush()
    peak = base
    samples = 0
    while not finished.is_set():
        try:
            rss = pp.memory_info().rss
        except psutil.Error:
            break
        peak = max(peak, rss)
        samples += 1
        time.sleep(0.001)
    th.join()
    peak = max(peak, done.get("rss_after", 0))
    cp.stdin.write("exit\n")
    cp.stdin.flush()
    cp.wait()
    return {
        "size": size,
        "mode": mode,
        "op": op,
        "baseline_rss": base,
        "peak_rss_sampled": peak,
        "peak_delta_sampled": peak - base,
        "peak_delta_maxrss": done["ru_maxrss"] - base,
        "rss_after_delta": done["rss_after"] - base,
        "samples": samples,
        "wall_s": done["wall_s"],
        "rows_out": done["rows_out"],
        "result_bytes": done["result_bytes"],
        "input_bytes": done["input_bytes"],
        "unix_time": time.time(),
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:5])
        return
    from ops import IO_OPS, MEM_OPS, MODES, PANDAS_EXTRA, PIPE_OPS

    ap = argparse.ArgumentParser()
    ap.add_argument("--size", required=True)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--ops", default="")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default=str(RESULTS / "memory.jsonl"))
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(a.out, "a") as out:
        for mode in a.modes.split(","):
            names = a.ops.split(",") if a.ops else IO_OPS + MEM_OPS + PIPE_OPS + (PANDAS_EXTRA if mode == "pandas" else [])
            if mode != "pandas":
                names = [n for n in names if n not in PANDAS_EXTRA]
            for op in names:
                for rep in range(a.reps):
                    r = measure(mode, a.size, op) | {"rep": rep}
                    out.write(json.dumps(r) + "\n")
                    out.flush()
                    print(
                        f"{a.size:>4} {mode:18s} {op:24s} rep{rep} peak+{r['peak_delta_sampled'] / 1e6:9.1f} MB "
                        f"(maxrss+{r['peak_delta_maxrss'] / 1e6:9.1f}) result={r['result_bytes'] / 1e6:8.1f} MB "
                        f"samples={r['samples']}",
                        flush=True,
                    )


if __name__ == "__main__":
    main()
