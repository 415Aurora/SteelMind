@echo off
setlocal
set "STEELMIND_ROOT=%~dp0"
set "STEELMIND_PYTHON=%STEELMIND_ROOT%.venv\Scripts\python.exe"

if not exist "%STEELMIND_PYTHON%" (
  echo SteelMind Python environment not found:
  echo   %STEELMIND_PYTHON%
  echo Install backend requirements first, or recreate the project .venv.
  pause
  exit /b 1
)

cd /d "%STEELMIND_ROOT%"
echo Starting SteelMind local tool gateway at http://127.0.0.1:8000
echo The agent page will open automatically after the gateway is ready.
"%STEELMIND_PYTHON%" "%STEELMIND_ROOT%start_tool_gateway.py"
pause
