"""Check that every mode computes the same answer for every op (run on a small size).

For each op we reduce the result to a canonical, order-independent fingerprint
(row count, column set, sorted key/value sums) and compare all modes against pandas.

Usage: python validate.py 1M
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd
import polars as pl

from common import RESULTS, paths
from ops import IO_OPS, MEM_OPS, MODES, PANDAS_EXTRA, PIPE_OPS, get_ops


def to_pandas(df) -> pd.DataFrame:
    return df.to_pandas() if isinstance(df, pl.DataFrame) else df.reset_index(drop=True)


def num(x) -> float:
    return float(np.nansum(np.asarray(x, dtype="float64")))


def fingerprint(op: str, df) -> dict:
    d = to_pandas(df)
    fp = {"rows": len(d), "cols": sorted(map(str, d.columns))}
    if op in ("read_csv", "read_csv_arrow", "read_parquet", "filter", "join"):
        fp["sum_unit_price"] = num(d["unit_price"])
        fp["sum_order_id"] = int(d["order_id"].sum())
        fp["sum_ts_s"] = int(d["ts"].astype("datetime64[s]").astype("int64").sum())
        fp["n_null_discount"] = int(d["discount"].isna().sum())
        fp["dtypes"] = {c: str(t) for c, t in d.dtypes.items()}
    if op == "join":
        fp["n_country"] = int(d["country"].nunique())
    if op in ("groupby_low", "groupby_high"):
        key = ["store", "status"] if op == "groupby_low" else ["customer_id"]
        s = d.sort_values(key).reset_index(drop=True)
        fp["revenue_sum"] = num(s["revenue"])
        fp["orders_sum"] = int(s["orders"].sum())
        fp["first_row_revenue"] = float(s["revenue"].iloc[0])
        if "avg_discount" in s:
            fp["avg_discount_mean"] = float(s["avg_discount"].mean())
    if op == "sort":
        fp["first_keys"] = d[["customer_id"]].head(5).to_numpy().ravel().tolist()
        fp["is_sorted"] = bool(
            (d["customer_id"].diff().fillna(0) >= 0).all()
            and d.groupby("customer_id")["ts"].apply(lambda s: s.is_monotonic_increasing).all()
        )
    if op == "window":
        s = d.sort_values("order_id")
        fp["sum_abs_dev"] = num(s["price_vs_cust_avg"].abs())
        fp["sum_cum_qty"] = int(s["cum_qty"].sum())
        fp["cum_qty_last5"] = s["cum_qty"].tail(5).astype(int).tolist()
    if op.startswith("pipeline"):
        s = d.sort_values(["country", "segment"]).reset_index(drop=True)
        fp["revenue"] = [float(v) for v in s["revenue"]]
        fp["orders"] = s["orders"].astype(int).tolist()
        fp["avg_discount"] = [float(v) for v in s["avg_discount"]]
        fp["top_country"] = str(d.iloc[0]["country"])
    return fp


def comparable(fp: dict) -> dict:
    # dtype names differ by library by design; compare them separately (printed).
    return {k: v for k, v in fp.items() if k != "dtypes"}


def main(size: str) -> None:
    p = paths(size)
    all_ops = IO_OPS + MEM_OPS + PIPE_OPS
    fps: dict[str, dict[str, dict]] = {}
    for mode in MODES:
        ops = get_ops(mode)
        ctx = {"p": p, **ops["_load"](p)}
        names = all_ops + (PANDAS_EXTRA if mode == "pandas" else [])
        fps[mode] = {op: fingerprint(op, ops[op](ctx)) for op in names}

    ok = True
    report = {}
    for op in all_ops + PANDAS_EXTRA:
        base_mode = "pandas"
        base_op = op
        ref = comparable(fps["pandas"][op.replace("_arrow", "").replace("_tuned", "")])
        for mode in MODES:
            if op not in fps[mode]:
                continue
            got = comparable(fps[mode][op])
            same = True
            diffs = {}
            for k in ref:
                a, b = ref[k], got.get(k)
                if isinstance(a, float) and isinstance(b, float):
                    eq = math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
                elif isinstance(a, list) and a and isinstance(a[0], float):
                    eq = len(a) == len(b) and all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-6) for x, y in zip(a, b))
                else:
                    eq = a == b
                if not eq:
                    same = False
                    diffs[k] = (a, b)
            report[f"{op}/{mode}"] = "same" if same else diffs
            ok &= same
            print(f"{op:24s} {mode:18s} {'same as pandas' if same else 'DIFFERENT: ' + str(diffs)}")
    for mode in MODES:
        print(mode, "read_parquet dtypes:", fps[mode]["read_parquet"]["dtypes"])
        print(mode, "read_csv dtypes:", fps[mode]["read_csv"]["dtypes"])
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"validation_{size}.json").write_text(json.dumps({"ok": ok, "report": report, "fingerprints": fps}, indent=1, default=str))
    print("ALL SAME" if ok else "MISMATCHES FOUND")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "1M")
