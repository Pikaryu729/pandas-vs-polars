# Charts for slides

Every chart is a self-contained **1600×900 PNG** plus an **SVG with font outlines**,
white background and embedded geometry. The SVG preserves the PNG's typography;
no installed fonts or network resources are required. Insert either format into a 16:9 slide without cropping. The PNG is
ready for standard slides; SVG scales to higher-resolution screens.

Generate all pairs with:

```sh
.venv/bin/python scripts/render_charts.py
```

The only numerical input is `results/summary.json`. Adjacent `environment.json`
supplies hardware/version captions. A complete three-size summary is required.
The CSV probe is discussed in the write-up, not silently merged into timing cells.

| Base filename (PNG and SVG) | Slide caption |
|---|---|
| `01-timings-50m` | All ten workloads at 50M orders; wall-time medians and min–max whiskers on a log axis. Lower is faster. |
| `02-scaling` | Default pandas time / Polars lazy time at 1M, 10M and 50M; values above 1× favor Polars. Log axis. |
| `03-tuned-pandas` | Default pandas, tuned pandas and the faster measured Polars mode for CSV reading and the CSV/Parquet queries. Log axis. |
| `04-memory-50m` | Extra peak RSS at 50M, median of three fresh processes. Loaded inputs are excluded from the baseline delta. Decimal GB. |
| `05-threads-10m` | All ten workloads at 10M: pandas versus lazy Polars with one and 18 threads. The limit applies only to Polars. Log axis. |
| `06-polars-engines` | Six diagnostic 50M workloads: eager in-memory, lazy in-memory and lazy streaming. Log axis. |

Each chart retains a shared-machine caveat in its footer. Four timing cells
exceeded the background-load limit after retries; read the main write-up before
presenting a ratio as representative. Whiskers are observed ranges, not confidence
intervals. Memory bars show extra RSS, not total RAM needed by a query.

`manifest.json` lists descriptions and filenames. Distinct colors and markers
separate modes; grayscale or a projector can still distinguish the timing dots.
For a new full run, use `--summary runs/<run>/summary.json --output runs/<run>/charts`.
The renderer uses the supplied hardware metadata, not this Mac's caption.
