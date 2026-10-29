@echo off
setlocal
set "STEELMIND_ROOT=%~dp0"
if not defined STEELMIND_CONDA_ENV set "STEELMIND_CONDA_ENV=steelmind"
cd /d "%STEELMIND_ROOT%"

where conda >nul 2>nul
if errorlevel 1 (
  echo Conda was not found. Open Anaconda Prompt, then run this file again.
  pause
  exit /b 1
)

conda run -n "%STEELMIND_CONDA_ENV%" python --version >nul 2>nul
if errorlevel 1 (
  echo Creating Conda environment "%STEELMIND_CONDA_ENV%" from environment.yml...
  conda env create -f "%STEELMIND_ROOT%environment.yml" -n "%STEELMIND_CONDA_ENV%"
  if errorlevel 1 goto failed
)

echo Installing/updating SteelMind backend dependencies...
conda run -n "%STEELMIND_CONDA_ENV%" python -m pip install --disable-pip-version-check -r "%STEELMIND_ROOT%backend\requirements.txt"
if errorlevel 1 goto failed

echo Starting SteelMind gateway at http://127.0.0.1:8000
echo The agent page will open automatically after the gateway is ready.
conda run --no-capture-output -n "%STEELMIND_CONDA_ENV%" python "%STEELMIND_ROOT%start_tool_gateway.py"
if errorlevel 1 goto failed
exit /b 0

:failed
echo SteelMind environment setup or startup failed. Check the error above.
pause
exit /b 1
