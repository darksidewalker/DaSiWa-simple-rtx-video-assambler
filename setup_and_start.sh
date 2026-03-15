#!/bin/bash

# 1. Check/Install UV
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing now..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the env to make uv available immediately
    source $HOME/.local/bin/env 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Sync venv and deps
echo "Syncing virtual environment..."
uv venv
uv pip install -r requirements.txt --quiet

# 3. Run the tool
echo "Launching ..."
uv run python3 vid_tool.py