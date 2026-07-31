"""Run and plot Python API benchmarks using Hyperfine."""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "benches" / "results.json"
DEFAULT_PLOT = ROOT / "benches" / "results.png"
CALIBRATION_SAMPLE_SECONDS = 0.05
MAX_ITERATIONS = 1_000_000
MICROSECONDS_PER_MILLISECOND = 1_000
DECIMAL_DURATION_THRESHOLD_US = 10

LIBRARIES = {
    "tl": "tl-parser",
    "bs4-html": "BeautifulSoup (html.parser)",
    "bs4-lxml": "BeautifulSoup (lxml)",
    "lxml": "lxml.html",
    "pyquery": "PyQuery",
}

SCENARIOS = {
    "parse": "Parse",
    "title_text": "Title text",
    "class_lookup": "Class lookup",
    "id_lookup": "ID lookup",
    "css_query": "CSS query",
}
WORKER_SCENARIOS = {"baseline": "Baseline", **SCENARIOS}

DOCUMENT_SECTIONS = {
    "small": 1,
    "medium": 50,
    "large": 250,
}

PACKAGE_DISTRIBUTIONS = {
    "tl-parser": "tl-parser",
    "beautifulsoup4": "beautifulsoup4",
    "lxml": "lxml",
    "pyquery": "pyquery",
}

_SINK: list[Any] = [None]


@dataclass(frozen=True)
class Expected:
    title: str
    sister_count: int
    css_count: int
    target_id: str
    target_text: str


@dataclass(frozen=True)
class Adapter:
    parse: Callable[[str], Any]
    operations: dict[str, Callable[[Any], Any]]


def consume(value: Any) -> None:
    _SINK[0] = value


def build_document(section_count: int) -> tuple[str, Expected]:
    sections = [
        f"""
            <section data-index="{index}">
              <p class="title"><b>Story {index}</b></p>
              <p class="story">
                Once upon a time there were three sisters:
                <a class="sister" href="/elsie/{index}" id="link-{index}-1">Elsie</a>,
                <a class="sister" href="/lacie/{index}" id="link-{index}-2">Lacie</a>,
                and
                <a class="sister" href="/tillie/{index}" id="link-{index}-3">Tillie</a>.
              </p>
              <p class="story">Section {index}</p>
            </section>
            """
        for index in range(section_count)
    ]

    document = f"""<!doctype html>
    <html>
      <head><title>Parser benchmark</title></head>
      <body>{"".join(sections)}</body>
    </html>
    """
    return document, Expected(
        title="Parser benchmark",
        sister_count=section_count * 3,
        css_count=section_count,
        target_id=f"link-{section_count - 1}-3",
        target_text="Tillie",
    )


def build_tl_adapter(expected: Expected) -> Adapter:
    import tl

    def id_lookup(dom: Any) -> str | None:
        element = dom.get_element_by_id(expected.target_id)
        return element.inner_text() if element is not None else None

    return Adapter(
        parse=tl.parse,
        operations={
            "title_text": lambda dom: dom.query_selector("title")[0].inner_text().strip(),
            "class_lookup": lambda dom: len(dom.get_elements_by_class_name("sister")),
            "id_lookup": id_lookup,
            "css_query": lambda dom: len(dom.query_selector('a[href^="/tillie/"]')),
        },
    )


def build_bs4_adapter(parser: str, expected: Expected) -> Adapter:
    from bs4 import BeautifulSoup

    def parse(html: str) -> Any:
        return BeautifulSoup(html, parser)

    def title_text(dom: Any) -> str:
        return dom.title.get_text(strip=True) if dom.title is not None else ""

    def id_lookup(dom: Any) -> str | None:
        element = dom.find(id=expected.target_id)
        return element.get_text(strip=True) if element is not None else None

    return Adapter(
        parse=parse,
        operations={
            "title_text": title_text,
            "class_lookup": lambda dom: len(dom.find_all(class_="sister")),
            "id_lookup": id_lookup,
            "css_query": lambda dom: len(dom.select('a[href^="/tillie/"]')),
        },
    )


def build_lxml_adapter(expected: Expected) -> Adapter:
    from lxml import html as lxml_html

    return Adapter(
        parse=lxml_html.fromstring,
        operations={
            "title_text": lambda dom: dom.cssselect("title")[0].text_content().strip(),
            "class_lookup": lambda dom: len(dom.cssselect(".sister")),
            "id_lookup": lambda dom: dom.get_element_by_id(expected.target_id).text_content().strip(),
            "css_query": lambda dom: len(dom.cssselect('a[href^="/tillie/"]')),
        },
    )


def build_pyquery_adapter(expected: Expected) -> Adapter:
    from pyquery import PyQuery

    return Adapter(
        parse=PyQuery,
        operations={
            "title_text": lambda dom: dom("title").text(),
            "class_lookup": lambda dom: len(dom(".sister")),
            "id_lookup": lambda dom: dom(f"#{expected.target_id}").text(),
            "css_query": lambda dom: len(dom('a[href^="/tillie/"]')),
        },
    )


def build_adapter(name: str, expected: Expected) -> Adapter:
    if name == "tl":
        return build_tl_adapter(expected)
    if name == "bs4-html":
        return build_bs4_adapter("html.parser", expected)
    if name == "bs4-lxml":
        return build_bs4_adapter("lxml", expected)
    if name == "lxml":
        return build_lxml_adapter(expected)
    if name == "pyquery":
        return build_pyquery_adapter(expected)
    raise ValueError(f"Unknown library: {name}")


def validate(adapter: Adapter, html: str, expected: Expected) -> Any:
    dom = adapter.parse(html)
    actual = {
        "title_text": adapter.operations["title_text"](dom),
        "class_lookup": adapter.operations["class_lookup"](dom),
        "id_lookup": adapter.operations["id_lookup"](dom),
        "css_query": adapter.operations["css_query"](dom),
    }
    wanted = {
        "title_text": expected.title,
        "class_lookup": expected.sister_count,
        "id_lookup": expected.target_text,
        "css_query": expected.css_count,
    }
    if actual != wanted:
        raise RuntimeError(f"Adapter returned {actual!r}; expected {wanted!r}")
    return dom


def prepare_operation(library: str, scenario: str, size: str) -> Callable[[], None] | None:
    html, expected = build_document(DOCUMENT_SECTIONS[size])
    adapter = build_adapter(library, expected)
    dom = validate(adapter, html, expected)
    if scenario == "baseline":
        return None

    if scenario == "parse":

        def parse() -> None:
            consume(adapter.parse(html))

        return parse

    operation = adapter.operations[scenario]

    def query() -> None:
        consume(operation(dom))

    return query


def run_worker(library: str, scenario: str, size: str, iterations: int) -> None:
    operation = prepare_operation(library, scenario, size)
    if operation is None:
        return

    for _ in range(iterations):
        operation()


def calibrate_worker(library: str, scenario: str, size: str, target_seconds: float) -> int:
    operation = prepare_operation(library, scenario, size)
    if operation is None:
        return 0

    sample_iterations = 1
    while True:
        started = perf_counter()
        for _ in range(sample_iterations):
            operation()
        elapsed = perf_counter() - started
        if elapsed >= CALIBRATION_SAMPLE_SECONDS or sample_iterations >= MAX_ITERATIONS:
            break
        sample_iterations *= 10

    estimated = round(target_seconds * sample_iterations / elapsed)
    return max(1, min(estimated, MAX_ITERATIONS))


def package_versions() -> dict[str, str]:
    versions = {}
    for name, distribution in PACKAGE_DISTRIBUTIONS.items():
        try:
            versions[name] = version(distribution)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def git_revision() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def benchmark_metadata(
    runs: int,
    warmup: int,
    target_seconds: float,
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    documents = {}
    for name, section_count in DOCUMENT_SECTIONS.items():
        html, _ = build_document(section_count)
        documents[name] = {
            "sections": section_count,
            "bytes": len(html.encode()),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_revision": git_revision(),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "hyperfine": subprocess.check_output(["hyperfine", "--version"], text=True).strip(),
        "packages": package_versions(),
        "libraries": LIBRARIES,
        "scenarios": SCENARIOS,
        "documents": documents,
        "cases": cases,
        "target_batch_seconds": target_seconds,
        "baseline_subtracted": True,
        "runs": runs,
        "warmup": warmup,
    }


def worker_command(library: str, scenario: str, size: str, iterations: int) -> str:
    parts = [
        sys.executable,
        str(Path(__file__).resolve()),
        "worker",
        "--library",
        library,
        "--scenario",
        scenario,
        "--size",
        size,
        "--iterations",
        str(iterations),
    ]
    return shlex.join(parts)


def calibrated_iterations(library: str, scenario: str, size: str, target_seconds: float) -> int:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "calibrate",
        "--library",
        library,
        "--scenario",
        scenario,
        "--size",
        size,
        "--target-seconds",
        str(target_seconds),
    ]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return int(result.stdout)


def run_hyperfine(args: argparse.Namespace) -> None:
    hyperfine = shutil.which("hyperfine")
    if hyperfine is None:
        raise SystemExit("hyperfine is not installed; see benches/README.md for setup")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    hyperfine_args = [
        hyperfine,
        "--warmup",
        str(args.warmup),
        "--runs",
        str(args.runs),
        "--export-json",
        str(output),
    ]

    cases: dict[str, dict[str, Any]] = {}
    for size in args.sizes:
        for library in args.libraries:
            name = f"{library}/baseline/{size}"
            cases[name] = {
                "library": library,
                "scenario": "baseline",
                "size": size,
                "iterations": 0,
            }
            hyperfine_args.extend(["--command-name", name, worker_command(library, "baseline", size, 0)])

        for scenario in args.scenarios:
            for library in args.libraries:
                iterations = calibrated_iterations(
                    library,
                    scenario,
                    size,
                    args.target_seconds,
                )
                name = f"{library}/{scenario}/{size}"
                cases[name] = {
                    "library": library,
                    "scenario": scenario,
                    "size": size,
                    "iterations": iterations,
                }
                hyperfine_args.extend(["--command-name", name, worker_command(library, scenario, size, iterations)])

    subprocess.run(hyperfine_args, cwd=ROOT, check=True)

    payload = json.loads(output.read_text())
    payload["benchmark"] = benchmark_metadata(
        args.runs,
        args.warmup,
        args.target_seconds,
        cases,
    )
    output.write_text(json.dumps(payload, indent=2) + "\n")
    plot_results(output, args.plot.resolve())


def plot_results(input_path: Path, output_path: Path) -> None:  # noqa: C901, PLR0915
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    payload = json.loads(input_path.read_text())
    metadata = payload["benchmark"]
    cases = metadata["cases"]
    available_sizes = [size for size in DOCUMENT_SECTIONS if any(case["size"] == size for case in cases.values())]
    available_scenarios = [
        scenario for scenario in SCENARIOS if any(case["scenario"] == scenario for case in cases.values())
    ]
    available_libraries = [
        library for library in LIBRARIES if any(case["library"] == library for case in cases.values())
    ]
    results = {result["command"]: result for result in payload["results"]}

    def median_and_mad(name: str) -> tuple[float, float]:
        times = results[name]["times"]
        median = statistics.median(times)
        mad = statistics.median(abs(value - median) for value in times)
        return median, mad

    def format_duration(microseconds: float) -> str:
        if microseconds >= MICROSECONDS_PER_MILLISECOND:
            return f"{microseconds / MICROSECONDS_PER_MILLISECOND:.2f} ms"
        if microseconds >= DECIMAL_DURATION_THRESHOLD_US:
            return f"{microseconds:.1f} us"
        return f"{microseconds:.2f} us"

    plt.rcParams.update(
        {
            "axes.facecolor": "#202831",
            "axes.edgecolor": "#52606d",
            "axes.labelcolor": "#d9e2ec",
            "figure.facecolor": "#202831",
            "font.size": 9,
            "text.color": "#d9e2ec",
            "xtick.color": "#bcccdc",
            "ytick.color": "#d9e2ec",
        }
    )
    figure_height = 3.25 * len(available_scenarios) + 1.0
    fig, axes = plt.subplots(
        len(available_scenarios),
        len(available_sizes),
        figsize=(5.8 * len(available_sizes), figure_height),
        squeeze=False,
    )

    for row, scenario in enumerate(available_scenarios):
        for column, size in enumerate(available_sizes):
            axis = axes[row][column]
            measurements = []
            for library in available_libraries:
                case_name = f"{library}/{scenario}/{size}"
                baseline_name = f"{library}/baseline/{size}"
                median, mad = median_and_mad(case_name)
                baseline_median, baseline_mad = median_and_mad(baseline_name)
                iterations = cases[case_name]["iterations"]
                elapsed = (median - baseline_median) * 1_000_000 / iterations
                deviation = (mad**2 + baseline_mad**2) ** 0.5 * 1_000_000 / iterations
                if elapsed <= 0:
                    raise RuntimeError(f"{case_name} did not exceed its baseline")
                measurements.append((elapsed, deviation, library))

            measurements.sort()
            values = [measurement[0] for measurement in measurements]
            deviations = [min(measurement[1], measurement[0] * 0.8) for measurement in measurements]
            labels = [LIBRARIES[measurement[2]] for measurement in measurements]
            colors = ["#56b4c2" if measurement[2] == "tl" else "#7651bd" for measurement in measurements]
            positions = list(range(len(measurements)))
            bars = axis.barh(
                positions,
                values,
                xerr=deviations,
                height=0.58,
                color=colors,
                error_kw={"ecolor": "#a7b6c2", "elinewidth": 0.8, "capsize": 2},
            )
            axis.set_yticks(positions, labels)
            axis.invert_yaxis()
            axis.grid(axis="x", color="#52606d", linewidth=0.6, alpha=0.55)
            axis.set_axisbelow(True)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.tick_params(axis="y", length=0)
            axis.margins(x=0.24)
            axis.bar_label(
                bars,
                labels=[format_duration(value) for value in values],
                padding=4,
                color="#d9e2ec",
                fontsize=8,
            )
            if row == 0:
                document = metadata["documents"][size]
                axis.set_title(
                    f"{size.title()}\n{document['sections']} sections | {document['bytes'] / 1024:.1f} KiB",
                    fontweight="bold",
                    pad=12,
                )
            if column == 0:
                axis.set_ylabel(SCENARIOS[scenario], fontweight="bold", labelpad=12)
            if row == len(available_scenarios) - 1:
                axis.set_xlabel("Time per operation")

    fig.suptitle(
        "Python HTML parser benchmark",
        fontsize=17,
        fontweight="bold",
        y=1 - 0.12 / figure_height,
    )
    fig.text(
        0.5,
        1 - 0.38 / figure_height,
        "Median startup-adjusted time; lower is better",
        ha="center",
        va="top",
        color="#9fb3c8",
        fontsize=10,
    )
    fig.subplots_adjust(
        top=1 - 1.0 / figure_height,
        bottom=0.06,
        left=0.11,
        right=0.98,
        hspace=0.46,
        wspace=0.42,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved Hyperfine results to {input_path}")
    print(f"Saved benchmark chart to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run Hyperfine and plot results")
    run_parser.add_argument("--runs", type=int, default=10)
    run_parser.add_argument("--warmup", type=int, default=2)
    run_parser.add_argument("--target-seconds", type=float, default=0.2)
    run_parser.add_argument("--libraries", nargs="+", default=list(LIBRARIES), choices=LIBRARIES)
    run_parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    run_parser.add_argument("--sizes", nargs="+", default=list(DOCUMENT_SECTIONS), choices=DOCUMENT_SECTIONS)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    run_parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT)

    plot_parser = subparsers.add_parser("plot", help="plot an existing JSON result")
    plot_parser.add_argument("--input", type=Path, default=DEFAULT_RESULTS)
    plot_parser.add_argument("--output", type=Path, default=DEFAULT_PLOT)

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--library", required=True, choices=LIBRARIES)
    worker_parser.add_argument("--scenario", required=True, choices=WORKER_SCENARIOS)
    worker_parser.add_argument("--size", required=True, choices=DOCUMENT_SECTIONS)
    worker_parser.add_argument("--iterations", required=True, type=int)

    calibrate_parser = subparsers.add_parser("calibrate")
    calibrate_parser.add_argument("--library", required=True, choices=LIBRARIES)
    calibrate_parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    calibrate_parser.add_argument("--size", required=True, choices=DOCUMENT_SECTIONS)
    calibrate_parser.add_argument("--target-seconds", required=True, type=float)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        run_hyperfine(args)
    elif args.command == "plot":
        plot_results(args.input.resolve(), args.output.resolve())
    elif args.command == "worker":
        run_worker(args.library, args.scenario, args.size, args.iterations)
    else:
        print(calibrate_worker(args.library, args.scenario, args.size, args.target_seconds))


if __name__ == "__main__":
    main()
