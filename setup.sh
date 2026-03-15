#!/bin/bash

export TK_SILENCE_DEPRECATION=1
export GDK_BACKEND=x11
# Install uv if missing
command -v uv >/dev/null 2>&1 || { curl -LsSf https://astral.sh/uv/install.sh | sh; source $HOME/.cargo/env; }

echo "Refreshing virtual environment..."
uv venv --clear
source .venv/bin/activate
uv pip install -r requirements.txt

python vid_tool.py
