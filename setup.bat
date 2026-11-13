@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem Prefer: bundled python -> py launcher -> real python on PATH (skip Store stub)
set "PY="
if exist "python\python.exe" (
    set "PY=python\python.exe"
    goto :run
)
where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    goto :run
)
for /f "delims=" %%P in ('where python 2^>nul ^| findstr /V /I "WindowsApps"') do (
    set "PY=%%P"
    goto :run
)
goto :nopython

:nopython
echo.
echo Python not found.
echo.
echo Option 1: extract Python "Windows embeddable package (64-bit)" into .\python\
echo           https://www.python.org/downloads/windows/
echo Option 2: install Python 3.11+ and enable "Add python.exe to PATH"
echo.
pause
exit /b 1

:run
"%PY%" run.py wizard
echo.
pause
