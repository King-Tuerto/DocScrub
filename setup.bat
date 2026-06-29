@echo off
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo   DocScrub  ^|  First-time setup
echo  ============================================================
echo.

:: ------------------------------------------------------------------
:: 1. Check Python
:: ------------------------------------------------------------------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python is not installed or not found on PATH.
    echo.
    echo  Please install Python 3.11 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, tick "Add Python to PATH"
    echo             then re-run this setup.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Found Python %PY_VER%  OK

:: ------------------------------------------------------------------
:: 2. Install Python dependencies
:: ------------------------------------------------------------------
echo.
echo  Installing dependencies (this may take a minute)...
echo.
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: pip install failed.
    echo  Try running setup.bat as Administrator,
    echo  or check your internet connection.
    echo.
    pause
    exit /b 1
)
echo  Dependencies installed  OK

:: ------------------------------------------------------------------
:: 3. Generate app icon
:: ------------------------------------------------------------------
echo.
echo  Generating icon...
python make_icon.py
echo  Icon ready  OK

:: ------------------------------------------------------------------
:: 4. Create Desktop shortcut
:: ------------------------------------------------------------------
echo.
echo  Creating Desktop shortcut...
python create_shortcut.py
if %errorlevel% neq 0 (
    echo.
    echo  WARNING: Could not create Desktop shortcut.
    echo  You can still launch DocScrub by double-clicking start.bat
) else (
    echo  Desktop shortcut created  OK
)

:: ------------------------------------------------------------------
:: 5. Done
:: ------------------------------------------------------------------
echo.
echo  ============================================================
echo   Setup complete!
echo.
echo   Double-click the "DocScrub" icon on your Desktop to start.
echo  ============================================================
echo.
pause
endlocal
