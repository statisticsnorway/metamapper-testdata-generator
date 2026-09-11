#!/usr/bin/env bash

set -euo pipefail

LOG_PREFIX="[metamapper-testdata-generator]"
PROJECT_NAME="metamapper-testdata-generator"
PROJECT_DIR="${PROJECT_DIR:-$HOME/work/$PROJECT_NAME}"
KERNEL_NAME="metamapper-testdata-generator"
KERNEL_DISPLAY_NAME="Python (metamapper testdata generator)"

if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    if [[ -f "$(pwd)/pyproject.toml" ]]; then
        PROJECT_DIR="$(pwd)"
    else
        echo "$LOG_PREFIX Could not find pyproject.toml in $PROJECT_DIR or the current directory." >&2
        exit 1
    fi
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "$LOG_PREFIX uv is required but was not found." >&2
    exit 1
fi

echo "$LOG_PREFIX Installing the locked Python environment in $PROJECT_DIR"
uv sync --project "$PROJECT_DIR"

echo "$LOG_PREFIX Registering the notebook kernel"
uv run --project "$PROJECT_DIR" python -m ipykernel install \
    --user \
    --name "$KERNEL_NAME" \
    --display-name "$KERNEL_DISPLAY_NAME"

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

echo "$LOG_PREFIX Environment ready. Select '$KERNEL_DISPLAY_NAME' in VS Code."
