# 1. Check/Install UV
if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Installing now..." -ForegroundColor Cyan
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    # Refresh Path for the current session
    $env:Path += ";$HOME\.local\bin"
}

# 2. Ensure venv exists and deps are synced
Write-Host "Syncing virtual environment..." -ForegroundColor Cyan
uv venv
uv pip install -r requirements.txt --quiet

# 3. Run the tool
Write-Host "Launching ..." -ForegroundColor Green
uv run python vid_tool.py