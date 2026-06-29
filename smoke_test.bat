@echo off
title DocScrub Smoke Test
cd /d "%~dp0"

echo.
echo  ============================================================
echo    DocScrub Smoke Test
echo  ============================================================
echo.

:: ------------------------------------------------------------------
:: 1. Fresh database
:: ------------------------------------------------------------------
if exist docscrub.db (
    echo  [1/4] Deleting existing database for a clean run...
    del /f /q docscrub.db
) else (
    echo  [1/4] No existing database -- starting fresh.
)

:: ------------------------------------------------------------------
:: 2. Start uvicorn in a minimised background window
:: ------------------------------------------------------------------
echo  [2/4] Starting server...
if exist smoke_server.log del /f /q smoke_server.log
start "DocScrub-SmokeTest" /min cmd /c "python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --log-level warning --no-access-log > smoke_server.log 2>&1"

:: ------------------------------------------------------------------
:: 3. Poll /health until ready (up to 30 seconds)
:: ------------------------------------------------------------------
echo  [3/4] Waiting for server to be ready...
python -c "
import urllib.request, time, sys
for i in range(30):
    try:
        urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)
        print('  Server ready.')
        sys.exit(0)
    except Exception:
        time.sleep(1)
print('  ERROR: Server did not respond after 30 seconds.')
sys.exit(1)
"
if errorlevel 1 (
    echo.
    echo  Server failed to start. Check smoke_server.log for details.
    echo.
    pause
    exit /b 1
)

:: ------------------------------------------------------------------
:: 4. Run smoke tests
:: ------------------------------------------------------------------
echo  [4/4] Running smoke tests...
echo.
python smoke_test.py
set SMOKE_RESULT=%errorlevel%

:: ------------------------------------------------------------------
:: Cleanup: give server 3 seconds to handle /shutdown (called inside
:: smoke_test.py), then force-kill the server window as a safety net.
:: ------------------------------------------------------------------
timeout /t 3 /nobreak >nul
taskkill /fi "WINDOWTITLE eq DocScrub-SmokeTest" /f >nul 2>&1

echo.
if %SMOKE_RESULT% equ 0 (
    echo  ============================================================
    echo    ALL TESTS PASSED
    echo  ============================================================
    echo.
    echo  Window closes in 10 seconds...
    timeout /t 10 /nobreak >nul
) else (
    echo  ============================================================
    echo    SOME TESTS FAILED
    echo  ============================================================
    echo.
    echo  Check the output above for details.
    echo  Server log: smoke_server.log
    echo.
    pause
)
