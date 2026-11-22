"""Benchmark the Compose cluster: worker-node sweep and processes-per-node sweep.

Run on the container host. Every sample rebuilds a fresh cluster, runs the full workload, and
counts only if the output CSV is complete (one row per image) and passes the character-accuracy
threshold. Two timing boundaries are recorded per sample:

- ``total_s``: `docker compose up -d` issued until the master container exits (includes startup).
- ``window_s``: master's first ASSIGN log line until its "Completed" line (processing only).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

from parallel_ocr_pipeline.distributed import MAX_ACTIVE_WORKERS
from run_acceptance import MODEL, ROOT, compose, container_ids, inspect, run

TIMESTAMP = re.compile(r"^(\d{4}-\d\d-\d\dT[\d:.]+)Z\s+(.*)$")


def parse_ts(value: str) -> float:
    head, _, frac = value.partition(".")
    base = dt.datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.UTC).timestamp()
    return base + float("0." + frac) if frac else base


def run_sample(nodes: int, procs: int, out: Path) -> dict:
    os.environ["N_WORKERS"] = str(procs)
    compose("down", "-v", "--remove-orphans", check=False)
    compose("create", "--scale", f"worker={nodes}")
    for index in range(1, nodes + 1):
        compose(
            "cp",
            "--index",
            str(index),
            str(MODEL),
            "worker:/app/local-assets/models/eng.traineddata",
        )
    start = time.monotonic()
    compose("up", "--no-recreate", "--scale", f"worker={nodes}", "-d")
    master = container_ids("master")[0]
    workers = container_ids("worker")
    log = subprocess.run(
        ["docker", "compose", "logs", "-t", "-f", "--no-log-prefix", "master"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    ).stdout
    run("docker", "wait", master)
    total = time.monotonic() - start
    first = done = None
    assigns = 0
    for line in log.splitlines():
        match = TIMESTAMP.match(line)
        if not match:
            continue
        if "ASSIGN " in match[2]:
            assigns += 1
            first = first or parse_ts(match[1])
        elif match[2].startswith("Completed"):
            done = parse_ts(match[1])
    window = (done - first) if first and done else None
    codes = [int(inspect(cid, "{{.State.ExitCode}}")) for cid in [master, *workers]]

    csv_path = out / f"n{nodes}p{procs}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    compose("cp", "master:/tmp/ocr_results.csv", str(csv_path), check=False)
    expected = len(list((ROOT / "local-assets" / "dataset" / "images").glob("*.png")))
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8"))) if csv_path.exists() else []
    score = subprocess.run(
        ["uv", "run", "--no-sync", "python", "scripts/evaluate_pipeline.py", str(csv_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    valid = (
        all(code == 0 for code in codes)
        and len(rows) == expected
        and len({r["filename"] for r in rows}) == expected
        and assigns == expected
        and score.returncode == 0
        and window is not None
    )
    csv_path.unlink(missing_ok=True)
    return {
        "nodes": nodes,
        "procs": procs,
        "total_s": round(total, 3),
        "window_s": round(window, 3) if window is not None else "",
        "valid": valid,
        "accuracy": (score.stdout + score.stderr).strip().splitlines()[-1:],
    }


def summarize(samples: list[dict], key: str, sweep: str, nodes: int | None = None) -> list[dict]:
    """Mean/stdev per setting, speedup against the smallest setting, efficiency per unit."""
    groups: dict[int, list[float]] = {}
    for s in samples:
        if s["valid"] and s["sweep"] == sweep and nodes in (None, s["nodes"]):
            groups.setdefault(s[key], []).append(s["window_s"])
    base_n = min(groups)
    t1 = statistics.mean(groups[base_n])
    table = []
    for n in sorted(groups):
        values = groups[n]
        mean = statistics.mean(values)
        speedup = t1 / mean
        table.append(
            {
                key: n,
                "runs": len(values),
                "mean_s": round(mean, 3),
                "stdev_s": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
                "min_s": round(min(values), 3),
                "max_s": round(max(values), 3),
                "speedup": round(speedup, 3),
                "efficiency": round(speedup * base_n / n, 3),
            }
        )
    return table


def ints(text: str) -> list[int]:
    return [int(part) for part in text.split(",")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-counts", type=ints, default=[1, 2], help="node sweep, e.g. 1,2,3")
    parser.add_argument("--node-procs", type=int, default=2, help="processes/node, node sweep")
    parser.add_argument("--proc-counts", type=ints, default=[1, 2, 4], help="processes sweep")
    parser.add_argument(
        "--proc-nodes", type=ints, default=[2], help="fixed node counts, processes sweep"
    )
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--skip", choices=("nodes", "procs"), help="skip one sweep")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if not MODEL.exists():
        raise SystemExit(f"missing supplied model: {MODEL}")

    out = args.out or ROOT / "results" / "benchmark-cluster" / dt.datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    out.mkdir(parents=True, exist_ok=True)
    plan: list[tuple[str, int, int]] = []
    if args.skip != "nodes":
        plan += [("nodes", n, args.node_procs) for n in args.node_counts]
    if args.skip != "procs":
        plan += [("procs", n, p) for n in args.proc_nodes for p in args.proc_counts]

    over_cap = [entry for entry in plan if entry[1] * entry[2] > MAX_ACTIVE_WORKERS]
    for sweep, nodes, procs in over_cap:
        print(
            f"skip {sweep} {nodes} nodes x {procs} procs: {nodes * procs} exceeds the master's "
            f"{MAX_ACTIVE_WORKERS} active worker-process cap",
            file=sys.stderr,
        )
    plan = [entry for entry in plan if entry not in over_cap]

    compose("build")
    samples: list[dict] = []
    try:
        for rep in range(1, args.reps + 1):
            # Interleave settings within each repetition so host drift hits every setting.
            for sweep, nodes, procs in plan:
                sample = run_sample(nodes, procs, out) | {"sweep": sweep, "rep": rep}
                samples.append(sample)
                print(json.dumps(sample), flush=True)
    finally:
        compose("down", "-v", "--remove-orphans", check=False)

    invalid = [s for s in samples if not s["valid"]]
    summary = {
        "host": platform.node(),
        "commit": run("git", "rev-parse", "HEAD"),
        "docker": run("docker", "--version"),
        "cpu": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "",
        ),
        "logical_cpus": os.cpu_count(),
        "omp_thread_limit": 1,
        "reps": args.reps,
        "invalid_samples": len(invalid),
        "node_sweep": summarize(samples, "nodes", "nodes")
        if any(s["sweep"] == "nodes" for s in samples)
        else [],
        "proc_sweeps": {
            str(n): summarize(samples, "procs", "procs", n)
            for n in args.proc_nodes
            if any(s["sweep"] == "procs" and s["nodes"] == n for s in samples)
        },
        "node_sweep_procs_per_node": args.node_procs,
        "samples": samples,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, indent=2))
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
