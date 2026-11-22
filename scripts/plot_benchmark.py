"""Render the cluster benchmark sweeps from ``summary.json`` as dependency-free SVG plots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

WIDTH, HEIGHT = 760, 300
LEFT, RIGHT, TOP, BOTTOM = 60, 20, 30, 50
BLUE, GREY, RED = "#1f6feb", "#8b949e", "#cf222e"


def panel(
    x0: int, title: str, xlabel: str, ylabel: str, xs: list[int], series: list[dict]
) -> list[str]:
    """One chart: each series is ``{"ys", "lo", "hi", "color", "line"}`` over shared ``xs``."""
    w = (WIDTH - LEFT - RIGHT) / 2 - 20
    h = HEIGHT - TOP - BOTTOM
    ymax = max(max(s["hi"]) for s in series) * 1.1 or 1.0
    xmin, xmax = min(xs), max(xs)

    def sx(x: float) -> float:
        return x0 + (x - xmin) / ((xmax - xmin) or 1) * w

    def sy(y: float) -> float:
        return TOP + h - y / ymax * h

    out = [
        f'<text x="{x0 + w / 2}" y="18" text-anchor="middle" font-weight="bold">{title}</text>',
        f'<line x1="{x0}" y1="{TOP + h}" x2="{x0 + w}" y2="{TOP + h}" stroke="{GREY}"/>',
        f'<line x1="{x0}" y1="{TOP}" x2="{x0}" y2="{TOP + h}" stroke="{GREY}"/>',
        f'<text x="{x0 + w / 2}" y="{HEIGHT - 10}" text-anchor="middle">{xlabel}</text>',
        (
            f'<text x="{x0 - 42}" y="{TOP + h / 2}" text-anchor="middle" '
            f'transform="rotate(-90 {x0 - 42} {TOP + h / 2})">{ylabel}</text>'
        ),
    ]
    for x in xs:
        out.append(f'<text x="{sx(x)}" y="{TOP + h + 16}" text-anchor="middle">{x}</text>')
    for k in range(5):
        value = ymax * k / 4
        out.append(
            f'<text x="{x0 - 6}" y="{sy(value) + 4}" text-anchor="end">{value:.1f}</text>'
            f'<line x1="{x0}" y1="{sy(value)}" x2="{x0 + w}" y2="{sy(value)}" '
            f'stroke="{GREY}" stroke-opacity="0.2"/>'
        )
    for s in series:
        points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, s["ys"], strict=True))
        dash = ' stroke-dasharray="5 4"' if s["line"] == "dash" else ""
        out.append(
            f'<polyline points="{points}" fill="none" stroke="{s["color"]}" '
            f'stroke-width="2"{dash}/>'
        )
        if s["line"] == "dash":
            continue
        for x, y, lo, hi in zip(xs, s["ys"], s["lo"], s["hi"], strict=True):
            out.append(
                f'<line x1="{sx(x)}" y1="{sy(lo)}" x2="{sx(x)}" y2="{sy(hi)}" '
                f'stroke="{s["color"]}"/><circle cx="{sx(x)}" cy="{sy(y)}" r="3.5" '
                f'fill="{s["color"]}"/>'
            )
    return out


def render(rows: list[dict], key: str, label: str, subtitle: str) -> str:
    xs = [row[key] for row in rows]
    base_n = xs[0]
    runtime = {
        "ys": [r["mean_s"] for r in rows],
        "lo": [r["min_s"] for r in rows],
        "hi": [r["max_s"] for r in rows],
        "color": BLUE,
        "line": "solid",
    }
    speed = {
        "ys": [r["speedup"] for r in rows],
        "lo": [r["speedup"] for r in rows],
        "hi": [r["speedup"] for r in rows],
        "color": BLUE,
        "line": "solid",
    }
    ideal = {
        "ys": [x / base_n for x in xs],
        "lo": [x / base_n for x in xs],
        "hi": [x / base_n for x in xs],
        "color": RED,
        "line": "dash",
    }
    half = (WIDTH - LEFT - RIGHT) / 2
    body = panel(LEFT, "Processing window (mean, min-max)", label, "seconds", xs, [runtime])
    body += panel(
        int(LEFT + half + 20),
        f"Speedup vs {base_n} (dashed: ideal)",
        label,
        "speedup",
        xs,
        [speed, ideal],
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" font-family="sans-serif" font-size="12">'
        f'<title>{subtitle}</title><rect width="100%" height="100%" fill="white"/>'
        + "".join(body)
        + "</svg>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="summary.json from benchmark_cluster.py")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    args = parser.parse_args()
    data = json.loads(args.summary.read_text(encoding="utf-8"))
    out = args.out or args.summary.parent
    out.mkdir(parents=True, exist_ok=True)
    sweeps = [
        (
            "node_sweep",
            data.get("node_sweep", []),
            "nodes",
            "worker nodes",
            f"{data['node_sweep_procs_per_node']} process/node",
        )
    ]
    sweeps += [
        (f"proc_sweep_{n}nodes", rows, "procs", "processes per node", f"{n} worker nodes")
        for n, rows in data.get("proc_sweeps", {}).items()
    ]
    for name, rows, key, label, fixed in sweeps:
        if rows:
            target = out / f"{name}.svg"
            target.write_text(render(rows, key, label, f"{label} sweep, {fixed}"), "utf-8")
            print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
