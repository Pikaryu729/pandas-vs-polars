"""Record the software and hardware this benchmark ran on (no serial numbers or UUIDs)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import platform
import subprocess
import sys
import time

import numpy
import pandas
import polars
import psutil
import pyarrow

from common import RESULTS


def sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return ""


def polars_versions() -> list[str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        polars.show_versions()
    return [ln for ln in buf.getvalue().splitlines() if ln.split(":")[0].strip() in ("Polars", "Build", "Index type", "Runtime")]


def main() -> None:
    hw = {}
    for line in sh("system_profiler", "SPHardwareDataType").splitlines():
        k, _, v = line.strip().partition(": ")
        if k in ("Model Name", "Model Identifier", "Chip", "Total Number of Cores", "Memory"):
            hw[k] = v
    info = {
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "python": sys.version,
        "polars": polars.__version__,
        "polars_show_versions": polars_versions(),
        "polars_thread_pool_size": polars.thread_pool_size(),
        "polars_engine_affinity": __import__("polars._plr", fromlist=["get_engine_affinity"]).get_engine_affinity(),
        "pandas": pandas.__version__,
        "pyarrow": pyarrow.__version__,
        "numpy": numpy.__version__,
        "psutil": psutil.__version__,
        "os": platform.system(),
        "os_release": platform.release(),
        "macos": platform.mac_ver()[0],
        "machine": platform.machine(),
        "hardware": hw,
        "perf_cores": sh("sysctl", "-n", "hw.perflevel0.physicalcpu"),
        "efficiency_or_second_tier_cores": sh("sysctl", "-n", "hw.perflevel1.physicalcpu"),
        "perflevel0_name": sh("sysctl", "-n", "hw.perflevel0.name"),
        "perflevel1_name": sh("sysctl", "-n", "hw.perflevel1.name"),
        "logical_cpus": psutil.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "load_avg": os.getloadavg(),
        "power": sh("pmset", "-g", "batt").splitlines()[:1],
        "low_power_mode": sh("pmset", "-g").count("lowpowermode 1") > 0,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "environment.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
