@echo off
REM arr launcher - bootstraps via uv and forwards all args.
setlocal EnableExtensions EnableDelayedExpansion

REM Always operate from the repo root, regardless of where the script was
REM invoked from (Explorer double-click, shortcut, or another working dir).
pushd "%~dp0" || (
    echo Failed to change directory to "%~dp0".
    pause
    exit /b 1
)

REM Locate uv. Explorer/GUI processes can have a stale PATH, so also probe the
REM common install locations before giving up.
set "UV="
for %%P in (uv.exe uv) do (
    if not defined UV for %%Q in (%%~$PATH:P) do set "UV=%%~fQ"
)
if not defined UV (
    for %%D in (
        "%USERPROFILE%\.local\bin\uv.exe"
        "%USERPROFILE%\.cargo\bin\uv.exe"
        "%APPDATA%\uv\uv.exe"
        "%LOCALAPPDATA%\Programs\uv\uv.exe"
        "%USERPROFILE%\scoop\shims\uv.exe"
    ) do (
        if not defined UV if exist "%%~D" set "UV=%%~fD"
    )
)
if not defined UV (
    echo.
    echo [arr] uv is not installed or not on PATH. Install it with:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo Then re-run this script.
    pause
    popd
    exit /b 1
)

"%UV%" python find 3.11 >nul 2>nul
if errorlevel 1 (
    echo [arr] No Python 3.11 found; uv will fetch one automatically on first sync.
)

echo [arr] Syncing environment (uv sync)...
"%UV%" sync
if errorlevel 1 (
    echo.
    echo [arr] uv sync failed with exit code %errorlevel%.
    pause
    popd
    exit /b 1
)

REM No arguments (typical Explorer double-click): show help and keep the window
REM open so the output is readable.
if "%~1"=="" (
    echo.
    "%UV%" run arr --help
    echo.
    echo [arr] Provide arguments, e.g.:
    echo   run.bat search movie "Inception"
    echo   run.bat download movie "Inception" --auto
    pause
    popd
    exit /b 0
)

"%UV%" run arr %*
set "rc=!errorlevel!"
popd
if not "!rc!"=="0" (
    echo.
    echo [arr] arr exited with code !rc!.
    pause
)
exit /b !rc!
