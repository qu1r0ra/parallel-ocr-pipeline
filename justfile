set windows-shell := ["powershell", "-NoProfile", "-Command"]

default:
    @just --list

# Install the pinned interpreter, project, development tools, and commit hooks.
setup:
    uv python install 3.11
    uv sync --locked --all-groups
    uv run --no-sync pre-commit install

# Extract only the 100 source PNGs and labels from the local course archive.
prepare-assets:
    uv run --no-sync python scripts/prepare_assets.py

# Diagnose Python packages, Tesseract, supplied model, and prepared dataset.
check-environment:
    uv run --no-sync python scripts/check_environment.py

# Apply the fast Ruff fixes to a path (defaults to the repository).
fix path=".":
    uv run --no-sync ruff check --fix "{{path}}"
    uv run --no-sync ruff format "{{path}}"

# Format Python without running lint fixes.
format path=".":
    uv run --no-sync ruff format "{{path}}"

# Run Ruff linting on a path (defaults to the repository).
check path=".":
    uv run --no-sync ruff check "{{path}}"

# Run the configured static type checker.
typecheck:
    uv run --no-sync basedpyright

# Run the source checks without rewriting project files or refreshing the lock.
verify:
    uv lock --check
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .
    uv run --no-sync basedpyright
    uv run --no-sync python -c "import parallel_ocr_pipeline"

# Run a real Python helper script; this is not an OCR application command.
run path *args:
    uv run --no-sync python "{{path}}" {{args}}
