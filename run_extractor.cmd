@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Failed to create Python virtual environment.
    echo Make sure Python 3 is installed and available through the py launcher.
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import PIL, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 exit /b 1
)

if "%~1"=="" (
  ".venv\Scripts\python.exe" scripts\extractor_gui.py
) else (
  ".venv\Scripts\python.exe" scripts\extract_assets.py %*
)
endlocal
