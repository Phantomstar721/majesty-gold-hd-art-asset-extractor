@echo off
setlocal
cd /d "%~dp0"

rem No virtual environment, no pip, no network. The extractor runs on a stock
rem Python install using nothing but the standard library. Cinematics are the
rem one exception, and are opt-in from inside the tool.
rem
rem Python itself is the only prerequisite. If it is missing, a small window
rem offers to install it; the extractor cannot show that itself, having no
rem Python to run on.

where py >nul 2>nul
if not errorlevel 1 goto run

where python >nul 2>nul
if not errorlevel 1 goto run_python

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\Request-Python.ps1" -LauncherPath "%~f0"
exit /b %errorlevel%

:run
if "%~1"=="" (
  py -3 scripts\extractor_gui.py
) else (
  py -3 scripts\extract_assets.py %*
)
goto done

:run_python
if "%~1"=="" (
  python scripts\extractor_gui.py
) else (
  python scripts\extract_assets.py %*
)
goto done

:done
endlocal
