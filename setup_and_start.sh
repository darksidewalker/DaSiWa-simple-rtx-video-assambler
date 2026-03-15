#!/bin/bash

# Ensure uv is available
if ! command -v uv &> /dev/null; then
    echo "uv could not be found. Please install it first."
    exit 1
fi

echo "Syncing environment with uv..."
uv pip install -r requirements.txt --quiet

echo "Launching ..."
uv run python3 vid_tool.py