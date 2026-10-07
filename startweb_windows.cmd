@echo off

REM Parse arguments
set FORCE_SETUP=false
if "%1"=="--force-setup" set FORCE_SETUP=true
if "%1"=="-fs" set FORCE_SETUP=true

cd /d "%~dp0"

echo +--------------------------------------------------------------+
echo ^| Oneirodex // EXPEDITION DECK                  FIELD BOOT   ^|
echo +--------------------------------------------------------------+
echo                         .------.
echo                        /  o  o  \
echo                       ^|    .    ^|     ONEI
echo                       ^|   /\    ^|     map scout - field guide
echo                        \  ____  /      d20 packed - radio tuned
echo                          / ^|\
echo                         /  ^| \
echo                        /___^|__\
echo                           / \
echo                          /___\
echo   QUEST LOG // waking the deck and checking the trail markers...
echo.

call venv\Scripts\activate.bat

REM Load .env file and export variables to shell environment
if exist .env (
    echo [*] Loading environment variables from .env...
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%b"=="" (
            set "%%a=%%b"
        )
    )

    REM Debug: Verify DATABASE_URL is loaded
    if defined DATABASE_URL (
        echo [+] DATABASE_URL loaded from .env
    ) else (
        echo [-] WARNING: DATABASE_URL not found in environment!
    )
) else (
    echo [!] Warning: .env file not found in current directory
)

if not defined PORT set PORT=5006

if "%FORCE_SETUP%"=="true" (
    echo [~] Force setup mode - resetting database...

    REM Environment variables are already loaded from .env file above
    python -c "from oneirodex import create_app, db; from oneirodex.utils.setup import reset_setup_state; app = create_app(); app.app_context().push(); print('Dropping all tables...'); db.drop_all(); print('Recreating all tables...'); db.create_all(); print('Database reset complete.'); reset_setup_state(); print('Setup state reset - setup wizard will run on next startup'); print('Database reset complete. Run startweb_windows.cmd to start the server.')"
    exit /b 0
)

echo ONEI ^> The launch gate is coming online.
echo         Oneirodex will be at http://localhost:%PORT% when ready.

REM Run complete startup initialization once before starting workers
python -c "from oneirodex.init_manager import run_complete_startup_initialization; import sys; print('QUEST LOG // checking the camp ledger and preparing the worlds...'); result = run_complete_startup_initialization(); print('QUEST COMPLETE // initialization ready; opening the launch gate...' if result else ''); sys.exit(0 if result else 1)"

if %errorlevel% neq 0 (
    echo FIELD ALERT // startup did not complete; see the log above.
    exit /b 1
)

REM Ensure environment variables are set for worker processes
set ONEIRODEX_MIGRATIONS_COMPLETE=true
set ONEIRODEX_INITIALIZATION_COMPLETE=true

REM Start uvicorn with workers (migrations already complete)
uvicorn asgi:asgi_app --host 0.0.0.0 --port %PORT% --workers 4
