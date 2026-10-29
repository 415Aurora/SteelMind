@echo off
setlocal
set "STEELMIND_ROOT=%~dp0"
if not defined STEELMIND_CONDA_ENV set "STEELMIND_CONDA_ENV=steelmind"
set "STEELMIND_CONDA_CMD="
cd /d "%STEELMIND_ROOT%"

call :find_conda
if not defined STEELMIND_CONDA_CMD (
  echo Could not locate conda.exe. Install Anaconda/Miniconda, or set CONDA_EXE to its full path.
  echo Common locations searched: %USERPROFILE%\anaconda3, %LOCALAPPDATA%\anaconda3, and Miniconda/Miniforge folders.
  pause
  exit /b 1
)
echo Using Conda: "%STEELMIND_CONDA_CMD%"

"%STEELMIND_CONDA_CMD%" run -n "%STEELMIND_CONDA_ENV%" python --version >nul 2>nul
if errorlevel 1 (
  echo Creating Conda environment "%STEELMIND_CONDA_ENV%" from environment.yml...
  "%STEELMIND_CONDA_CMD%" env create --yes -f "%STEELMIND_ROOT%environment.yml" -n "%STEELMIND_CONDA_ENV%"
  if errorlevel 1 (
    echo Environment creation did not complete. Trying to repair/update the named environment...
    "%STEELMIND_CONDA_CMD%" env update --yes -f "%STEELMIND_ROOT%environment.yml" -n "%STEELMIND_CONDA_ENV%" --prune
    if errorlevel 1 goto failed
  )
)

echo Installing/updating SteelMind backend dependencies...
"%STEELMIND_CONDA_CMD%" run -n "%STEELMIND_CONDA_ENV%" python -m pip install --disable-pip-version-check -r "%STEELMIND_ROOT%backend\requirements.txt"
if errorlevel 1 goto failed

echo Starting SteelMind gateway at http://127.0.0.1:8000
echo The agent page will open automatically after the gateway is ready.
"%STEELMIND_CONDA_CMD%" run --no-capture-output -n "%STEELMIND_CONDA_ENV%" python "%STEELMIND_ROOT%start_tool_gateway.py"
if errorlevel 1 goto failed
exit /b 0

:find_conda
if defined CONDA_EXE if exist "%CONDA_EXE%" set "STEELMIND_CONDA_CMD=%CONDA_EXE%"
if defined STEELMIND_CONDA_CMD exit /b 0

for /f "delims=" %%C in ('where conda.exe 2^>nul') do if not defined STEELMIND_CONDA_CMD set "STEELMIND_CONDA_CMD=%%C"
if defined STEELMIND_CONDA_CMD exit /b 0

for %%P in (
  "%USERPROFILE%\anaconda3\Scripts\conda.exe"
  "%USERPROFILE%\Anaconda3\Scripts\conda.exe"
  "%USERPROFILE%\miniconda3\Scripts\conda.exe"
  "%USERPROFILE%\Miniconda3\Scripts\conda.exe"
  "%USERPROFILE%\miniforge3\Scripts\conda.exe"
  "C:\Anaconda3\Scripts\conda.exe"
  "C:\Miniconda3\Scripts\conda.exe"
  "C:\Miniforge3\Scripts\conda.exe"
  "%LOCALAPPDATA%\anaconda3\Scripts\conda.exe"
  "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
  "%LOCALAPPDATA%\miniforge3\Scripts\conda.exe"
  "%ProgramData%\anaconda3\Scripts\conda.exe"
  "%ProgramData%\miniconda3\Scripts\conda.exe"
  "%ProgramData%\miniforge3\Scripts\conda.exe"
) do if not defined STEELMIND_CONDA_CMD if exist "%%~P" set "STEELMIND_CONDA_CMD=%%~P"
exit /b 0

:failed
echo SteelMind setup or startup failed. Check the error above.
echo If package downloads failed, check your network/proxy and retry this file.
pause
exit /b 1
