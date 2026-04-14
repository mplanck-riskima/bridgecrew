@echo off
cd /d "%~dp0"
call .venv\Scripts\activate

:loop
python server.py
if %ERRORLEVEL% == 42 (
    echo feature-mcp restart requested. Restarting...
    goto loop
)
echo feature-mcp exited with code %ERRORLEVEL%.
