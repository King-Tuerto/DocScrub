@echo off
cd /d "%~dp0"

:: Find pythonw.exe (same folder as python.exe) for a windowless launch.
:: Falls back to python.exe if not found (shows a brief console that closes).
for /f "delims=" %%p in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYTHONW=%%p

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" "%~dp0launcher.py"
) else (
    start "" python "%~dp0launcher.py"
)
