@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Start the password manager as a desktop app (no console window when possible).
set "PY="

pythonw.exe --version >nul 2>nul && set "PY=pythonw.exe"
if not defined PY python.exe --version >nul 2>nul && set "PY=python.exe"

if not defined PY (
  py.exe -3 --version >nul 2>nul
  if not errorlevel 1 (
    start "" py.exe -3 app.py %*
    exit /b 0
  )
)

if not defined PY if exist "D:\Python\Python 3.14\pythonw.exe" set "PY="D:\Python\Python 3.14\pythonw.exe""
if not defined PY if exist "D:\Python\Python 3.14\python.exe" set "PY="D:\Python\Python 3.14\python.exe""

if not defined PY (
  echo.
  echo [!] Python was not found on this computer.
  echo     Please install Python 3.10+ and make sure "Add Python to PATH" is checked.
  echo     Download: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

start "" %PY% app.py %*
exit /b 0
