@echo off
title DocScrub Smoke Test
cd /d "%~dp0"

echo.
echo  ============================================================
echo    DocScrub Smoke Test
echo  ============================================================
echo.

:: 1. Fresh database
if exist docscrub.db (
    echo  [1/3] Deleting existing database for a clean run...
    del /f /q docscrub.db
) else (
    echo  [1/3] No existing database -- starting fresh.
)

:: 2. Start uvicorn in a minimised background window
echo  [2/3] Starting server...
if exist smoke_server.log del /f /q smoke_server.log
start "DocScrub-SmokeTest" /min cmd /c "python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --log-level warning --no-access-log > smoke_server.log 2>&1"

:: 3. Run smoke tests (health polling happens inside smoke_test.py)
echo  [3/3] Running smoke tests...
echo.
python smoke_test.py
set SMOKE_RESULT=%errorlevel%

:: Cleanup: shutdown was called inside smoke_test.py; force-kill as safety net
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
