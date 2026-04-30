@echo off
REM KStudio 인스톨러 빌드 — PyInstaller dist 가 이미 있다고 가정.
REM 1) python -m PyInstaller KStudio.spec --noconfirm
REM 2) 본 스크립트 실행 → dist/installer/KStudio-Setup-<ver>.exe 생성

setlocal

REM Inno Setup 6 ISCC 경로 자동 탐색 (시스템 / 사용자 단위 설치 모두).
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe

if "%ISCC%"=="" (
  echo [ERROR] Inno Setup 6 가 설치되어 있지 않습니다.
  echo         https://jrsoftware.org/isdl.php 에서 받거나 winget install JRSoftware.InnoSetup
  exit /b 1
)

REM dist\KStudio 가 있어야 함 — 없으면 PyInstaller 부터.
if not exist "%~dp0..\dist\KStudio\KStudio.exe" (
  echo [ERROR] dist\KStudio\KStudio.exe 가 없습니다. 먼저 PyInstaller 를 실행하세요:
  echo         python -m PyInstaller KStudio.spec --noconfirm
  exit /b 1
)

"%ISCC%" "%~dp0KStudio.iss"
if errorlevel 1 (
  echo [ERROR] 인스톨러 빌드 실패.
  exit /b 1
)

echo.
echo [OK] 인스톨러 생성 완료: dist\installer\
dir /b "%~dp0..\dist\installer\*.exe"
