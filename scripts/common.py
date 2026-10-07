"""Shared paths and size definitions for the Polars vs pandas benchmark."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("BENCH_DATA_DIR", ROOT / "data"))
# Never overwrite the published measurements by default.
RESULTS = Path(os.environ.get("BENCH_RESULTS_DIR", ROOT / "runs" / "latest"))

# Number of order rows per size label. Customers = rows // 10.
SIZES = {
    "1M": 1_000_000,
    "10M": 10_000_000,
    "50M": 50_000_000,
}


def paths(size: str) -> dict[str, Path]:
    return {
        "orders_csv": DATA / f"orders_{size}.csv",
        "orders_parquet": DATA / f"orders_{size}.parquet",
        "customers_csv": DATA / f"customers_{size}.csv",
        "customers_parquet": DATA / f"customers_{size}.parquet",
    }
