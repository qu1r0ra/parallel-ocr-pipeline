"""Benchmark the cloud cluster over SSH: native master and workers on three LXC containers.

Run on the owner's PC. Every sample starts a fresh master and worker nodes, runs the full
workload, and counts only if every process exits 0, the CSV has one row per image with unique
filenames, the master assigned each image exactly once, and `evaluate-pipeline` passes.

Timing comes from the master's own log, never from SSH latency: the master's stdout is stamped
with `$EPOCHREALTIME` on the master host, so ``window_s`` (first ASSIGN to "Completed") uses one
clock. ``total_s`` (master launch until its exit file is seen) includes startup and SSH polling.

Endpoints are never committed: pass ``--nodes host:port,host:port,host:port`` (master first) or
set ``CLOUD_NODES``. Read ``docs/cloud-containers.md`` before using this.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmark_cluster import summarize
from parallel_ocr_pipeline.distributed import MAX_ACTIVE_WORKERS

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/root/ocr"
REMOTE_RUNS = "/root/run"
UV_PATH = "export PATH=/root/.local/bin:$PATH"
DEFAULT_KEY = Path.home() / ".ssh" / "csc611m_cloud"
DEFAULT_MASTER_IP = "10.20.201.36"
MASTER_PORT = 5000
IMAGE_DIR = f"{REMOTE_ROOT}/local-assets/dataset/images"
MASTER_TIMEOUT_S = 600
WORKER_EXIT_TIMEOUT_S = 90
READY_TIMEOUT_S = 60
FAULT_TRIGGER_ASSIGNS = 20
LOG_LINE = re.compile(r"^(\d+\.\d+) (.*)$")


@dataclass(frozen=True)
class Node:
    name: str
    host: str
    port: int


@dataclass
class LogFacts:
    first_assign: float | None = None
    completed: float | None = None
    assigns: int = 0
    expires: list[str] = field(default_factory=list)

    @property
    def window_s(self) -> float | None:
        if self.first_assign is None or self.completed is None:
            return None
        return self.completed - self.first_assign


def parse_nodes(text: str) -> list[Node]:
    """Parse ``host:port`` triples, master first, naming them server0..server2."""
    entries = [part.strip() for part in text.split(",") if part.strip()]
    if len(entries) != 3:
        raise SystemExit(f"expected 3 host:port entries (master first), got {len(entries)}")
    nodes = []
    for index, entry in enumerate(entries):
        host, _, port = entry.rpartition(":")
        if not host or not port.isdigit():
            raise SystemExit(f"bad node entry {index}: expected host:port")
        nodes.append(Node(f"server{index}", host, int(port)))
    return nodes


def build_plan(
    node_counts: list[int], proc_counts: list[int], cap: int = MAX_ACTIVE_WORKERS
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (runnable, skipped) ``(nodes, procs)`` settings; the master caps active processes."""
    settings = [(n, p) for n in node_counts for p in proc_counts]
    return [s for s in settings if s[0] * s[1] <= cap], [s for s in settings if s[0] * s[1] > cap]


def parse_master_log(text: str) -> LogFacts:
    """Read the stamped master log: first ASSIGN, Completed, ASSIGN count, EXPIRE lines."""
    facts = LogFacts()
    for line in text.splitlines():
        match = LOG_LINE.match(line)
        if not match:
            continue
        stamp, message = float(match[1]), match[2]
        if message.startswith("ASSIGN "):
            facts.assigns += 1
            facts.first_assign = facts.first_assign or stamp
        elif message.startswith("EXPIRE "):
            facts.expires.append(message)
        elif message.startswith("Completed"):
            facts.completed = stamp
    return facts


def sample_is_valid(
    *,
    exit_codes: list[int],
    rows: list[dict[str, str]],
    expected: int,
    facts: LogFacts,
    score_ok: bool,
    allow_reassignment: bool = False,
) -> bool:
    """Apply the same validity rules as the local benchmark."""
    assigned_once = facts.assigns == expected or (allow_reassignment and facts.assigns > expected)
    return (
        all(code == 0 for code in exit_codes)
        and len(rows) == expected
        and len({row["filename"] for row in rows}) == expected
        and assigned_once
        and score_ok
        and facts.window_s is not None
    )


def master_script(run: str) -> str:
    """Shell script that starts the master detached, stamping each stdout line on the master."""
    return f"""set -e
{UV_PATH}
pkill -f 'scripts/run_(master|worker)\\.py' || true
rm -rf {run}; mkdir -p {run}
printf 'image_dir={IMAGE_DIR}\\nport={MASTER_PORT}\\n' > {run}/master_config.txt
cd {REMOTE_ROOT}
setsid nohup bash -c '( uv run --no-sync python -u scripts/run_master.py {run}/master_config.txt \
2>&1; echo $? > {run}/master.exit ) | while IFS= read -r l; \
do printf "%s %s\\n" "$EPOCHREALTIME" "$l"; done > {run}/master.log' \
>/dev/null 2>&1 < /dev/null &
"""


def worker_script(run: str, master_ip: str, procs: int) -> str:
    """Shell script that starts one worker node with ``procs`` processes, detached."""
    return f"""set -e
{UV_PATH}
pkill -f 'scripts/run_(master|worker)\\.py' || true
rm -rf {run}; mkdir -p {run}
printf 'master_host={master_ip}\\nmaster_port={MASTER_PORT}\\nn_workers={procs}\\n' \
> {run}/worker_config.txt
cd {REMOTE_ROOT}
setsid nohup bash -c '( uv run --no-sync python -u scripts/run_worker.py {run}/worker_config.txt \
> {run}/worker.log 2>&1; echo $? > {run}/worker.exit )' >/dev/null 2>&1 < /dev/null &
"""


class Cluster:
    """SSH access to the three containers."""

    def __init__(self, nodes: list[Node], key: Path, master_ip: str) -> None:
        self.master, *self.workers = nodes
        self.nodes = nodes
        self.key = key
        self.master_ip = master_ip

    def ssh(
        self, node: Node, script: str, timeout: float = 120, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a bash script on ``node``; retry transient SSH failures (exit 255)."""
        command = [
            "ssh",
            "-i",
            str(self.key),
            "-p",
            str(node.port),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"root@{node.host}",
            "bash -s",
        ]
        result = subprocess.CompletedProcess(command, 255, "", "")
        for _ in range(3):
            result = subprocess.run(
                command, input=script, capture_output=True, text=True, timeout=timeout, check=False
            )
            if result.returncode != 255:
                break
            time.sleep(2)
        if check and result.returncode != 0:
            raise RuntimeError(f"{node.name}: ssh exit {result.returncode}: {result.stderr[-400:]}")
        return result

    def scp(self, node: Node, local: Path, remote: str) -> None:
        subprocess.run(
            [
                "scp",
                "-i",
                str(self.key),
                "-P",
                str(node.port),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                str(local),
                f"root@{node.host}:{remote}",
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )

    def wait_for(self, node: Node, test: str, timeout: float, interval: float = 1.0) -> bool:
        """Poll a shell ``test`` on ``node`` until it succeeds or ``timeout`` passes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ssh(node, test, check=False).returncode == 0:
                return True
            time.sleep(interval)
        return False


def read_csv_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def stop_all(cluster: Cluster) -> None:
    for node in cluster.nodes:
        cluster.ssh(node, "pkill -f 'scripts/run_(master|worker)\\.py' || true", check=False)


def run_sample(
    cluster: Cluster,
    run_id: str,
    nodes: int,
    procs: int,
    expected: int,
    *,
    fault_node: Node | None = None,
) -> dict:
    """Run one fresh master plus ``nodes`` worker nodes; return the sample record."""
    run = f"{REMOTE_RUNS}/{run_id}"
    active = cluster.workers[:nodes]
    started = time.monotonic()
    cluster.ssh(cluster.master, master_script(run))
    ready = cluster.wait_for(
        cluster.master, f"grep -q 'Master ready' {run}/master.log", READY_TIMEOUT_S
    )
    if not ready:
        stop_all(cluster)
        return {"nodes": nodes, "procs": procs, "valid": False, "error": "master not ready"}
    for node in active:
        cluster.ssh(node, worker_script(run, cluster.master_ip, procs))
    killed = False
    if fault_node is not None:
        reached = cluster.wait_for(
            cluster.master,
            f"[ $(grep -c ' ASSIGN ' {run}/master.log) -ge {FAULT_TRIGGER_ASSIGNS} ]",
            MASTER_TIMEOUT_S,
            interval=0.5,
        )
        if reached:
            cluster.ssh(fault_node, "pkill -9 -f 'scripts/run_worker\\.py' || true", check=False)
            killed = True
    finished = cluster.wait_for(cluster.master, f"test -s {run}/master.exit", MASTER_TIMEOUT_S)
    total = time.monotonic() - started
    for node in active:
        cluster.wait_for(node, f"test -s {run}/worker.exit", WORKER_EXIT_TIMEOUT_S)

    exit_codes = []
    for node in [cluster.master, *active]:
        name = "master" if node is cluster.master else "worker"
        code = cluster.ssh(node, f"cat {run}/{name}.exit 2>/dev/null || echo 255", check=False)
        value = int(code.stdout.strip() or 255)
        if node is fault_node and killed:
            continue  # the killed node's exit status is the injected fault, not a failure
        exit_codes.append(value)
    log = cluster.ssh(cluster.master, f"cat {run}/master.log", check=False).stdout
    csv_text = cluster.ssh(
        cluster.master, f"cat {run}/ocr_results.csv 2>/dev/null", check=False
    ).stdout
    score = cluster.ssh(
        cluster.master,
        f"{UV_PATH}; cd {REMOTE_ROOT}; uv run --no-sync python scripts/evaluate_pipeline.py "
        f"{run}/ocr_results.csv",
        check=False,
    )
    stop_all(cluster)

    facts = parse_master_log(log)
    rows = read_csv_rows(csv_text)
    valid = finished and sample_is_valid(
        exit_codes=exit_codes,
        rows=rows,
        expected=expected,
        facts=facts,
        score_ok=score.returncode == 0,
        allow_reassignment=fault_node is not None,
    )
    return {
        "nodes": nodes,
        "procs": procs,
        "total_s": round(total, 3),
        "window_s": round(facts.window_s, 3) if facts.window_s is not None else "",
        "valid": bool(valid),
        "assigns": facts.assigns,
        "expires": facts.expires,
        "killed_worker_node": fault_node.name if killed and fault_node else "",
        "accuracy": (score.stdout + score.stderr).strip().splitlines()[-1:],
        "run_dir": run,
    }


ENVIRONMENT_SCRIPT = f"""{UV_PATH}
cd {REMOTE_ROOT}
echo hostname=$(hostname)
echo vcpus=$(nproc)
echo mem_mib=$(free -m | awk '/Mem:/ {{print $2}}')
echo kernel=$(uname -r)
echo tesseract=$(tesseract --version 2>&1 | head -1)
echo python=$(uv run --no-sync python --version)
echo commit=$(cat COMMIT 2>/dev/null)
echo model_sha256=$(sha256sum local-assets/models/eng.traineddata | cut -d' ' -f1)
if [ -d {IMAGE_DIR} ]; then
  echo images=$(ls {IMAGE_DIR} | wc -l)
  echo dataset_sha256=$(cd {IMAGE_DIR} && for f in img*.png; do sha256sum "$f" | cut -d' ' -f1; done | sha256sum | cut -d' ' -f1)
fi
"""


def read_environment(cluster: Cluster) -> dict[str, dict[str, str]]:
    """Collect hostnames, resources, versions, commit and hashes from every node."""
    environment = {}
    for node in cluster.nodes:
        output = cluster.ssh(node, ENVIRONMENT_SCRIPT).stdout
        environment[node.name] = dict(
            line.split("=", 1) for line in output.splitlines() if "=" in line
        )
    return environment


def check_environment(environment: dict[str, dict[str, str]]) -> list[str]:
    """Return problems that make a run non-comparable: mixed commits, models or versions."""
    problems = []
    for key in ("commit", "model_sha256", "tesseract", "python", "vcpus", "mem_mib"):
        values = {node: env.get(key, "") for node, env in environment.items()}
        if len(set(values.values())) != 1 or not any(values.values()):
            problems.append(f"{key} differs or is missing: {values}")
    if not environment["server0"].get("dataset_sha256"):
        problems.append("server0 has no dataset")
    return problems


def deploy(cluster: Cluster) -> None:
    """Ship ``git archive HEAD`` to every node and sync dependencies; record the commit."""
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        print("warning: uncommitted changes are not deployed (git archive HEAD)", file=sys.stderr)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    tarball = ROOT / "results" / "cloud-deploy.tgz"
    tarball.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "-o", str(tarball), "HEAD"], cwd=ROOT, check=True
    )
    for node in cluster.nodes:
        cluster.scp(node, tarball, "/root/repo.tgz")
        cluster.ssh(
            node,
            f"""set -e
{UV_PATH}
pkill -f 'scripts/run_(master|worker)\\.py' || true
mkdir -p {REMOTE_ROOT}
find {REMOTE_ROOT} -mindepth 1 -maxdepth 1 ! -name local-assets ! -name .venv -exec rm -rf {{}} +
tar --no-same-owner -xzf /root/repo.tgz -C {REMOTE_ROOT}
echo {sha} > {REMOTE_ROOT}/COMMIT
cd {REMOTE_ROOT} && uv sync --locked --no-dev
""",
            timeout=600,
        )
        print(f"deployed {sha[:7]} to {node.name}", flush=True)


def ints(text: str) -> list[int]:
    return [int(part) for part in text.split(",")]


def write_summary(out: Path, summary: dict) -> None:
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, indent=2))


def command_sweep(cluster: Cluster, args: argparse.Namespace, out: Path) -> int:
    environment = read_environment(cluster)
    problems = check_environment(environment)
    if problems:
        raise SystemExit("environment not comparable:\n" + "\n".join(problems))
    expected = int(environment["server0"]["images"])
    plan, skipped = build_plan(args.node_counts, args.proc_counts)
    for nodes, procs in skipped:
        print(
            f"skip {nodes} nodes x {procs} procs: {nodes * procs} exceeds the master's "
            f"{MAX_ACTIVE_WORKERS} active worker-process cap",
            file=sys.stderr,
        )
    samples: list[dict] = []
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        for rep in range(1, args.reps + 1):
            # Interleave settings within each repetition so drift hits every setting.
            for nodes, procs in plan:
                run_id = f"{stamp}-n{nodes}p{procs}-r{rep}"
                sample = run_sample(cluster, run_id, nodes, procs, expected)
                sample |= {"sweep": "procs", "rep": rep}
                samples.append(sample)
                print(json.dumps(sample), flush=True)
    finally:
        stop_all(cluster)
    invalid = [s for s in samples if not s["valid"]]
    node_samples = [s | {"sweep": "nodes"} for s in samples if s["procs"] == args.node_procs]
    write_summary(
        out,
        {
            "environment": environment,
            "reps": args.reps,
            "invalid_samples": len(invalid),
            "node_sweep_procs_per_node": args.node_procs,
            "node_sweep": summarize(node_samples, "nodes", "nodes") if node_samples else [],
            "proc_sweeps": {
                str(n): summarize(samples, "procs", "procs", n)
                for n in args.node_counts
                if any(s["nodes"] == n and s["valid"] for s in samples)
            },
            "samples": samples,
        },
    )
    return 1 if invalid else 0


def command_fault(cluster: Cluster, args: argparse.Namespace, out: Path) -> int:
    environment = read_environment(cluster)
    problems = check_environment(environment)
    if problems:
        raise SystemExit("environment not comparable:\n" + "\n".join(problems))
    expected = int(environment["server0"]["images"])
    run_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-fault"
    sample = run_sample(cluster, run_id, 2, args.procs, expected, fault_node=cluster.workers[1])
    reassigned = any("outcome=requeued" in line for line in sample.get("expires", []))
    sample["reassigned"] = reassigned
    write_summary(out, {"environment": environment, "fault": sample})
    return 0 if sample["valid"] and reassigned else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", default=os.environ.get("CLOUD_NODES", ""), help="host:port x3")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--master-ip", default=DEFAULT_MASTER_IP, help="master's private IP")
    parser.add_argument("--out", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("deploy", help="ship git archive HEAD and sync dependencies")
    commands.add_parser("check", help="print the environment and any comparability problems")
    sweep = commands.add_parser("sweep", help="process sweep at 1 and 2 worker nodes")
    sweep.add_argument("--node-counts", type=ints, default=[1, 2])
    sweep.add_argument("--proc-counts", type=ints, default=list(range(1, 9)))
    sweep.add_argument("--node-procs", type=int, default=2, help="processes/node, node pair")
    sweep.add_argument("--reps", type=int, default=5)
    fault = commands.add_parser("fault", help="kill one worker node mid-run; expect reassignment")
    fault.add_argument("--procs", type=int, default=2)
    args = parser.parse_args()
    if not args.nodes:
        raise SystemExit("pass --nodes host:port,host:port,host:port or set CLOUD_NODES")
    cluster = Cluster(parse_nodes(args.nodes), args.key, args.master_ip)

    if args.command == "deploy":
        deploy(cluster)
        return 0
    if args.command == "check":
        environment = read_environment(cluster)
        print(json.dumps(environment, indent=2))
        problems = check_environment(environment)
        print("\n".join(problems) or "environment comparable")
        return 1 if problems else 0

    out = args.out or ROOT / "results" / "benchmark-cloud" / dt.datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    out.mkdir(parents=True, exist_ok=True)
    return (command_sweep if args.command == "sweep" else command_fault)(cluster, args, out)


if __name__ == "__main__":
    sys.exit(main())
