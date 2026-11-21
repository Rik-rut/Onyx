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

REM Locate uv. Check local bin/ folder first for 100% portability.
set "UV="
if exist "%~dp0bin\uv.exe" set "UV=%~dp0bin\uv.exe"
if not defined UV if exist "%~dp0uv.exe" set "UV=%~dp0uv.exe"
if not defined UV for %%P in (uv.exe uv) do (
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

REM Auto-build the compiled SPA when it is missing (fresh clone / cleaned tree).
if exist "src\arr\web\static\dist\index.html" goto :spa_ready
echo [arr] Compiled SPA missing; building frontend...
where npm >nul 2>nul
if errorlevel 1 goto :spa_no_node
cd frontend
if not exist node_modules call npm install
if errorlevel 1 goto :spa_failed
call npm run build
if errorlevel 1 goto :spa_failed
cd ..
if not exist "src\arr\web\static\dist\index.html" goto :spa_failed
goto :spa_ready
:spa_no_node
echo.
echo [arr] Node/npm not found. Install Node 22+, then build the UI manually:
echo   cd frontend ^&^& npm install ^&^& npm run build
echo Continuing without compiled assets; the web UI will show a diagnostic.
goto :spa_ready
:spa_failed
echo.
echo [arr] Frontend build failed. Install Node 22+ and run:
echo   cd frontend ^&^& npm install ^&^& npm run build
pause
popd
exit /b 1
:spa_ready

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

REM No arguments (e.g. Explorer double-click or terminal without flags):
REM Default to Web UI first with browser auto-open (R22.4).
if "%~1"=="" (
    "%UV%" run arr web --open-browser
    set "rc=!errorlevel!"
    popd
    if not "!rc!"=="0" (
        echo.
        echo [arr] arr exited with code !rc!.
        pause
    )
    exit /b !rc!
)

REM CLI shortcut (run.bat cli or run.bat interactive)
if /i "%~1"=="cli" (
    shift
    "%UV%" run arr interactive %*
    set "rc=!errorlevel!"
    popd
    if not "!rc!"=="0" (
        echo.
        echo [arr] arr exited with code !rc!.
        pause
    )
    exit /b !rc!
)
if /i "%~1"=="interactive" (
    shift
    "%UV%" run arr interactive %*
    set "rc=!errorlevel!"
    popd
    if not "!rc!"=="0" (
        echo.
        echo [arr] arr exited with code !rc!.
        pause
    )
    exit /b !rc!
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
