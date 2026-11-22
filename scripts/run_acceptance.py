"""Run the #26 cluster acceptance: one master, several worker containers, one killed in flight.

Run this on the container host (see docs/agents/mp2-development.md). It builds the Compose
cluster, kills a worker container the instant the master logs an assignment to it, waits for the
90-second assignment deadline and reassignment, then checks the output and scores it against the
supplied labels. Evidence is written to --out as evidence.json and master.log.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "local-assets" / "models" / "eng.traineddata"
ASSIGN = re.compile(
    r"ASSIGN image_id=(?P<image>\S+) file=(?P<file>\S+) node=(?P<node>\S+) "
    r"process=(?P<process>\S+) attempt=(?P<attempt>\d+)"
)
EXPIRE = re.compile(
    r"EXPIRE image_id=(?P<image>\S+) file=(?P<file>\S+) node=(?P<node>\S+) "
    r"process=(?P<process>\S+) outcome=(?P<outcome>\S+)"
)


def run(*cmd: str, check: bool = True) -> str:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed ({result.returncode}):\n{result.stderr}")
    return (result.stdout + result.stderr).strip()


def compose(*args: str, check: bool = True) -> str:
    return run("docker", "compose", *args, check=check)


def container_ids(service: str) -> list[str]:
    ids = compose("ps", "-a", "-q", service).split()
    return sorted(ids, key=lambda cid: run("docker", "inspect", "-f", "{{.Name}}", cid))


def inspect(container: str, template: str) -> str:
    return run("docker", "inspect", "-f", template, container)


def attempt_once(nodes: int, timeout: float) -> dict:
    compose("down", "-v", "--remove-orphans", check=False)
    compose("build")
    compose("create", "--scale", f"worker={nodes}")
    for index in range(1, nodes + 1):
        compose(
            "cp",
            "--index",
            str(index),
            str(MODEL),
            "worker:/app/local-assets/models/eng.traineddata",
        )
    started = time.monotonic()
    compose("up", "--no-recreate", "--scale", f"worker={nodes}", "-d")
    workers = container_ids("worker")
    master = container_ids("master")[0]
    hostnames = {cid: inspect(cid, "{{.Config.Hostname}}") for cid in workers}
    victim = workers[0]

    lines: list[str] = []
    event: dict = {}
    stream = subprocess.Popen(
        ["docker", "compose", "logs", "-f", "--no-log-prefix", "master"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    watchdog = threading.Timer(timeout, stream.kill)
    watchdog.start()
    assert stream.stdout is not None
    for line in stream.stdout:
        line = line.rstrip()
        lines.append(line)
        match = ASSIGN.search(line)
        if match and not event and match["node"] == hostnames[victim]:
            # Freeze first so the assignment cannot finish, then kill: an in-flight image is lost.
            run("docker", "pause", victim)
            run("docker", "kill", victim)
            event = {
                "killed_at_s": round(time.monotonic() - started, 3),
                "killed_container": victim[:12],
                "killed_node": match["node"],
                "in_flight": match.groupdict(),
            }
    stream.wait()
    watchdog.cancel()
    finished = time.monotonic() - started
    run("docker", "wait", master)

    exit_codes = {cid[:12]: int(inspect(cid, "{{.State.ExitCode}}")) for cid in [master, *workers]}
    return {
        "lines": lines,
        "event": event,
        "master": master[:12],
        "workers": {cid[:12]: hostnames[cid] for cid in workers},
        "exit_codes": exit_codes,
        "total_s": round(finished, 3),
        "recovery_s": round(finished - event.get("killed_at_s", finished), 3),
    }


def check_run(attempt: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "ocr_results.csv"
    compose("cp", "master:/tmp/ocr_results.csv", str(csv_path), check=False)
    expected = len(list((ROOT / "local-assets" / "dataset" / "images").glob("*.png")))
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8"))) if csv_path.exists() else []
    names = [row["filename"] for row in rows]
    event = attempt["event"]
    lines = attempt["lines"]
    in_flight = event.get("in_flight", {})
    expiries = [m for m in map(EXPIRE.search, lines) if m and m["image"] == in_flight.get("image")]
    reassigned = [
        m
        for m in map(ASSIGN.search, lines)
        if m and m["image"] == in_flight.get("image") and int(m["attempt"]) > 1
    ]
    score = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "scripts/evaluate_pipeline.py",
            str(csv_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    codes = attempt["exit_codes"]
    killed = event.get("killed_container")
    checks = {
        "worker killed while an assignment was in flight": bool(event),
        "master logged the expired assignment": bool(expiries),
        "image reassigned to another node": any(
            m["node"] != event.get("killed_node") for m in reassigned
        ),
        "master exit 0": codes[attempt["master"]] == 0,
        "surviving workers exit 0": all(
            code == 0 for cid, code in codes.items() if cid not in (attempt["master"], killed)
        ),
        f"{expected} rows, one per image": len(rows) == expected and len(set(names)) == expected,
        "evaluate-pipeline passes": score.returncode == 0,
    }
    (out / "master.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "evaluation.txt").write_text(score.stdout + score.stderr, encoding="utf-8")
    return {"checks": checks, "evaluation": (score.stdout + score.stderr).strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=2, help="worker containers (at least 2)")
    parser.add_argument("--processes", type=int, default=2, help="processes per worker node")
    parser.add_argument("--attempts", type=int, default=3, help="retries if the kill misses")
    parser.add_argument("--timeout", type=float, default=420, help="seconds before aborting a run")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "acceptance")
    args = parser.parse_args()
    if args.nodes < 2:
        raise SystemExit("--nodes must be at least 2 so a survivor can finish the image")
    if not MODEL.exists():
        raise SystemExit(f"missing supplied model: {MODEL}")

    os.environ["N_WORKERS"] = str(args.processes)
    evidence: dict = {
        "host": platform.node(),
        "commit": run("git", "rev-parse", "HEAD"),
        "docker": run("docker", "--version"),
        "compose": compose("version", "--short"),
        "topology": {"master": 1, "worker_nodes": args.nodes, "processes_per_node": args.processes},
    }
    try:
        for number in range(1, args.attempts + 1):
            attempt = attempt_once(args.nodes, args.timeout)
            result = check_run(attempt, args.out / f"attempt-{number}")
            evidence["attempts"] = evidence.get("attempts", []) + [
                {
                    "number": number,
                    **{k: v for k, v in attempt.items() if k != "lines"},
                    **result,
                }
            ]
            print(json.dumps(evidence["attempts"][-1], indent=2))
            if all(result["checks"].values()):
                evidence["passed"] = True
                break
        else:
            evidence["passed"] = False
    finally:
        compose("down", "-v", "--remove-orphans", check=False)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
