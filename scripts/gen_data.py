"""Generate a synthetic but realistic orders + customers dataset.

orders (N rows): one row per order line, in time order (append-only log).
customers (N // 10 rows): dimension table, ~10 orders per customer.

The same files feed both libraries. CSV and Parquet are written by Polars
(Parquet: Polars defaults, zstd compression, column statistics on).

Usage: python gen_data.py 1M 10M 50M
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

import numpy as np
import polars as pl

from common import DATA, SIZES, paths

SEED = 20261007

STATUS = ["delivered", "shipped", "pending", "cancelled", "returned"]
STATUS_P = [0.62, 0.18, 0.08, 0.07, 0.05]
CHANNEL = ["web", "app", "store", "phone"]
CHANNEL_P = [0.45, 0.30, 0.20, 0.05]
SEGMENT = ["consumer", "corporate", "small_business"]
SEGMENT_P = [0.7, 0.2, 0.1]
COUNTRIES = [
    "US", "CA", "MX", "BR", "AR", "GB", "IE", "FR", "DE", "NL", "BE", "ES", "PT", "IT", "CH",
    "AT", "SE", "NO", "DK", "FI", "PL", "CZ", "JP", "KR", "CN", "IN", "SG", "AU", "NZ", "ZA",
]


def make(n: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(SEED + n)
    n_cust = n // 10
    start = np.datetime64("2025-01-01T00:00:00", "s")
    span = 365 * 24 * 3600
    ts = np.sort(rng.integers(0, span, n)).astype("timedelta64[s]") + start

    discount = rng.choice(np.array([0.0, 0.05, 0.10, 0.20]), n, p=[0.6, 0.2, 0.15, 0.05])
    discount_null = rng.random(n) < 0.05  # 5% missing discounts

    orders = pl.DataFrame(
        {
            "order_id": np.arange(n, dtype=np.int64),
            "ts": ts.astype("datetime64[us]"),
            "customer_id": rng.integers(0, n_cust, n, dtype=np.int64),
            "product_id": rng.integers(0, 50_000, n, dtype=np.int64),
            "store": pl.Series(rng.integers(0, 200, n)).cast(pl.String).str.zfill(3),
            "channel": np.array(CHANNEL)[rng.choice(len(CHANNEL), n, p=CHANNEL_P)],
            "status": np.array(STATUS)[rng.choice(len(STATUS), n, p=STATUS_P)],
            "quantity": rng.integers(1, 11, n, dtype=np.int64),
            "unit_price": np.round(rng.lognormal(3.2, 0.9, n), 2),
            "discount": discount,
        }
    ).with_columns(
        pl.concat_str(pl.lit("store_"), pl.col("store")).alias("store"),
        pl.when(pl.Series(discount_null)).then(None).otherwise(pl.col("discount")).alias("discount"),
    )

    cust_start = np.datetime64("2018-01-01", "D")
    customers = pl.DataFrame(
        {
            "customer_id": np.arange(n_cust, dtype=np.int64),
            "segment": np.array(SEGMENT)[rng.choice(len(SEGMENT), n_cust, p=SEGMENT_P)],
            "country": np.array(COUNTRIES)[rng.integers(0, len(COUNTRIES), n_cust)],
            "signup_date": (rng.integers(0, 7 * 365, n_cust).astype("timedelta64[D]") + cust_start),
        }
    )
    return orders, customers


def main(sizes: list[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        n = SIZES[size]
        p = paths(size)
        t0 = time.perf_counter()
        orders, customers = make(n)
        orders.write_parquet(p["orders_parquet"])
        customers.write_parquet(p["customers_parquet"])
        orders.write_csv(p["orders_csv"], datetime_format="%Y-%m-%d %H:%M:%S")
        customers.write_csv(p["customers_csv"])
        sizes_mb = {k: round(v.stat().st_size / 1e6, 1) for k, v in p.items()}
        print(f"{size}: {n:,} orders, {n // 10:,} customers in {time.perf_counter() - t0:.1f}s {sizes_mb}")
        print(orders.head(3))


if __name__ == "__main__":
    main(sys.argv[1:] or list(SIZES))
