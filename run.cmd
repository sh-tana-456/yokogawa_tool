@echo off
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo Install uv first. See readme.md.
    pause
    exit /b 1
)
uv run --locked --python 3.12 yokogawa-tool %*
