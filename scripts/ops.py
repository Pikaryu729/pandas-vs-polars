"""Benchmark workloads, written once per library mode.

Modes
  pandas             pandas 3.x, default settings (NumPy-backed, pyarrow str dtype)
  polars-eager       Polars DataFrame API (always runs on the in-memory engine)
  polars-lazy        Polars LazyFrame + .collect() with no engine argument
                     (in Polars 2.0 "auto" resolves to the streaming engine)
  polars-lazy-inmem  Polars LazyFrame + .collect(engine="in-memory")

Every op takes a context dict and returns a DataFrame.
In-memory ops ("filter" .. "window") start from frames already loaded from Parquet.
IO ops and pipelines start from files on disk.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

CUTOFF = datetime(2025, 10, 1)  # Q4 2025
PIPE_ORDER_COLS = ["order_id", "ts", "customer_id", "status", "quantity", "unit_price", "discount"]
PIPE_CUST_COLS = ["customer_id", "segment", "country"]

IO_OPS = ["read_csv", "read_parquet"]
MEM_OPS = ["filter", "groupby_low", "groupby_high", "join", "sort", "window"]
PIPE_OPS = ["pipeline_parquet", "pipeline_csv"]
PANDAS_EXTRA = ["read_csv_arrow", "pipeline_parquet_tuned", "pipeline_csv_tuned"]


# --------------------------------------------------------------------------- pandas
def pandas_ops() -> dict[str, Callable]:
    import pandas as pd

    def load(p):
        return {"orders": pd.read_parquet(p["orders_parquet"]), "customers": pd.read_parquet(p["customers_parquet"])}

    def read_csv(c):
        return pd.read_csv(c["p"]["orders_csv"], parse_dates=["ts"])

    def read_csv_arrow(c):
        return pd.read_csv(c["p"]["orders_csv"], parse_dates=["ts"], engine="pyarrow")

    def read_parquet(c):
        return pd.read_parquet(c["p"]["orders_parquet"])

    def filt(c):
        o = c["orders"]
        return o[(o["status"] == "delivered") & (o["unit_price"] > 50) & o["channel"].isin(["web", "app"])]

    def groupby_low(c):
        o = c["orders"]
        return (
            o.assign(revenue=o["quantity"] * o["unit_price"])
            .groupby(["store", "status"], sort=False)
            .agg(revenue=("revenue", "sum"), avg_discount=("discount", "mean"), orders=("order_id", "count"))
            .reset_index()
        )

    def groupby_high(c):
        o = c["orders"]
        return (
            o.assign(revenue=o["quantity"] * o["unit_price"])
            .groupby("customer_id", sort=False)
            .agg(revenue=("revenue", "sum"), orders=("order_id", "count"), last_order=("ts", "max"))
            .reset_index()
        )

    def join(c):
        return c["orders"].merge(c["customers"], on="customer_id", how="inner")

    def sort(c):
        return c["orders"].sort_values(["customer_id", "ts"])

    def window(c):
        o = c["orders"]
        g = o.groupby("customer_id", sort=False)
        return o.assign(
            price_vs_cust_avg=o["unit_price"] - g["unit_price"].transform("mean"),
            cum_qty=g["quantity"].cumsum(),
        )

    def _pipeline_rest(o, cust):
        o = o[(o["status"] == "delivered") & (o["ts"] >= CUTOFF)]
        m = o.merge(cust, on="customer_id", how="inner")
        m = m.assign(revenue=m["quantity"] * m["unit_price"] * (1 - m["discount"].fillna(0)))
        return (
            m.groupby(["country", "segment"], sort=False)
            .agg(revenue=("revenue", "sum"), orders=("order_id", "count"), avg_discount=("discount", "mean"))
            .reset_index()
            .sort_values("revenue", ascending=False)
        )

    def pipeline_parquet(c):
        p = c["p"]
        return _pipeline_rest(pd.read_parquet(p["orders_parquet"]), pd.read_parquet(p["customers_parquet"]))

    def pipeline_parquet_tuned(c):
        # What a careful pandas user can do by hand: column + row-group pushdown in the reader.
        p = c["p"]
        o = pd.read_parquet(
            p["orders_parquet"],
            columns=PIPE_ORDER_COLS,
            filters=[("status", "==", "delivered"), ("ts", ">=", CUTOFF)],
        )
        cust = pd.read_parquet(p["customers_parquet"], columns=PIPE_CUST_COLS)
        return _pipeline_rest(o, cust)

    def pipeline_csv(c):
        p = c["p"]
        return _pipeline_rest(pd.read_csv(p["orders_csv"], parse_dates=["ts"]), pd.read_csv(p["customers_csv"]))

    def pipeline_csv_tuned(c):
        # Hand-tuned: read only needed columns, with the multithreaded pyarrow CSV engine.
        p = c["p"]
        o = pd.read_csv(p["orders_csv"], usecols=PIPE_ORDER_COLS, parse_dates=["ts"], engine="pyarrow")
        cust = pd.read_csv(p["customers_csv"], usecols=PIPE_CUST_COLS, engine="pyarrow")
        return _pipeline_rest(o, cust)

    return {
        "_load": load,
        "read_csv": read_csv,
        "read_csv_arrow": read_csv_arrow,
        "read_parquet": read_parquet,
        "filter": filt,
        "groupby_low": groupby_low,
        "groupby_high": groupby_high,
        "join": join,
        "sort": sort,
        "window": window,
        "pipeline_parquet": pipeline_parquet,
        "pipeline_parquet_tuned": pipeline_parquet_tuned,
        "pipeline_csv": pipeline_csv,
        "pipeline_csv_tuned": pipeline_csv_tuned,
    }


# --------------------------------------------------------------------------- polars
def _polars_queries():
    """Each query is a function LazyFrame(s) -> LazyFrame; eager mode runs the same
    expressions through the DataFrame API instead."""
    import polars as pl

    revenue = (pl.col("quantity") * pl.col("unit_price")).alias("revenue")

    def filt(o):
        return o.filter(
            (pl.col("status") == "delivered") & (pl.col("unit_price") > 50) & pl.col("channel").is_in(["web", "app"])
        )

    def groupby_low(o):
        return o.with_columns(revenue).group_by(["store", "status"]).agg(
            pl.col("revenue").sum(), pl.col("discount").mean().alias("avg_discount"), pl.col("order_id").count().alias("orders")
        )

    def groupby_high(o):
        return o.with_columns(revenue).group_by("customer_id").agg(
            pl.col("revenue").sum(), pl.col("order_id").count().alias("orders"), pl.col("ts").max().alias("last_order")
        )

    def join(o, cust):
        return o.join(cust, on="customer_id", how="inner")

    def sort(o):
        return o.sort(["customer_id", "ts"])

    def window(o):
        return o.with_columns(
            (pl.col("unit_price") - pl.col("unit_price").mean().over("customer_id")).alias("price_vs_cust_avg"),
            pl.col("quantity").cum_sum().over("customer_id").alias("cum_qty"),
        )

    def pipeline_rest(o, cust):
        return (
            o.filter((pl.col("status") == "delivered") & (pl.col("ts") >= CUTOFF))
            .join(cust, on="customer_id", how="inner")
            .with_columns(
                (pl.col("quantity") * pl.col("unit_price") * (1 - pl.col("discount").fill_null(0))).alias("revenue")
            )
            .group_by(["country", "segment"])
            .agg(
                pl.col("revenue").sum(),
                pl.col("order_id").count().alias("orders"),
                pl.col("discount").mean().alias("avg_discount"),
            )
            .sort("revenue", descending=True)
        )

    return pl, filt, groupby_low, groupby_high, join, sort, window, pipeline_rest


def polars_ops(mode: str) -> dict[str, Callable]:
    pl, filt, groupby_low, groupby_high, join, sort, window, pipeline_rest = _polars_queries()

    def load(p):
        return {"orders": pl.read_parquet(p["orders_parquet"]), "customers": pl.read_parquet(p["customers_parquet"])}

    if mode == "polars-eager":
        return {
            "_load": load,
            "read_csv": lambda c: pl.read_csv(c["p"]["orders_csv"], try_parse_dates=True),
            "read_parquet": lambda c: pl.read_parquet(c["p"]["orders_parquet"]),
            "filter": lambda c: filt(c["orders"]),
            "groupby_low": lambda c: groupby_low(c["orders"]),
            "groupby_high": lambda c: groupby_high(c["orders"]),
            "join": lambda c: join(c["orders"], c["customers"]),
            "sort": lambda c: sort(c["orders"]),
            "window": lambda c: window(c["orders"]),
            "pipeline_parquet": lambda c: pipeline_rest(
                pl.read_parquet(c["p"]["orders_parquet"]), pl.read_parquet(c["p"]["customers_parquet"])
            ),
            "pipeline_csv": lambda c: pipeline_rest(
                pl.read_csv(c["p"]["orders_csv"], try_parse_dates=True),
                pl.read_csv(c["p"]["customers_csv"], try_parse_dates=True),
            ),
        }

    if mode == "polars-lazy":
        collect = lambda lf: lf.collect()  # noqa: E731  (default engine = "auto")
    elif mode == "polars-lazy-inmem":
        collect = lambda lf: lf.collect(engine="in-memory")  # noqa: E731
    else:
        raise ValueError(mode)

    return {
        "_load": load,
        "read_csv": lambda c: collect(pl.scan_csv(c["p"]["orders_csv"], try_parse_dates=True)),
        "read_parquet": lambda c: collect(pl.scan_parquet(c["p"]["orders_parquet"])),
        "filter": lambda c: collect(filt(c["orders"].lazy())),
        "groupby_low": lambda c: collect(groupby_low(c["orders"].lazy())),
        "groupby_high": lambda c: collect(groupby_high(c["orders"].lazy())),
        "join": lambda c: collect(join(c["orders"].lazy(), c["customers"].lazy())),
        "sort": lambda c: collect(sort(c["orders"].lazy())),
        "window": lambda c: collect(window(c["orders"].lazy())),
        "pipeline_parquet": lambda c: collect(
            pipeline_rest(pl.scan_parquet(c["p"]["orders_parquet"]), pl.scan_parquet(c["p"]["customers_parquet"]))
        ),
        "pipeline_csv": lambda c: collect(
            pipeline_rest(
                pl.scan_csv(c["p"]["orders_csv"], try_parse_dates=True),
                pl.scan_csv(c["p"]["customers_csv"], try_parse_dates=True),
            )
        ),
    }


MODES = ["pandas", "polars-eager", "polars-lazy", "polars-lazy-inmem"]


def get_ops(mode: str) -> dict[str, Callable]:
    return pandas_ops() if mode == "pandas" else polars_ops(mode)


def frame_bytes(df) -> int:
    """In-memory size of a result frame as reported by the library itself."""
    if hasattr(df, "estimated_size"):
        return int(df.estimated_size())
    return int(df.memory_usage(deep=True).sum())
