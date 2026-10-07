"""Behavioral checks on disposable data; these are not new benchmark results."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import polars as pl
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import analyze
import env_info
import gen_data
import render_charts
import validate
from ops import IO_OPS, MEM_OPS, MODES, PANDAS_EXTRA, PIPE_OPS, get_ops


class Workloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)
        orders, customers = gen_data.make(10_000)
        cls.paths = {}
        for name, df in (("orders", orders), ("customers", customers)):
            for fmt in ("csv", "parquet"):
                p = cls.folder / f"{name}.{fmt}"
                cls.paths[f"{name}_{fmt}"] = p
                if fmt == "csv":
                    df.write_csv(p, datetime_format="%Y-%m-%d %H:%M:%S")
                else:
                    df.write_parquet(p)
        cls.outputs = {}
        for mode in MODES:
            ops = get_ops(mode)
            ctx = {"p": cls.paths, **ops["_load"](cls.paths)}
            names = IO_OPS + MEM_OPS + PIPE_OPS + (PANDAS_EXTRA if mode == "pandas" else [])
            cls.outputs[mode] = {op: ops[op](ctx) for op in names}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def canonical(self, op, df):
        d = validate.to_pandas(df).copy()
        # Arrow date32 may become Python dates while Polars becomes datetimes.
        # Compare logical date/timestamp values, not representation differences.
        for column in ("ts", "signup_date", "last_order"):
            if column in d:
                d[column] = pd.to_datetime(d[column]).astype("datetime64[us]")
        if op == "sort":
            keys = d[["customer_id", "ts"]]
            self.assertEqual(keys.values.tolist(), keys.sort_values(["customer_id", "ts"]).values.tolist())
        if op.startswith("pipeline"):
            self.assertTrue(d["revenue"].is_monotonic_decreasing)
            keys = ["country", "segment"]
        elif op == "groupby_low":
            keys = ["store", "status"]
        elif op == "groupby_high":
            keys = ["customer_id"]
        else:
            keys = ["order_id"]
        return d.sort_values(keys).sort_index(axis=1).reset_index(drop=True)

    def test_complete_outputs_all_modes_and_tuned_cases(self):
        count = 0
        for mode, outputs in self.outputs.items():
            for op, output in outputs.items():
                with self.subTest(mode=mode, op=op):
                    base_op = op.replace("_arrow", "").replace("_tuned", "")
                    expected = self.canonical(base_op, self.outputs["pandas"][base_op])
                    got = self.canonical(op, output)
                    assert_frame_equal(got, expected, check_dtype=False, check_exact=False,
                                       rtol=1e-9, atol=1e-6)
                    count += 1
        self.assertEqual(count, 43)

    def test_seeded_generator(self):
        a, b = gen_data.make(10_000)
        c, d = gen_data.make(10_000)
        self.assertTrue(a.equals(c))
        self.assertTrue(b.equals(d))
        self.assertEqual(a.shape, (10_000, 10))
        self.assertEqual(b.height, 1_000)
        self.assertGreater(a["discount"].null_count(), 0)

    def test_validator_stops_on_mismatch(self):
        original = validate.fingerprint
        def bad(op, frame):
            fp = original(op, frame)
            if isinstance(frame, pl.DataFrame):
                fp["rows"] += 1
            return fp
        with patch.object(validate, "paths", return_value=self.paths), \
             patch.object(validate, "RESULTS", self.folder), \
             patch.object(validate, "fingerprint", side_effect=bad), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                validate.main("test")
        self.assertEqual(error.exception.code, 1)
        self.assertFalse(json.loads((self.folder / "validation_test.json").read_text())["ok"])


class Publication(unittest.TestCase):
    def test_original_summary_is_reproducible_from_raw_records(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            for name in ("timings.jsonl", "memory.jsonl"):
                shutil.copyfile(ROOT / "results" / name, p / name)
            cp = subprocess.run([sys.executable, str(ROOT / "scripts/analyze.py"), "--results-dir", str(p)], capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            for name in ("summary.json", "summary.md"):
                self.assertEqual((p / name).read_bytes(), (ROOT / "results" / name).read_bytes())

    def test_chart_rendering_uses_supplied_summary_and_writes_both_formats(self):
        from PIL import Image
        from matplotlib.axes import Axes
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            summary = json.loads((ROOT / "results/summary.json").read_text())
            summary["timing"]["50M|pandas|read_csv|"]["median_s"] = 12.345
            (p / "summary.json").write_text(json.dumps(summary))
            shutil.copyfile(ROOT / "results/environment.json", p / "environment.json")
            values = []
            original = Axes.scatter
            def record(ax, x, y, *args, **kwargs):
                values.append(list(x))
                return original(ax, x, y, *args, **kwargs)
            with patch.object(Axes, "scatter", new=record), contextlib.redirect_stdout(io.StringIO()):
                render_charts.render(p / "summary.json", p / "charts")
            self.assertEqual(values[0][0], 12.345)
            manifest = json.loads((p / "charts/manifest.json").read_text())
            self.assertEqual(len(manifest["charts"]), 6)
            for item in manifest["charts"]:
                png, svg = p / "charts" / item["png"], p / "charts" / item["svg"]
                with Image.open(png) as image:
                    self.assertEqual(image.size, (1600, 900))
                    self.assertGreater(len(image.convert("RGB").resize((160, 90)).getcolors(14_400)), 50)
                import xml.etree.ElementTree as ET
                root = ET.parse(svg).getroot()
                self.assertTrue(root.tag.endswith("svg"))
                self.assertGreater(len(root.findall(".//{http://www.w3.org/2000/svg}path")), 10)
                # Font outlines are embedded, so SVG cannot fall back to host fonts.
                self.assertEqual(root.findall(".//{http://www.w3.org/2000/svg}text"), [])

    def test_runner_refuses_published_and_nonempty_results(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "already-run.json").write_text("{}")
            before = (ROOT / "results/SHA256SUMS").read_bytes()
            for results in (ROOT / "results", p):
                cp = subprocess.run(["bash", str(ROOT / "scripts/run_all.sh"), "--smoke"],
                                    env=dict(os.environ, BENCH_PYTHON=sys.executable, BENCH_RESULTS_DIR=str(results)),
                                    capture_output=True, text=True)
                self.assertNotEqual(cp.returncode, 0)
                self.assertIn("Choose", cp.stderr)
            self.assertEqual((ROOT / "results/SHA256SUMS").read_bytes(), before)

    def test_environment_has_no_interpreter_path(self):
        with tempfile.TemporaryDirectory() as td, patch.object(env_info, "RESULTS", Path(td)), \
             contextlib.redirect_stdout(io.StringIO()):
            env_info.main()
            result = json.loads((Path(td) / "environment.json").read_text())
            self.assertNotIn("python_executable", result)
            self.assertEqual(result["polars"], pl.__version__)
            self.assertEqual(result["pandas"], pd.__version__)
            self.assertNotIn(str(Path.home()), json.dumps(result))


if __name__ == "__main__":
    unittest.main()
