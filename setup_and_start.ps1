# Ensure uv is available
if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found! Please install it from https://astral.sh/uv" -ForegroundColor Red
    pause
    exit
}

Write-Host "Syncing environment with uv..." -ForegroundColor Cyan
uv pip install -r requirements.txt --quiet

Write-Host "Launching RTX 4070 Assembler..." -ForegroundColor Green
uv run python vid_tool.py