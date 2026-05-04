@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_MODE=auto"
if /I "%~1"=="--venv" (
  if "%~2"=="" goto :usage
  set "VENV_MODE=%~2"
)

if /I not "%VENV_MODE%"=="auto" if /I not "%VENV_MODE%"=="on" if /I not "%VENV_MODE%"=="off" goto :usage

set "PYTHON_CMD=python"
set "USING_VENV=0"

if /I "%VENV_MODE%"=="off" goto :install

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_CMD=%CD%\.venv\Scripts\python.exe"
  set "USING_VENV=1"
  goto :install
)

if /I "%VENV_MODE%"=="on" (
  echo Creating project virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    python -m venv .venv
  )
  if errorlevel 1 (
    echo.
    echo ERROR: failed to create .venv. Check that Python 3 is installed and the venv module is available.
    pause
    exit /b 1
  )
  set "PYTHON_CMD=%CD%\.venv\Scripts\python.exe"
  set "USING_VENV=1"
)

:install
if /I "%VENV_MODE%"=="off" (
  echo Using current Python interpreter without a virtual environment.
) else if "%USING_VENV%"=="1" (
  echo Using project virtual environment: "%PYTHON_CMD%"
) else (
  echo No project virtual environment found. Using current Python interpreter.
)

echo Installing / updating dependencies...
"%PYTHON_CMD%" -m pip install --upgrade pip
if errorlevel 1 (
  echo.
  echo ERROR: pip upgrade failed for the selected Python interpreter.
  pause
  exit /b 1
)

"%PYTHON_CMD%" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: pip install failed. Make sure Python is installed and on your PATH.
  pause
  exit /b 1
)

REM --- Register avt CLI on PATH (asks once) ---
set "AVT_SKIP=0"
if exist ".avt-path-declined" set "AVT_SKIP=1"
if exist ".venv\Scripts\avt.exe" set "AVT_SKIP=1"
if "!AVT_SKIP!"=="0" (
  echo.
  echo  Add "avt" command to PATH for global calling? [y/n]
  set /p "AVT_CHOICE=> "
  if /I "!AVT_CHOICE!"=="y" (
    echo Installing avt CLI entry point...
    "%PYTHON_CMD%" -m pip install -e . --quiet 2>nul
    if errorlevel 1 (
      echo WARNING: avt CLI installation failed. You can still use "python cli.py".
    ) else (
      echo Entry point installed.
      if "%USING_VENV%"=="1" (
        set "AVT_SCRIPTS=%CD%\.venv\Scripts"
        powershell -NoProfile -Command "if (-not ([Environment]::GetEnvironmentVariable('Path','User') -like '*!AVT_SCRIPTS!*')) { [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';!AVT_SCRIPTS!', 'User'); Write-Host 'Added to user PATH.' } else { Write-Host 'Already on user PATH.' }"
        echo You can now run "avt" from any terminal. Restart open terminals first.
      ) else (
        echo You can now run "avt" from any terminal.
      )
    )
  ) else (
    echo.>"%~dp0.avt-path-declined"
    echo Skipped. Run "pip install -e ." later if you change your mind.
  )
  echo.
)

set PORT=8001
"%PYTHON_CMD%" start.py --prod
exit /b %errorlevel%

:usage
echo Usage:
echo   start_windows.bat
echo   start_windows.bat --venv auto
echo   start_windows.bat --venv on
echo   start_windows.bat --venv off
echo.
echo Venv modes:
echo   auto - use .venv if it already exists, otherwise use the current Python interpreter
echo   on   - create/use .venv and install dependencies there
echo   off  - use the current Python interpreter without .venv
pause
exit /b 1
