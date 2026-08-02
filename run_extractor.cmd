@echo off
setlocal
cd /d "%~dp0"

rem No virtual environment, no pip, no network. The extractor runs on a stock
rem Python install using nothing but the standard library. Cinematics are the
rem one exception, and are opt-in from inside the tool.

where py >nul 2>nul
if errorlevel 1 goto no_python

if "%~1"=="" (
  py -3 scripts\extractor_gui.py
) else (
  py -3 scripts\extract_assets.py %*
)
goto done

:no_python
echo.
echo Python 3 was not found.
echo.
echo This tool needs Python 3.9 or newer. Install it from:
echo   https://www.python.org/downloads/windows/
echo.
echo During setup, tick "Add python.exe to PATH".
echo Nothing else needs installing.
echo.
pause
exit /b 1

:done
endlocal
