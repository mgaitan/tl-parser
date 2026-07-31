# Python benchmarks

The benchmark compares the public Python APIs of `tl-parser`, BeautifulSoup,
`lxml.html`, and PyQuery. It measures parsing and common lookup operations over
valid HTML documents at three sizes.

Timing is delegated to [`hyperfine`](https://github.com/sharkdp/hyperfine),
which runs every case in a fresh process and reports statistics across multiple
runs. Each worker performs a batch of operations. Hyperfine also measures a
no-op baseline after importing, building the input, parsing once, and validating
results. The chart subtracts that baseline before normalizing each batch to time
per operation, so Python startup and imports do not dominate small documents.
Before running Hyperfine, the script calibrates each batch to approximately 0.2
seconds. The horizontal bar chart uses the median across runs and shows median
absolute deviation as error bars.

## Setup

Install the Python dependencies and the local extension:

```bash
uv sync --group benchmark
```

Install Hyperfine using your system package manager or Cargo:

```bash
cargo install --locked hyperfine
```

## Run

Run the complete benchmark and generate both the JSON result and chart:

```bash
uv run --group benchmark python benches/benchmark.py run
```

Results are written to `benches/results.json` and `benches/results.png`. To
regenerate only the chart:

```bash
uv run --group benchmark python benches/benchmark.py plot
```

For a shorter exploratory run, select a subset and reduce the number of runs:

```bash
uv run --group benchmark python benches/benchmark.py run \
  --sizes medium \
  --scenarios parse css_query \
  --runs 5 \
  --warmup 1
```

Run benchmarks on an otherwise idle machine. The JSON records the Python,
Hyperfine, package, platform, Git revision, document sizes, and batch sizes used
for the run.
