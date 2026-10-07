#!/usr/bin/env bash
# Rerun the saved method on disposable data; never append to published results.
# Usage from the project root: ./scripts/run_all.sh [--smoke]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PY=${BENCH_PYTHON:-"$ROOT/.venv/bin/python"}
export BENCH_DATA_DIR=${BENCH_DATA_DIR:-"$ROOT/data"}
export BENCH_RESULTS_DIR=${BENCH_RESULTS_DIR:-"$ROOT/runs/$(date +%Y%m%d-%H%M%S)"}
SMOKE=0
case "${1:-}" in
  --smoke) SMOKE=1 ;;
  "") ;;
  *) echo 'Usage: ./scripts/run_all.sh [--smoke]' >&2; exit 2 ;;
esac
"$PY" - <<'PY'
from pathlib import Path
from scripts.common import RESULTS, ROOT
if RESULTS.resolve() == (ROOT / 'results').resolve() or (ROOT / 'results').resolve() in RESULTS.resolve().parents:
    raise SystemExit('Choose a new results directory; published results are read-only inputs.')
RESULTS.mkdir(parents=True, exist_ok=True)
if any(RESULTS.iterdir()):
    raise SystemExit('Choose an empty results directory to avoid mixing separate runs.')
PY
exec > >(tee "$BENCH_RESULTS_DIR/run.log") 2>&1
echo "== start $(date '+%Y-%m-%d %H:%M:%S %Z')"
"$PY" scripts/env_info.py > /dev/null
SIZES=(1M 10M 50M)
if (( SMOKE )); then SIZES=(1M); fi
for size in "${SIZES[@]}"; do
  if [[ ! -f "$BENCH_DATA_DIR/orders_$size.parquet" || ! -f "$BENCH_DATA_DIR/customers_$size.parquet" || ! -f "$BENCH_DATA_DIR/orders_$size.csv" || ! -f "$BENCH_DATA_DIR/customers_$size.csv" ]]; then
    "$PY" scripts/gen_data.py "$size"
  fi
done
"$PY" scripts/validate.py 1M | tail -1
for size in "${SIZES[@]}"; do
  case "$size" in
    1M) warm=2; reps=10 ;;
    10M) warm=1; reps=7 ;;
    50M) warm=1; reps=5 ;;
  esac
  if (( SMOKE )); then warm=0; reps=1; fi
  for mode in pandas polars-eager polars-lazy polars-lazy-inmem; do
    "$PY" scripts/bench_time.py --mode "$mode" --size "$size" --warmup "$warm" --repeats "$reps"
  done
done
if (( ! SMOKE )); then
  for mode in polars-eager polars-lazy; do
    POLARS_MAX_THREADS=1 "$PY" scripts/bench_time.py --mode "$mode" --size 10M --warmup 1 --repeats 5 --tag 1-thread
  done
fi
MEM_SIZES=(10M 50M); MEM_REPS=3; PROBE_SIZE=50M
if (( SMOKE )); then MEM_SIZES=(1M); MEM_REPS=1; PROBE_SIZE=1M; fi
for size in "${MEM_SIZES[@]}"; do
  "$PY" scripts/bench_mem.py --size "$size" --reps "$MEM_REPS"
done
"$PY" scripts/csv_probe.py "$PROBE_SIZE"
"$PY" scripts/analyze.py
if (( ! SMOKE )); then
  "$PY" scripts/render_charts.py --summary "$BENCH_RESULTS_DIR/summary.json" --output "$BENCH_RESULTS_DIR/charts"
fi
echo "== end $(date '+%Y-%m-%d %H:%M:%S %Z')"
