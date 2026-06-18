@echo off
REM ============================================================
REM  KStudio launcher -- runs the app from the project .venv and
REM  closes this cmd window once KStudio has been launched.
REM  ASCII-ONLY BODY: no Korean / no emoji / no smart quotes
REM  anywhere, not even in REM comments. Non-ASCII bytes desync
REM  the cmd.exe parser under chcp 65001. All Korean text is
REM  printed by the Python program, not by this launcher.
REM ============================================================
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo  [error] .venv not found in this folder.
  echo  Create it first:
  echo      python -m venv .venv
  echo      .venv\Scripts\python.exe -m pip install -e .
  echo.
  pause
  exit /b 1
)

REM Launch detached with pythonw (no console). This cmd window
REM exits right after, so it disappears once KStudio is up.
start "" ".venv\Scripts\pythonw.exe" -m screen_recorder
exit /b 0
