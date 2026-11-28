"""Build the source-only ZIP and check the three handout deliverables.

The handout asks for a source-code ZIP, the output CSV, and the PPT file (no video). The ZIP is a
``git archive`` of ``HEAD``, so only committed source ships; the checks below then confirm that
no environment, secret, course input, model, or run output slipped in.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "submission"
ZIP_NAME = "distributed-ocr-pipeline-source.zip"

# Entries the archive must never contain (fnmatch patterns on forward-slash paths).
FORBIDDEN = (
    ".env",
    ".venv/*",
    ".git/*",
    "results/*",
    "*.traineddata",
    "*.zip",
    "*.pdf",
    "*.csv",
    "*.pptx",
    "*labels.txt",
    "*__MACOSX*",
    "local-assets/dataset/*",
    "local-assets/models/*",
    "local-assets/supplied/*",
)
REQUIRED = (
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "compose.yaml",
    "justfile",
    "src/parallel_ocr_pipeline/distributed.py",
    "scripts/run_master.py",
    "scripts/run_worker.py",
    "docs/requirements-mp2.md",
)


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def audit_zip(names: list[str]) -> list[str]:
    """Return one problem per forbidden or missing entry; an empty list means the ZIP is clean."""
    problems = [
        f"forbidden entry: {name}"
        for name in names
        if any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN)
    ]
    problems += [f"missing required entry: {name}" for name in REQUIRED if name not in names]
    return problems


def check_csv(path: Path) -> list[str]:
    done = subprocess.run(
        ["uv", "run", "--no-sync", "python", "scripts/evaluate_pipeline.py", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode == 0:
        print(done.stdout.strip())
        return []
    return [f"CSV failed evaluation: {(done.stdout + done.stderr).strip()}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="the complete output CSV")
    parser.add_argument("--deck", type=Path, help="the PowerPoint file (reported missing if unset)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for the ZIP")
    args = parser.parse_args()

    problems: list[str] = []
    if git("status", "--porcelain"):
        problems.append("working tree has uncommitted changes; the ZIP would omit them")
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / ZIP_NAME
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={archive}", "HEAD"], cwd=ROOT, check=True
    )
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    problems += audit_zip(names)
    problems += check_csv(args.csv)
    if args.deck is None or not args.deck.is_file() or args.deck.suffix.lower() != ".pptx":
        problems.append("PowerPoint deck missing: pass --deck <file>.pptx")

    print(f"Commit: {git('rev-parse', 'HEAD')}")
    print(f"Source ZIP: {archive} ({len(names)} entries)")
    print(f"Output CSV: {args.csv}")
    print(f"PowerPoint: {args.deck}")
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
