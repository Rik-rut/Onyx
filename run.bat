@echo off
REM arr launcher - bootstraps via uv and forwards all args.
setlocal

where uv >nul 2>nul
if errorlevel 1 (
    echo uv is not installed. Install it with:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo Then re-run this script.
    pause
    exit /b 1
)
uv python find 3.11 >nul 2>nul
if errorlevel 1 (
    echo No Python 3.11 found; uv will fetch one automatically on first sync.
)
uv sync
if errorlevel 1 (
    echo uv sync failed with exit code %errorlevel%.
    pause
    exit /b %errorlevel%
)
if "%~1"=="" (
    uv run arr --help
) else (
    uv run arr %*
)
set rc=%errorlevel%
if not "%rc%"=="0" (
    echo.
    echo arr exited with code %rc%.
    pause
)
exit /b %rc%
