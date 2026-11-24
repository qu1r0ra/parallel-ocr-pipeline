from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
benchmark_cloud = importlib.import_module("benchmark_cloud")


def stamped(*lines: tuple[float, str]) -> str:
    return "\n".join(f"{stamp:.6f} {message}" for stamp, message in lines)


def test_parse_nodes_names_master_first() -> None:
    nodes = benchmark_cloud.parse_nodes("h:1,h:2,h:3")
    assert [(n.name, n.port) for n in nodes] == [("server0", 1), ("server1", 2), ("server2", 3)]


@pytest.mark.parametrize("text", ["h:1,h:2", "h:1,h:2,h:x", "h:1,h:2,:3"])
def test_parse_nodes_rejects_malformed_lists(text: str) -> None:
    with pytest.raises(SystemExit):
        benchmark_cloud.parse_nodes(text)


def test_plan_covers_one_to_eight_at_both_node_counts() -> None:
    plan, skipped = benchmark_cloud.build_plan([1, 2], list(range(1, 9)))
    assert len(plan) == 16
    assert skipped == []
    assert {nodes for nodes, _ in plan} == {1, 2}


def test_plan_skips_settings_over_the_master_cap() -> None:
    plan, skipped = benchmark_cloud.build_plan([2], [8, 16, 17], cap=32)
    assert plan == [(2, 8), (2, 16)]
    assert skipped == [(2, 17)]


def test_window_uses_the_master_clock_between_first_assign_and_completed() -> None:
    log = stamped(
        (100.0, "Master ready at PYRO:ocr.master@0.0.0.0:5000; queued 2 image(s)."),
        (101.5, "ASSIGN image_id=1 file=img0001.png node=a process=1:x attempt=1"),
        (102.0, "ASSIGN image_id=2 file=img0002.png node=a process=2:y attempt=1"),
        (104.25, "Completed 2 image(s)."),
    )
    facts = benchmark_cloud.parse_master_log(log)
    assert facts.assigns == 2
    assert facts.window_s == 2.75


def test_window_is_missing_without_a_completed_line() -> None:
    log = stamped((1.0, "ASSIGN image_id=1 file=img0001.png node=a process=1:x attempt=1"))
    assert benchmark_cloud.parse_master_log(log).window_s is None


def test_expire_lines_are_collected() -> None:
    log = stamped(
        (1.0, "EXPIRE image_id=3 file=img0003.png node=a process=1:x outcome=requeued"),
    )
    assert benchmark_cloud.parse_master_log(log).expires == [
        "EXPIRE image_id=3 file=img0003.png node=a process=1:x outcome=requeued"
    ]


def valid_kwargs(**overrides) -> dict:
    facts = benchmark_cloud.LogFacts(first_assign=1.0, completed=2.0, assigns=3)
    rows = [{"filename": f"img{n}.png"} for n in range(3)]
    base = {
        "exit_codes": [0, 0, 0],
        "rows": rows,
        "expected": 3,
        "facts": facts,
        "score_ok": True,
    }
    return base | overrides


def test_a_clean_sample_is_valid() -> None:
    assert benchmark_cloud.sample_is_valid(**valid_kwargs())


@pytest.mark.parametrize(
    "overrides",
    [
        {"exit_codes": [0, 1, 0]},
        {"rows": [{"filename": "a.png"}, {"filename": "a.png"}, {"filename": "b.png"}]},
        {"rows": [{"filename": "a.png"}]},
        {"score_ok": False},
        {"facts": benchmark_cloud.LogFacts(first_assign=1.0, completed=None, assigns=3)},
        {"facts": benchmark_cloud.LogFacts(first_assign=1.0, completed=2.0, assigns=4)},
    ],
)
def test_any_broken_rule_invalidates_the_sample(overrides: dict) -> None:
    assert not benchmark_cloud.sample_is_valid(**valid_kwargs(**overrides))


def test_reassignment_allows_extra_assigns_only_when_injecting_a_fault() -> None:
    facts = benchmark_cloud.LogFacts(first_assign=1.0, completed=2.0, assigns=5)
    assert not benchmark_cloud.sample_is_valid(**valid_kwargs(facts=facts))
    assert benchmark_cloud.sample_is_valid(**valid_kwargs(facts=facts, allow_reassignment=True))


def test_master_script_stamps_output_on_the_master_and_isolates_the_run() -> None:
    script = benchmark_cloud.master_script("/root/run/r1")
    assert "EPOCHREALTIME" in script
    assert "image_dir=/root/ocr/local-assets/dataset/images" in script
    assert "rm -rf /root/run/r1" in script
    assert "/root/run/r1/master.exit" in script


def test_worker_script_points_at_the_master_with_the_process_count() -> None:
    script = benchmark_cloud.worker_script("/root/run/r1", "10.20.201.36", 6)
    assert "master_host=10.20.201.36" in script
    assert "n_workers=6" in script
    assert "/root/run/r1/worker.exit" in script


def test_worker_script_arms_a_local_kill_timer_only_for_the_fault_node() -> None:
    plain = benchmark_cloud.worker_script("/root/run/r1", "10.0.0.1", 1)
    armed = benchmark_cloud.worker_script("/root/run/r1", "10.0.0.1", 1, kill_after_s=2.5)
    assert "pkill -9" not in plain
    assert "sleep 2.5" in armed
    assert "pkill -9" in armed
    assert "run_worke[r]" in armed  # the timer must not match its own command line
    assert "multiprocessin[g]" in armed  # spawn children omit run_worker.py


def environment(**overrides: str) -> dict[str, dict[str, str]]:
    node = {
        "commit": "abc",
        "model_sha256": "m",
        "tesseract": "tesseract 5.3.4",
        "python": "Python 3.15.2",
        "vcpus": "2",
        "mem_mib": "4096",
    }
    result = {name: dict(node) for name in ("server0", "server1", "server2")}
    result["server0"]["dataset_sha256"] = "d"
    for key, value in overrides.items():
        result["server1"][key] = value
    return result


def test_matching_environments_are_comparable() -> None:
    assert benchmark_cloud.check_environment(environment()) == []


@pytest.mark.parametrize("key", ["commit", "model_sha256", "tesseract", "vcpus"])
def test_a_node_that_differs_makes_the_run_non_comparable(key: str) -> None:
    assert benchmark_cloud.check_environment(environment(**{key: "other"}))


def test_missing_dataset_on_the_master_is_a_problem() -> None:
    env = environment()
    del env["server0"]["dataset_sha256"]
    assert benchmark_cloud.check_environment(env)
