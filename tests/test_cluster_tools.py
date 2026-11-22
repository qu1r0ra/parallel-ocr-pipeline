from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
benchmark_cluster = importlib.import_module("benchmark_cluster")
package_submission = importlib.import_module("package_submission")
plot_benchmark = importlib.import_module("plot_benchmark")


def sample(nodes: int, window: float, valid: bool = True, sweep: str = "nodes") -> dict:
    return {"sweep": sweep, "nodes": nodes, "procs": 1, "window_s": window, "valid": valid}


def test_summarize_reports_speedup_and_efficiency_against_smallest_setting() -> None:
    samples = [sample(1, 8.0), sample(1, 8.0), sample(2, 4.0), sample(2, 5.0)]
    one, two = benchmark_cluster.summarize(samples, "nodes", "nodes")
    assert one["speedup"] == 1.0
    assert two["mean_s"] == 4.5
    assert two["speedup"] == round(8.0 / 4.5, 3)
    assert two["efficiency"] == round(8.0 / 4.5 / 2, 3)


def test_summarize_ignores_invalid_samples_and_other_sweeps() -> None:
    samples = [sample(1, 8.0), sample(2, 1.0, valid=False), sample(2, 1.0, sweep="procs")]
    assert [row["nodes"] for row in benchmark_cluster.summarize(samples, "nodes", "nodes")] == [1]


def test_parse_ts_keeps_fractional_seconds() -> None:
    early = benchmark_cluster.parse_ts("2026-11-22T10:00:00.250000000")
    late = benchmark_cluster.parse_ts("2026-11-22T10:00:03.750000000")
    assert late - early == 3.5


def test_audit_zip_accepts_required_source_only() -> None:
    assert package_submission.audit_zip(list(package_submission.REQUIRED) + [".env.example"]) == []


def test_audit_zip_flags_secrets_inputs_and_missing_source() -> None:
    names = [name for name in package_submission.REQUIRED if name != "uv.lock"] + [
        ".env",
        "local-assets/models/eng.traineddata",
        "results/x.csv",
        ".venv/bin/python",
    ]
    problems = package_submission.audit_zip(names)
    assert "missing required entry: uv.lock" in problems
    for forbidden in (".env", "local-assets/models/eng.traineddata", "results/x.csv"):
        assert f"forbidden entry: {forbidden}" in problems
    assert "forbidden entry: .venv/bin/python" in problems


def test_plot_render_draws_both_panels() -> None:
    rows = [
        {"nodes": 1, "mean_s": 8.0, "min_s": 7.5, "max_s": 8.5, "speedup": 1.0},
        {"nodes": 2, "mean_s": 4.0, "min_s": 3.8, "max_s": 4.3, "speedup": 2.0},
    ]
    svg = plot_benchmark.render(rows, "nodes", "worker nodes", "node sweep")
    assert svg.startswith("<svg") and svg.count("<polyline") == 3
