@echo off
cd /d "%~dp0"
echo.
echo   DocScrub -- Starting...
echo.

python -c "from backend.main import create_app; create_app()"
if errorlevel 1 (
    echo.
    echo   ERROR: Startup failed. Make sure Python is installed and
    echo   you have run setup.bat at least once.
    echo.
    pause
    exit /b 1
)

:: Open the browser after a 3-second delay in a minimised background window
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"

echo   Server running at http://127.0.0.1:8000
echo   Close this window to stop DocScrub.
echo.
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000

echo.
echo   DocScrub has stopped.
pause
