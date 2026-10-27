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
echo After startup, open that URL with /health in a browser.
"%STEELMIND_PYTHON%" -m uvicorn app:app --app-dir "%STEELMIND_ROOT%backend" --host 127.0.0.1 --port 8000
pause
