"""Render standalone 1600x900 PNG and font-independent SVG slides from summary.json.

Usage: python scripts/render_charts.py [--summary results/summary.json] [--output charts]
No private paths or current timestamps are embedded in generated slides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import ROOT

OPS = ["read_csv", "read_parquet", "filter", "groupby_low", "groupby_high", "join", "sort", "window", "pipeline_parquet", "pipeline_csv"]
LABELS = ["Read CSV", "Read Parquet", "Filter", "Group-by: 1,000 groups", "Group-by: per customer", "Join orders to customers", "Sort by two keys", "Window per customer", "Query from Parquet", "Query from CSV"]
PANDAS, EAGER, LAZY, INMEM = "pandas", "polars-eager", "polars-lazy", "polars-lazy-inmem"
COLORS = ["#64748b", "#b96b13", "#007e83", "#7c3aed"]
CHART_NAMES = ("01-timings-50m", "02-scaling", "03-tuned-pandas", "04-memory-50m", "05-threads-10m", "06-polars-engines")


def render(summary: Path, output: Path) -> None:
    s = json.loads(summary.read_text())
    t, m = s["timing"], s["memory"]
    env_path = summary.parent / "environment.json"
    env = json.loads(env_path.read_text()) if env_path.exists() else {}
    hw = env.get("hardware", {})
    core_count = str(hw.get("Total Number of Cores", env.get("logical_cpus", ""))).split(" ")[0]
    machine = " · ".join(str(v) for v in (hw.get("Model Name"), hw.get("Chip"),
                        f"{core_count} cores" if core_count else None, hw.get("Memory")) if v)
    software = f"Polars {env.get('polars', '?')} / pandas {env.get('pandas', '?')}"
    footer = f"{machine or 'Hardware not supplied'} | {software} | Shared-machine results; background work may affect timings"
    def cell(size, mode, op, tag=""):
        return t[f"{size}|{mode}|{op}|{tag}"]
    def med(size, mode, op, tag=""):
        return cell(size, mode, op, tag)["median_s"]

    # Fail before producing partial slides if the full method was not run.
    for size in ("1M", "10M", "50M"):
        for op in OPS:
            for mode in (PANDAS, EAGER, LAZY):
                med(size, mode, op)
    for op in OPS:
        med("10M", LAZY, op, "1-thread")
        med("50M", INMEM, op)
        for mode in (PANDAS, EAGER, LAZY):
            m[f"50M|{mode}|{op}"]["median_peak_mb"]
    for op in ("read_csv_arrow", "pipeline_csv_tuned", "pipeline_parquet_tuned"):
        med("50M", PANDAS, op)
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 16, "axes.labelsize": 16,
                         "xtick.labelsize": 14, "ytick.labelsize": 16, "svg.fonttype": "path",
                         "svg.hashsalt": "polars-vs-pandas-bench", "axes.spines.top": False,
                         "axes.spines.right": False, "axes.spines.left": False})
    manifest = {"source": "summary.json", "summary_sha256": hashlib.sha256(summary.read_bytes()).hexdigest(), "charts": []}

    def frame(title, subtitle, labels=LABELS):
        fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
        fig.patch.set_facecolor("white")
        fig.subplots_adjust(left=.29, right=.95, bottom=.18, top=.75)
        fig.text(.035, .95, title, fontsize=24, weight="bold", color="#182434", va="top")
        fig.text(.035, .90, subtitle, fontsize=15, color="#475569", va="top")
        fig.text(.035, .04, footer, fontsize=12, color="#475569")
        ax.set_yticks(range(len(labels)), labels)
        ax.set_ylim(len(labels)-.4, -.6)
        ax.tick_params(axis="y", length=0, pad=12)
        ax.grid(axis="x", color="#e2e8f0")
        ax.set_axisbelow(True)
        return fig, ax

    def save(fig, name, alt):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        # Catch cropped slide text, including changes to hardware captions.
        for text in fig.findobj(matplotlib.text.Text):
            if not text.get_visible() or not text.get_text():
                continue
            box = text.get_window_extent(renderer)
            if box.x0 < -1 or box.y0 < -1 or box.x1 > 1601 or box.y1 > 901:
                raise ValueError(f"Slide text does not fit: {text.get_text()}")
        fig.savefig(output / f"{name}.png", dpi=100, facecolor="white", metadata={"Software": "polars-vs-pandas-bench"})
        svg = output / f"{name}.svg"
        fig.savefig(svg, facecolor="white", metadata={"Date": None, "Creator": "polars-vs-pandas-bench", "Description": alt})
        # Matplotlib emits trailing spaces in path data; retain geometry, not whitespace.
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
        plt.close(fig)
        manifest["charts"].append({"name": name, "description": alt, "png": f"{name}.png", "svg": f"{name}.svg"})

    def dots(ax, values, y, color, label, marker="o", spread=None):
        if spread:
            ax.hlines(y, [v[0] for v in spread], [v[1] for v in spread], color=color, linewidth=3, alpha=.5)
        ax.scatter(values, y, s=90, color=color, marker=marker, label=label, zorder=3)

    def log_limits(ax, lo, hi):
        ax.set_xscale("log")
        data_lo, data_hi = ax.dataLim.intervalx
        ax.set_xlim(min(lo, data_lo / 1.15), max(hi, data_hi * 1.15))

    def legend(ax, cols=3):
        ax.legend(loc="lower left", bbox_to_anchor=(-.02, 1.02), ncol=cols, frameon=False, fontsize=14, columnspacing=1.2)

    y = np.arange(len(OPS))
    fig, ax = frame("Median workload timings at 50M orders", "Median wall time; whiskers show min–max · Lower is faster · Log scale")
    for j, (mode, label, marker) in enumerate(((PANDAS,"pandas","o"),(EAGER,"Polars eager","s"),(LAZY,"Polars lazy","D"))):
        vals = [med("50M", mode, op) for op in OPS]
        spread = [(cell("50M",mode,op)["min_s"],cell("50M",mode,op)["max_s"]) for op in OPS]
        dots(ax, vals, y+(j-1)*.20, COLORS[j], label, marker, spread)
    log_limits(ax, .025, 60)
    ax.set_xticks([.03,.1,.3,1,3,10,30], ["30 ms","0.1 s","0.3 s","1 s","3 s","10 s","30 s"])
    ax.set_xlabel("Wall time (seconds)")
    legend(ax)
    save(fig, CHART_NAMES[0], "Median times for all 10 workloads at 50M orders, pandas, Polars eager and Polars lazy; min–max spans.")

    fig, ax = frame("Polars lazy speedup across three data sizes", "Ratio = default pandas median / Polars lazy median · Above 1× favors Polars · Log scale")
    for j,size in enumerate(("1M","10M","50M")):
        dots(ax,[med(size,PANDAS,op)/med(size,LAZY,op) for op in OPS],y+(j-1)*.20,COLORS[j],f"{size} orders",["o","s","D"][j])
    log_limits(ax, .5, 60)
    ax.set_xticks([.5,1,2,5,10,20,50],["0.5×","1×","2×","5×","10×","20×","50×"])
    ax.axvline(1,color="#182434",linewidth=1.5);ax.set_xlabel("Speedup relative to default pandas")
    legend(ax)
    save(fig, CHART_NAMES[1], "Polars lazy versus default pandas speedups at 1M, 10M and 50M orders, for every workload.")

    tuned = {"read_csv":"read_csv_arrow","pipeline_csv":"pipeline_csv_tuned","pipeline_parquet":"pipeline_parquet_tuned"}
    fig, ax = frame("CSV and Parquet with tuned pandas", "50M orders · Arrow CSV reader; selected columns and Parquet filters · Median wall time · Log scale", ["Read CSV","Query from CSV","Query from Parquet"])
    yy=np.arange(3)
    values=[[med("50M",PANDAS,op) for op in tuned], [med("50M",PANDAS,v) for v in tuned.values()], [min(med("50M",EAGER,op),med("50M",LAZY,op)) for op in tuned]]
    for j,(vals,label) in enumerate(zip(values,("pandas default","pandas tuned","Polars (faster mode)"))):
        dots(ax,vals,yy+(j-1)*.15,COLORS[j],label,["o","s","D"][j])
        for i,v in enumerate(vals):ax.annotate(f"{v:.3f} s",(v,yy[i]+(j-1)*.15),xytext=(7,0),textcoords="offset points",va="center",fontsize=13,color=COLORS[j])
    log_limits(ax, .055, 100)
    ax.set_xticks([.1,.3,1,3,10,30],["0.1 s","0.3 s","1 s","3 s","10 s","30 s"]);ax.set_xlabel("Wall time (seconds)")
    legend(ax)
    save(fig, CHART_NAMES[2], "Tuned and default pandas against the faster Polars mode for CSV reading and CSV/Parquet queries at 50M orders.")

    fig, ax = frame("Memory savings depend on the workload and engine", "50M orders · Peak extra resident memory, not total RSS · Median of 3 fresh processes · Decimal GB")
    ax.set_position([.29, .18, .66, .62])
    for j,(mode,label) in enumerate(((PANDAS,"pandas"),(EAGER,"Polars eager"),(LAZY,"Polars lazy"))):
        vals=[m[f"50M|{mode}|{op}"]["median_peak_mb"]/1000 for op in OPS]
        ax.barh(y+(j-1)*.30,vals,height=.26,color=COLORS[j],label=label)
        for i,v in enumerate(vals):ax.text(v+.10,y[i]+(j-1)*.30,f"{v:.1f}",va="center",fontsize=11,color="#182434")
    ax.set_xlim(0, max(23, ax.dataLim.x1 * 1.12));ax.set_xticks(range(0,23,2));ax.set_xlabel("Peak RSS − baseline RSS (GB); in-memory inputs are loaded before baseline")
    legend(ax)
    save(fig, CHART_NAMES[3], "Peak RSS growth at 50M orders for all workloads and three library modes, median of three fresh processes, excluding preloaded inputs.")

    wins = sum(med("10M", PANDAS, op) > med("10M", LAZY, op, "1-thread") for op in OPS)
    threads = env.get("polars_thread_pool_size", "default")
    fig, ax = frame(f"One-thread Polars lazy wins {wins} of 10 workloads", "10M orders · Median wall time · Polars thread limit does not pin pandas or Arrow · Log scale")
    for j,(mode,tag,label) in enumerate(((PANDAS,"","pandas default"),(LAZY,"1-thread","Polars lazy: 1 thread"),(LAZY,"",f"Polars lazy: {threads} threads"))):
        dots(ax,[med("10M",mode,op,tag) for op in OPS],y+(j-1)*.20,COLORS[j],label,["o","s","D"][j])
    log_limits(ax, .005, 10)
    ax.set_xticks([.01,.03,.1,.3,1,3,10],["10 ms","30 ms","0.1 s","0.3 s","1 s","3 s","10 s"]);ax.set_xlabel("Wall time (seconds)")
    legend(ax)
    save(fig, CHART_NAMES[4], "All 10 workloads at 10M orders: pandas, Polars lazy with one thread and Polars lazy with 18 threads.")

    engine_ops=["groupby_low","groupby_high","join","sort","window","pipeline_parquet"]
    fig, ax = frame("Lazy versus eager is also an engine comparison", "50M orders · Default collect() uses streaming; eager uses in-memory · Log scale", [LABELS[OPS.index(op)] for op in engine_ops])
    yy=np.arange(len(engine_ops))
    for j,(mode,label,color) in enumerate(((EAGER,"Eager: in-memory",COLORS[1]),(INMEM,"Lazy: in-memory",COLORS[3]),(LAZY,"Lazy: streaming",COLORS[2]))):
        dots(ax,[med("50M",mode,op) for op in engine_ops],yy+(j-1)*.20,color,label,["s","o","D"][j])
    log_limits(ax, .025, 4)
    ax.set_xticks([.03,.1,.3,1,3],["30 ms","0.1 s","0.3 s","1 s","3 s"]);ax.set_xlabel("Wall time (seconds)")
    legend(ax)
    save(fig, CHART_NAMES[5], "Polars eager, lazy in-memory and lazy streaming for six diagnostic workloads at 50M orders.")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(f"Rendered {len(manifest['charts'])} charts, each as PNG and SVG.")


if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary",type=Path,default=ROOT/"results"/"summary.json")
    ap.add_argument("--output",type=Path,default=ROOT/"charts")
    args=ap.parse_args()
    render(args.summary,args.output)
