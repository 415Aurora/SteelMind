@echo off
setlocal
set "STEELMIND_ROOT=%~dp0"
set "STEELMIND_PYTHON=%STEELMIND_ROOT%.venv\Scripts\python.exe"

if not exist "%STEELMIND_PYTHON%" (
  echo Project .venv was not found. Switching to the Anaconda environment setup...
  call "%STEELMIND_ROOT%start_tool_gateway_conda.bat"
  exit /b %errorlevel%
)

cd /d "%STEELMIND_ROOT%"
echo Checking/updating backend dependencies in the project .venv...
"%STEELMIND_PYTHON%" -m pip install --disable-pip-version-check -r "%STEELMIND_ROOT%backend\requirements.txt"
if errorlevel 1 (
  echo Dependency installation failed. Check the network and pip error above.
  pause
  exit /b 1
)

echo Starting SteelMind local tool gateway at http://127.0.0.1:8000
echo The agent page will open automatically after the gateway is ready.
"%STEELMIND_PYTHON%" "%STEELMIND_ROOT%start_tool_gateway.py"
set "STEELMIND_EXIT_CODE=%ERRORLEVEL%"
if not "%STEELMIND_EXIT_CODE%"=="0" pause
exit /b %STEELMIND_EXIT_CODE%
