@echo off
echo Starting DocScrub...
cd /d "%~dp0"
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --log-level warning --no-access-log
pause