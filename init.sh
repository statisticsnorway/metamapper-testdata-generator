#!/usr/bin/env bash

set -euo pipefail

LOG_PREFIX="[metamapper-testdata-generator]"
PROJECT_NAME="metamapper-testdata-generator"
PROJECT_DIR="${PROJECT_DIR:-$HOME/work/$PROJECT_NAME}"
REPOSITORY_URL="https://github.com/statisticsnorway/metamapper-testdata-generator.git"
KERNEL_NAME="metamapper-testdata-generator"
KERNEL_DISPLAY_NAME="Python (metamapper testdata generator)"
PYTHON="${PYTHON:-python3}"

if [[ ! -d "$PROJECT_DIR" ]] && [[ -f "$(pwd)/notebooks/generate_test_data.ipynb" ]]; then
    PROJECT_DIR="$(pwd)"
fi

if [[ ! -f "$PROJECT_DIR/notebooks/generate_test_data.ipynb" ]]; then
    if [[ -d "$PROJECT_DIR" ]] && [[ -z "$(ls -A "$PROJECT_DIR")" ]]; then
        rmdir "$PROJECT_DIR"
    fi

    if [[ -e "$PROJECT_DIR" ]]; then
        echo "$LOG_PREFIX $PROJECT_DIR exists but is not the expected repository." >&2
        exit 1
    fi

    echo "$LOG_PREFIX Cloning the repository into $PROJECT_DIR"
    mkdir -p "$(dirname "$PROJECT_DIR")"
    git clone "$REPOSITORY_URL" "$PROJECT_DIR"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "$LOG_PREFIX $PYTHON is required but was not found." >&2
    exit 1
fi

VENV_DIR="$PROJECT_DIR/.venv"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/work}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "$LOG_PREFIX Creating the notebook environment in $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

echo "$LOG_PREFIX Installing notebook dependencies"
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check \
    -r "$PROJECT_DIR/requirements.txt"

echo "$LOG_PREFIX Registering the notebook kernel"
"$VENV_DIR/bin/python" -m ipykernel install \
    --user \
    --name "$KERNEL_NAME" \
    --display-name "$KERNEL_DISPLAY_NAME"

echo "$LOG_PREFIX Selecting the project kernel for notebooks"
"$VENV_DIR/bin/python" - "$PROJECT_DIR/notebooks" "$KERNEL_NAME" "$KERNEL_DISPLAY_NAME" <<'PY'
import json
import pathlib
import sys

notebooks_dir = pathlib.Path(sys.argv[1])
kernelspec = {
    "display_name": sys.argv[3],
    "language": "python",
    "name": sys.argv[2],
}

for notebook_path in notebooks_dir.glob("*.ipynb"):
    notebook = json.loads(notebook_path.read_text())
    notebook.setdefault("metadata", {})["kernelspec"] = kernelspec
    notebook_path.write_text(json.dumps(notebook, indent=1) + "\n")
PY

# Make the project interpreter the default interpreter when the repository is
# opened in code-server. The file is local service configuration, not project
# source code.
mkdir -p "$PROJECT_DIR/.vscode"
cat > "$PROJECT_DIR/.vscode/settings.json" <<EOF
{
    "python.defaultInterpreterPath": "$PROJECT_DIR/.venv/bin/python",
    "jupyter.kernels.filter": [
        {
            "path": "$PROJECT_DIR/.venv/bin/python",
            "type": "python"
        }
    ]
}
EOF

# Dapla commonly opens $HOME/work as the code-server workspace, so also place
# the interpreter setting where VS Code can load it for the repository.
mkdir -p "$WORKSPACE_DIR/.vscode"
cat > "$WORKSPACE_DIR/.vscode/settings.json" <<EOF
{
    "python.defaultInterpreterPath": "$VENV_DIR/bin/python"
}
EOF

echo "$LOG_PREFIX Kernel ready: $KERNEL_NAME"

echo "$LOG_PREFIX Environment ready. Select '$KERNEL_DISPLAY_NAME' in VS Code."
