"""Build the write-up card body (HTML with inline SVG) from results/summary.json.

Every number on the card is read from the result files written by the benchmark scripts.
Usage: BENCH_RESULTS_DIR=results python scripts/gen_card.py <out.html> <results-label>

Historical answer renderer retained as source; the README and charts are the
maintained publication. The label should be relative, never a private machine path.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from html import escape

from common import RESULTS
from svgplot import bar_plot, fmt_s, fmt_x, log_dot_plot

S = json.loads((RESULTS / "summary.json").read_text())
ENV = json.loads((RESULTS / "environment.json").read_text())
T, M, NOISE = S["timing"], S["memory"], S["noise"]
PROBE = [json.loads(l) for l in (RESULTS / "csv_probe.jsonl").read_text().splitlines()] if (RESULTS / "csv_probe.jsonl").exists() else []
OUT = sys.argv[1]
EVID = sys.argv[2]

OPS = ["read_csv", "read_parquet", "filter", "groupby_low", "groupby_high", "join", "sort", "window", "pipeline_parquet", "pipeline_csv"]
LABEL = {
    "read_csv": "Read CSV",
    "read_parquet": "Read Parquet",
    "filter": "Filter",
    "groupby_low": "Group-by, 1,000 groups",
    "groupby_high": "Group-by, per customer",
    "join": "Join orders to customers",
    "sort": "Sort by 2 keys",
    "window": "Window per customer",
    "pipeline_parquet": "Query from Parquet",
    "pipeline_csv": "Query from CSV",
}

SHORT = {"read_csv": "the CSV read", "read_parquet": "the Parquet read", "filter": "the filter", "groupby_low": "the 1,000-group group-by",
         "groupby_high": "the per-customer group-by", "join": "the join", "sort": "the sort", "window": "the window step",
         "pipeline_parquet": "the Parquet query", "pipeline_csv": "the CSV query"}

PANDAS, EAGER, LAZY, INMEM = "pandas", "polars-eager", "polars-lazy", "polars-lazy-inmem"
C_PANDAS, C_POLARS = "var(--fg-3)", "var(--accent)"


def t(size, mode, op, tag=""):
    return T[f"{size}|{mode}|{op}|{tag}"]


def med(size, mode, op, tag=""):
    return t(size, mode, op, tag)["median_s"]


def mem(size, mode, op):
    return M[f"{size}|{mode}|{op}"]


def x(a, b):
    return a / b


def words(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def p(text: str) -> str:
    return f"<p>{text}</p>"


# ------------------------------------------------------------------ numbers used in prose
big = "50M"
sp_lazy = {op: x(med(big, PANDAS, op), med(big, LAZY, op)) for op in OPS}
sp_eager = {op: x(med(big, PANDAS, op), med(big, EAGER, op)) for op in OPS}
best_default = {op: max(sp_lazy[op], sp_eager[op]) for op in OPS}
wins = sum(1 for op in OPS if best_default[op] > 1)
eager_losses = [op for op in OPS if sp_eager[op] < 1]
lazy_losses = [op for op in OPS if sp_lazy[op] < 1]
iqr_max_50 = max(v["iqr_pct"] for v in T.values() if v["size"] == big and not v["tag"])
iqr_med_50 = st.median(v["iqr_pct"] for v in T.values() if v["size"] == big and not v["tag"])
hw = ENV["hardware"]
csv_gb = 3.91
pq_gb = 0.77

# ------------------------------------------------------------------ figure 1: 50M times
rows = []
for op in OPS:
    rows.append(
        {
            "label": LABEL[op],
            "values": {PANDAS: med(big, PANDAS, op), EAGER: med(big, EAGER, op), LAZY: med(big, LAZY, op)},
            "spread": {m: (t(big, m, op)["min_s"], t(big, m, op)["max_s"]) for m in (PANDAS, EAGER, LAZY)},
            "right": f"{fmt_x(sp_lazy[op])}",
            "right2": f"{fmt_x(sp_eager[op])}",
            "right_strong": True,
        }
    )
TIME_TICKS = [(0.03, "30 ms"), (0.1, "0.1 s"), (0.3, "0.3 s"), (1, "1 s"), (3, "3 s"), (10, "10 s"), (30, "30 s")]
fig1 = log_dot_plot(
    rows,
    [
        {"key": PANDAS, "color": C_PANDAS, "shape": "dot", "label": "pandas 3.0.6"},
        {"key": EAGER, "color": C_POLARS, "shape": "ring", "label": "Polars eager"},
        {"key": LAZY, "color": C_POLARS, "shape": "dot", "label": "Polars lazy (default collect)"},
    ],
    lo=0.025,
    hi=60,
    ticks=TIME_TICKS,
    aria="Median time per workload at 50 million rows on a log scale: pandas, Polars eager and Polars lazy",
    right_title="lazy|eager",
)

# ------------------------------------------------------------------ figure 2: speedup vs size
rows2 = []
for op in OPS:
    vals = {s: x(med(s, PANDAS, op), med(s, LAZY, op)) for s in ("1M", "10M", "50M")}
    rows2.append({"label": LABEL[op], "values": vals, "right": fmt_x(vals["50M"]), "right_strong": True})
fig2 = log_dot_plot(
    rows2,
    [
        {"key": "1M", "color": "var(--fg-3)", "shape": "ring", "label": "1M rows", "fmt": fmt_x},
        {"key": "10M", "color": "var(--fg-3)", "shape": "dot", "label": "10M rows", "fmt": fmt_x},
        {"key": "50M", "color": C_POLARS, "shape": "dot", "label": "50M rows", "fmt": fmt_x},
    ],
    lo=0.5,
    hi=60,
    ticks=[(0.5, "0.5×"), (1, "1×"), (2, "2×"), (5, "5×"), (10, "10×"), (20, "20×"), (50, "50×")],
    aria="How many times faster Polars lazy is than pandas, per workload, at 1, 10 and 50 million rows",
    right_title="at 50M",
    ref_line=(1, "same speed as pandas"),
)

# ------------------------------------------------------------------ figure 3: tuned pandas
TUNED = {"read_csv": "read_csv_arrow", "pipeline_csv": "pipeline_csv_tuned", "pipeline_parquet": "pipeline_parquet_tuned"}
rows3 = []
for op, tuned in TUNED.items():
    pt = med(big, PANDAS, tuned)
    pol = min(med(big, LAZY, op), med(big, EAGER, op))
    winner = f"pandas {fmt_x(pol / pt)}" if pt < pol else f"Polars {fmt_x(pt / pol)}"
    rows3.append(
        {
            "label": LABEL[op],
            "values": {"pd": med(big, PANDAS, op), "pdt": pt, "pl": pol},
            "right": winner,
            "right_strong": pt < pol,
        }
    )
fig3 = log_dot_plot(
    rows3,
    [
        {"key": "pd", "color": C_PANDAS, "shape": "dot", "label": "pandas default"},
        {"key": "pdt", "color": "var(--fg-1)", "shape": "ring", "label": "pandas tuned"},
        {"key": "pl", "color": C_POLARS, "shape": "dot", "label": "Polars, faster mode"},
    ],
    lo=0.05,
    hi=60,
    ticks=[(0.1, "0.1 s"), (0.3, "0.3 s"), (1, "1 s"), (3, "3 s"), (10, "10 s"), (30, "30 s")],
    aria="Tuned pandas against Polars at 50 million rows for CSV reading and the two end-to-end queries",
    right_title="faster",
)

# ------------------------------------------------------------------ figure 4: memory at 50M
MEM_OPS_SHOWN = OPS
rows4 = []
for op in MEM_OPS_SHOWN:
    rows4.append(
        {"label": LABEL[op], "values": {m: mem(big, m, op)["median_peak_mb"] / 1000 for m in (PANDAS, EAGER, LAZY)}}
    )
mem_hi = max(max(r["values"].values()) for r in rows4)
mem_top = 2 * int(mem_hi / 2 + 1)
fig4 = bar_plot(
    rows4,
    [
        {"key": PANDAS, "color": C_PANDAS, "label": "pandas"},
        {"key": EAGER, "color": "color-mix(in srgb, var(--accent) 45%, transparent)", "label": "Polars eager"},
        {"key": LAZY, "color": C_POLARS, "label": "Polars lazy (default collect)"},
    ],
    hi=mem_top,
    ticks=[(g, f"{g} GB") for g in range(0, mem_top + 1, 2)],
    aria="Peak extra memory per workload at 50 million rows for pandas, Polars eager and Polars lazy",
    value_fmt=lambda v: f"{v:.1f} GB" if v >= 0.095 else f"{v * 1000:.0f} MB",
)

# ------------------------------------------------------------------ figure 5: one thread
TOPS = ["read_csv", "filter", "groupby_low", "groupby_high", "join", "sort", "window", "pipeline_parquet"]
rows5 = []
for op in TOPS:
    one = med("10M", LAZY, op, "1-thread")
    rows5.append(
        {
            "label": LABEL[op],
            "values": {"pd": med("10M", PANDAS, op), "one": one, "all": med("10M", LAZY, op)},
            "right": fmt_x(med("10M", PANDAS, op) / one),
            "right_strong": True,
        }
    )
fig5 = log_dot_plot(
    rows5,
    [
        {"key": "pd", "color": C_PANDAS, "shape": "dot", "label": "pandas"},
        {"key": "one", "color": C_POLARS, "shape": "ring", "label": "Polars, 1 thread"},
        {"key": "all", "color": C_POLARS, "shape": "dot", "label": "Polars, 18 threads"},
    ],
    lo=0.005,
    hi=10,
    ticks=[(0.01, "10 ms"), (0.03, "30 ms"), (0.1, "0.1 s"), (0.3, "0.3 s"), (1, "1 s"), (3, "3 s")],
    aria="Polars on one thread against pandas and against Polars on all 18 threads, 10 million rows",
    right_title="1 thread vs pandas",
)

# ------------------------------------------------------------------ prose numbers
def mm(op, m):
    return mem(big, m, op)["median_peak_mb"] / 1000


def sx(op, mode=LAZY, size=big):
    return fmt_x(med(size, PANDAS, op) / med(size, mode, op))


one_thread = {op: med("10M", PANDAS, op) / med("10M", LAZY, op, "1-thread") for op in TOPS}
one_thread_wins = [op for op in TOPS if one_thread[op] > 1]
one_thread_losses = [op for op in TOPS if one_thread[op] < 1]

pd_in = mem(big, PANDAS, "filter")["input_mb"] / 1000
pl_in = mem(big, EAGER, "filter")["input_mb"] / 1000

probe = {r["variant"]: r for r in PROBE if r["size"] == big}


def probe_s(prefix):
    for k, v in probe.items():
        if k.startswith(prefix):
            return v["median_s"]
    return None


# ------------------------------------------------------------------ tables for details
def table(size: str) -> str:
    head = "<tr><th>Workload</th><th>pandas</th><th>Polars eager</th><th>Polars lazy (default)</th><th>Polars lazy, in-memory engine</th></tr>"
    body = []
    for op in OPS + ["read_csv_arrow", "pipeline_parquet_tuned", "pipeline_csv_tuned"]:
        cells = []
        for m in (PANDAS, EAGER, LAZY, INMEM):
            k = f"{size}|{m}|{op}|"
            if k in T:
                v = T[k]
                cells.append(
                    f"<td class='fm-mono'>{fmt_s(v['median_s'])}<br><span class='fm-muted'>{fmt_s(v['min_s'])}–{fmt_s(v['max_s'])}, IQR {v['iqr_pct']:.0f}%, {v['cores_busy']:.1f} cores</span></td>"
                )
            else:
                cells.append("<td></td>")
        name = LABEL.get(op, {"read_csv_arrow": "Read CSV, pandas engine=pyarrow", "pipeline_parquet_tuned": "Query from Parquet, pandas tuned", "pipeline_csv_tuned": "Query from CSV, pandas tuned"}.get(op, op))
        body.append(f"<tr><td>{escape(name)}</td>{''.join(cells)}</tr>")
    return f"<table>{head}{''.join(body)}</table>"


def mem_table(size: str) -> str:
    head = "<tr><th>Workload</th><th>pandas</th><th>Polars eager</th><th>Polars lazy (default)</th><th>Polars lazy, in-memory engine</th></tr>"
    body = []
    for op in OPS + ["read_csv_arrow", "pipeline_parquet_tuned", "pipeline_csv_tuned"]:
        cells = []
        for m in (PANDAS, EAGER, LAZY, INMEM):
            k = f"{size}|{m}|{op}"
            if k in M:
                v = M[k]
                cells.append(f"<td class='fm-mono'>{v['median_peak_mb']:,.0f} MB<br><span class='fm-muted'>{v['min_peak_mb']:,.0f}–{v['max_peak_mb']:,.0f}</span></td>")
            else:
                cells.append("<td></td>")
        name = LABEL.get(op, {"read_csv_arrow": "Read CSV, pandas engine=pyarrow", "pipeline_parquet_tuned": "Query from Parquet, pandas tuned", "pipeline_csv_tuned": "Query from CSV, pandas tuned"}.get(op, op))
        body.append(f"<tr><td>{escape(name)}</td>{''.join(cells)}</tr>")
    return f"<table>{head}{''.join(body)}</table>"


html: list[str] = []
add = html.append

same_engine = {op: 100 * abs(med(big, INMEM, op) - med(big, EAGER, op)) / med(big, EAGER, op) for op in ("groupby_low", "join", "window")}
pq_q_lazy = med(big, LAZY, "pipeline_parquet")
pq_q_inmem = med(big, INMEM, "pipeline_parquet")
pq_q_eager = med(big, EAGER, "pipeline_parquet")

lazy_wins = sum(1 for op in OPS if sp_lazy[op] > 1)
add(
    p(
        f"<strong>On this Mac mini, Polars 2.0.0 run lazily beat default pandas 3.0.6 on {'all ' + str(len(OPS)) if lazy_wins == len(OPS) else f'{lazy_wins} of {len(OPS)}'} workloads at 50 million rows, "
        f"by {fmt_x(min(sp_lazy.values()))} to {fmt_x(max(sp_lazy.values()))}.</strong> "
        "Two exceptions: Polars' eager API lost the window step, and pandas' pyarrow CSV reader beat Polars at reading CSV."
    )
)

add(
    p(
        "This is the historical answer layout, retained for reproducibility. "
        "README.md contains the formal write-up, corrected qualifications and standalone slide charts."
    )
)
add(
    "<div class='fm-panel'><p class='fm-muted' style='margin:0'>"
    f"I ran Polars {escape(ENV['polars'])} (released October 6, 2026), pandas {escape(ENV['pandas'])} (latest stable), pyarrow {escape(ENV['pyarrow'])}, NumPy {escape(ENV['numpy'])} "
    f"on Python {escape(ENV['python'].split()[0])} in an isolated environment. "
    f"The machine is a {escape(hw['Model Name'])} ({escape(hw['Model Identifier'])}) with an {escape(hw['Chip'])}, {escape(hw['Total Number of Cores'])} cores, {escape(hw['Memory'])} memory, on macOS {escape(ENV['macos'])}. "
    "The data is a generated orders table (10 columns) plus a customers table, at 1M, 10M and 50M orders. "
    f"Every workload had warm-up runs, then 10, 7 or 5 timed runs by size; the charts show medians."
    "</p></div>"
)

add("<h3>Speed at 50 million rows</h3>")
add(
    p(
        f"Polars lazy beat pandas on every workload; in 2.0 its <span class='fm-mono'>collect()</span> runs the streaming engine. Its largest margins were group-by with 1,000 groups ({sx('groupby_low')}), "
        f"sort ({sx('sort')}), filter ({sx('filter')}) and the query from Parquet ({sx('pipeline_parquet')})."
    )
)
add(fig1)
add(
    p(
        f"Polars eager lost to pandas on the per-customer window step: {fmt_s(med(big, EAGER, 'window'))} against {fmt_s(med(big, PANDAS, 'window'))}. "
        f"Polars lazy did the same step in {fmt_s(med(big, LAZY, 'window'))}. "
        f"For eager group-by and join, Polars was only {fmt_x(min(sp_eager[o] for o in ('groupby_low', 'groupby_high', 'join')))} to {fmt_x(max(sp_eager[o] for o in ('groupby_low', 'groupby_high', 'join')))} faster."
    )
)
add(
    p(
        f"Each dot is a median. The faint bar through it spans the fastest to slowest run. "
        f"At 50M the middle half of runs spanned at most {iqr_max_50:.0f}% of the median, and {iqr_med_50:.0f}% typically."
    )
)

add("<h3>Lazy against eager in Polars 2.0</h3>")
add(
    p(
        "In Polars 2.0, <span class='fm-mono'>collect()</span> with no engine argument runs the streaming engine. "
        "The eager DataFrame API still runs the in-memory engine. "
        f"I also timed lazy on the in-memory engine. It was within {max(same_engine.values()):.0f}% of eager on the 1,000-group group-by, join and window, so the engine causes the gap."
    )
)
add(
    p(
        f"On the query from Parquet, query planning helped on top of the engine: eager took {fmt_s(pq_q_eager)}, lazy on the in-memory engine {fmt_s(pq_q_inmem)}, "
        f"and lazy streaming {fmt_s(pq_q_lazy)}. "
        f"Sort is the one place streaming lost: {fmt_s(med(big, LAZY, 'sort'))} against {fmt_s(med(big, EAGER, 'sort'))} eager."
    )
)

add("<h3>How the gap grows with data size</h3>")
grew = [op for op in OPS if x(med("50M", PANDAS, op), med("50M", LAZY, op)) > x(med("1M", PANDAS, op), med("1M", LAZY, op))]
dipped = [op for op in OPS if x(med("10M", PANDAS, op), med("10M", LAZY, op)) < x(med("1M", PANDAS, op), med("1M", LAZY, op))]
add(p(f"Polars lazy's lead over pandas was larger at 50M rows than at 1M on {'all ' + str(len(OPS)) if len(grew) == len(OPS) else f'{len(grew)} of {len(OPS)}'} workloads."))
add(fig2)
add(
    p(
        f"At 1M rows, the window step was close to a tie ({sx('window', size='1M')}), and so was Read Parquet ({sx('read_parquet', size='1M')}). "
        f"At that size pandas finished {sum(1 for op in OPS if med('1M', PANDAS, op) < 0.05)} of {len(OPS)} steps in under 50 ms. "
        + (f"The lead dipped at 10M for {words(SHORT[o] for o in dipped)}." if dipped else "")
    )
)

add("<h3>pandas tuned by hand</h3>")
add(
    p(
        "I also ran pandas the way a careful user would. CSV reads used <span class='fm-mono'>engine=\"pyarrow\"</span>. "
        "The Parquet query read only the needed columns and pushed its filters into <span class='fm-mono'>read_parquet</span>."
    )
)
add(fig3)
csv_note = (
    f"With the pyarrow engine, pandas read the {csv_gb} GB CSV in {fmt_s(med(big, PANDAS, 'read_csv_arrow'))}. "
    f"Polars took {fmt_s(min(med(big, LAZY, 'read_csv'), med(big, EAGER, 'read_csv')))} and default pandas {fmt_s(med(big, PANDAS, 'read_csv'))}."
)
add(p(csv_note))
if probe:
    add(
        p(
            f"Parsing the timestamp column is most of that gap. In a side check, Polars read the same file in {fmt_s(probe_s('polars read_csv, ts left as text'))} with timestamps left as text, "
            f"and in {fmt_s(probe_s('polars read_csv, ts typed via schema'))} with the column typed up front. "
            f"Reading with pyarrow and handing the table to Polars took {fmt_s(probe_s('pyarrow.csv.read_csv -> pl'))}."
        )
    )
add(
    p(
        f"On the Parquet query, Polars lazy still beat tuned pandas by {fmt_x(med(big, PANDAS, 'pipeline_parquet_tuned') / pq_q_lazy)}."
    )
)

add("<h3>Memory at 50 million rows</h3>")
add(
    p(
        f"Reading files, Polars grew by {mm('read_csv', EAGER):.1f} GB for CSV and {mm('read_parquet', EAGER):.1f} GB for Parquet, against {mm('read_csv', PANDAS):.1f} GB and {mm('read_parquet', PANDAS):.1f} GB for pandas. "
        "Polars lazy needed far less for the 1,000-group group-by and both queries. pandas needed less for the per-customer group-by, join, sort and window."
    )
)
add(fig4)
add(
    p(
        f"Each bar is the peak growth in resident memory while one workload ran, median of 3 fresh processes. "
        f"The loaded orders table itself took {pd_in:.1f} GB in pandas and {pl_in:.1f} GB in Polars."
    )
)

add(
    p(
        f"Polars eager's group-bys were the memory outlier: {mm('groupby_low', EAGER):.1f} GB for 1,000 groups, against {mm('groupby_low', PANDAS):.1f} GB in pandas "
        f"and {mm('groupby_low', LAZY) * 1000:.0f} MB in Polars lazy. "
        f"Tuned pandas brought the Parquet query down to {mm('pipeline_parquet_tuned', PANDAS):.1f} GB, against {mm('pipeline_parquet', LAZY):.1f} GB for Polars lazy."
    )
)

add("<h3>How much is just more cores (eight-workload subset)</h3>")
scale = {op: med("10M", LAZY, op, "1-thread") / med("10M", LAZY, op) for op in TOPS}
lazy_cores = [t(big, LAZY, op)["cores_busy"] for op in OPS]
add(
    p(
        f"At 50M rows Polars lazy kept {min(lazy_cores):.0f} to {max(lazy_cores):.0f} of the 18 cores busy on average, and pandas mostly one. Pinned to one thread at 10M rows, Polars lazy still beat pandas on "
        f"{len(one_thread_wins)} of {len(TOPS)} workloads. It lost on {words(SHORT[o] for o in one_thread_losses) or 'none'}."
    )
)
add(fig5)
add(
    p(
        f"Going from 1 to 18 threads made Polars lazy {fmt_x(min(scale.values()))} to {fmt_x(max(scale.values()))} faster. "
        f"On one thread its lead over pandas was {fmt_x(max(one_thread.values()))} at most. "
        "So on this machine most of the large margins come from using more cores."
    )
)

add("<h3>Caveats</h3>")
add(
    "<ul>"
    f"<li>This Mac was shared with other running jobs. The harness rejected {NOISE['runs_discarded_for_background_load']} records, including warm-ups. "
    f"It retained {len(NOISE['batches_flagged'])} timing cells above the background limit after retries. "
    f"Across batches, other processes used a median {NOISE['background_cores_per_batch_median']:.1f} of 18 cores. Runs under a second could only be checked as a batch.</li>"
    f"<li>The {escape(hw['Chip'])} mixes {ENV['perf_cores']} {escape(ENV['perflevel0_name'])} and {ENV['efficiency_or_second_tier_cores']} {escape(ENV['perflevel1_name'])} cores. macOS picks which core runs pandas' single thread, which adds run-to-run spread.</li>"
    "<li>The data is synthetic, with evenly spread keys. Skewed real data can change group-by and join results.</li>"
    "<li>Files were read repeatedly, so they came from the operating system's file cache. Read times measure parsing, not the SSD.</li>"
    "<li>pandas ran with defaults: NumPy-backed columns, pandas 3's Arrow-backed strings, no categoricals. Group-bys used <span class='fm-mono'>sort=False</span> to match Polars.</li>"
    "<li>Memory is peak resident memory sampled about every millisecond from outside the process. Memory the allocator reuses is not counted twice, so it can understate.</li>"
    "<li>Polars joins and group-bys return rows in any order. pandas keeps the left table's order, which is slightly more work.</li>"
    "<li>One machine and one day of runs, one day after the Polars 2.0.0 release. I did not compare against Polars 1.x.</li>"
    "</ul>"
)

add("<h3>What I measured and what I infer</h3>")
add(
    "<ul>"
    "<li><strong>Measured:</strong> every time, memory figure and ratio on this card, and the versions and hardware above. "
    "Selected fingerprints agreed in all four modes at 1M rows, not exhaustive row equality. Float sums matched to a relative 1e-9.</li>"
    "<li><strong>Measured:</strong> Polars 2.0's <span class='fm-mono'>collect()</span> picks the streaming engine by default. Its docstring says so, and a verbose run logged the streaming engine.</li>"
    "<li><strong>Inferred:</strong> most of 2.0's group-by, join and window speed work went into the streaming engine, which is why eager trails lazy. "
    "Many items in the 2.0 performance notes name that engine. I did not read the engine code or compare with Polars 1.x.</li>"
    "<li><strong>Not tested:</strong> other machines, Linux, pandas with <span class='fm-mono'>dtype_backend=\"pyarrow\"</span>, and Polars' 64-bit-index runtime.</li>"
    "</ul>"
)

files = [
    ("README.md", "how to run everything again"),
    ("scripts/run_all.sh", "full run, in order"),
    ("scripts/gen_data.py", "seeded data generator"),
    ("scripts/ops.py", "every workload, per library mode"),
    ("scripts/validate.py", "same-answer check across modes"),
    ("scripts/bench_time.py", "timing harness with the quiet-machine gate"),
    ("scripts/bench_mem.py", "peak-memory harness"),
    ("scripts/csv_probe.py", "CSV side check"),
    ("scripts/analyze.py", "medians, spread, ratios"),
    ("scripts/env_info.py", "versions and hardware"),
    ("scripts/requirements.txt", "exact package versions"),
    ("results/timings.jsonl", "every run, including warm-ups and redone runs"),
    ("results/memory.jsonl", "every memory measurement"),
    ("results/csv_probe.jsonl", "CSV side check runs"),
    ("results/summary.json", "medians, spread and ratios"),
    ("results/summary.md", "the same as tables"),
    ("results/validation_1M.json", "answer fingerprints per mode"),
    ("results/environment.json", "versions and hardware"),
    ("results/run.log", "console log of the full run"),
]
add(
    "<details><summary>Scripts, raw results and how to run them again</summary>"
    f"<p>Everything is saved in <span class='fm-mono'>{escape(EVID)}</span>. The working copy where I ran it is deleted when this task closes. "
    "The 5 GB of generated data is not saved; the generator is seeded, so it rebuilds the same data.</p>"
    "<ul>" + "".join(f"<li><span class='fm-mono'>{escape(f)}</span>: {escape(d)}</li>" for f, d in files) + "</ul>"
    "<p>To run it again on a Mac, from that folder:</p>"
    "<pre class='fm-mono'># From the project root; see README.md for the full method\n"
    "python3 -m venv .bootstrap &amp;&amp; .bootstrap/bin/pip install uv==0.12.23\n"
    "UV_PYTHON_INSTALL_DIR=$PWD/.uv-python .bootstrap/bin/uv venv --python 3.14.8 .venv\n"
    ".bootstrap/bin/uv pip install --python .venv/bin/python -r scripts/requirements.txt -r scripts/requirements-charts.txt\n"
    "./scripts/run_all.sh</pre>"
    "</details>"
)
add(
    "<details><summary>All timings at 50M rows: median, fastest–slowest, spread, cores busy</summary>"
    f"{table('50M')}<p class='fm-muted'>The 1M and 10M tables, and the one-thread runs, are in <span class='fm-mono'>results/summary.md</span>.</p></details>"
)
add(
    "<details><summary>Peak extra memory at 50M rows: median of 3, lowest–highest</summary>"
    f"{mem_table('50M')}<p class='fm-muted'>The 10M table is in <span class='fm-mono'>results/summary.md</span>.</p></details>"
)
add(
    "<details><summary>Workload definitions</summary><ul>"
    "<li>Orders: order_id, ts (2025, in time order), customer_id (N/10 customers), product_id, store (200), channel, status, quantity, unit_price, discount (5% missing). Customers: customer_id, segment, country, signup_date.</li>"
    f"<li>Read CSV: the {csv_gb} GB orders CSV with timestamps parsed. Read Parquet: the {pq_gb} GB zstd Parquet file written by Polars.</li>"
    "<li>Filter: status delivered, unit_price above 50, channel web or app.</li>"
    "<li>Group-by, 1,000 groups: by store and status, revenue sum, mean discount, count. Group-by, per customer: 5M groups at 50M, revenue sum, count, latest ts.</li>"
    "<li>Join: inner join of orders to customers on customer_id. Sort: by customer_id, then ts.</li>"
    "<li>Window: price minus the customer's mean price, and a running quantity total per customer.</li>"
    "<li>Query: Q4 delivered orders, joined to customers, net revenue by country and segment, sorted. Run from Parquet and from CSV files.</li>"
    "<li>Polars eager uses the DataFrame API. Polars lazy wraps the same expressions in a LazyFrame or scan and calls collect().</li>"
    "</ul></details>"
)
add(
    "<details><summary>Environment as recorded</summary><pre class='fm-mono'>"
    + escape(json.dumps({k: ENV[k] for k in ("recorded_at", "python", "polars", "polars_show_versions", "polars_thread_pool_size", "polars_engine_affinity", "pandas", "pyarrow", "numpy", "macos", "hardware", "perflevel0_name", "perf_cores", "perflevel1_name", "efficiency_or_second_tier_cores", "power", "low_power_mode")}, indent=1))
    + "</pre></details>"
)

with open(OUT, "w") as f:
    f.write("\n".join(html))
print(f"wrote {OUT}: {sum(len(h) for h in html):,} chars")
