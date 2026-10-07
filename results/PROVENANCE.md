# Provenance and result schema

## Original measurements

The benchmark answer that preceded this project saved its scripts and results
on October 7, 2026. This project packages that saved evidence without rerunning
or replacing the reported timings. The Mac was shared with other work.

`SHA256SUMS` covers the nine originally supplied result files as published here.
All are byte-for-byte identical to the saved evidence except `environment.json`:
its `python_executable` field containing a private absolute path was removed.
The hardware summary and every numerical value remain unchanged.
No generated dataset, original working-copy path or personal account data is included.

## Schemas

- `timings.jsonl`: one record per warm-up/timed attempt; size, mode, op, tag,
  wall/CPU/background seconds, acceptance/rejection, retry attempt, input-load
  time, output row count and measurement time. Analysis keeps only non-warm-up
  records with `accepted: true` (missing `accepted` defaults to true).
- `memory.jsonl`: fresh-process repetitions; pre-operation RSS baseline,
  sampled peak RSS/growth, kernel high-water delta, output/input size and row count.
  All measurements use bytes; summaries use decimal MB.
- `csv_probe.jsonl`: seven reader variants; five timed samples per variant,
  median wall time, core diagnostics and background load. Probe records are
  separate from the main timing summary and do not have its acceptance filter.
- `summary.json`: timing cells keyed `size|mode|op|tag`, speedups versus default
  pandas, memory cells keyed `size|mode|op`, and background/rejection diagnostics.
  It is regenerated from the timing and memory JSONL files by `analyze.py`.
- `summary.md`: the same summary, rendered as tables.
- `validation_1M.json`: original fingerprint comparison results and fingerprints.
- `environment.json`: versions and hardware summary, with interpreter path redacted.
- `run.log`: original console output of the main run, including retries and waits.
- `polars-2.0.0-release-notes.md`: saved upstream release text, attributed separately.

Unix timestamps are preserved for auditability. The recorded run-log times are
already local Central time. Do not interpret a record timestamp as a randomized
experiment or an independent replicate on a second machine.

## Publication adaptations to source

The original workload expressions, seed, data distributions, timing acceptance
rules and analysis arithmetic are unchanged. The package makes these bounded
changes for safe rerunning:

1. Paths now resolve from the project root; new results default to ignored `runs/`.
2. The full runner uses Bash, honors data/result overrides, checks all four input
   files per size, refuses nonempty or published result folders, and adds analysis,
   the CSV probe and standalone slide rendering. Its smoke option is functional only.
3. The validator exits with failure when fingerprints disagree.
4. Environment capture omits interpreter paths and tolerates missing Mac-specific
   system queries. Memory capture converts Linux kernel high-water KiB to bytes.
5. Analysis accepts a results-directory argument; its arithmetic is unchanged.
6. The standalone slide renderer and behavioral tests are new. The historical
   SVG/card renderer remains available but is not the formal publication.

## Clarifications to the earlier answer

- The 132 discarded **records** include 18 warm-ups, not 132 timed measurements.
- Four final timing cells still exceeded the background threshold after retries.
- The original correctness check used selected fingerprints, not full row equality.
- The original one-thread figure showed eight workloads; all ten saved workloads
  give six lazy wins and 5.6×–10.8× gains from one to 18 threads. The displayed
  eight-workload subset gave five wins and 5.6×–7.9× gains.
- The CSV side probe did not filter noisy timed samples; its text-only reader
  variant omits timestamp parsing. It suggests a cause rather than proving one.

These qualifications change the interpretation, not the original raw values.
