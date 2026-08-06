<#
.SYNOPSIS
    Package the extractor as a single Windows executable.

.DESCRIPTION
    Maintainer tool. PyInstaller is needed to build, but nothing is needed to
    run what it produces: the executable carries its own Python, so a user
    downloads one file and double-clicks it.

    FFmpeg is deliberately not bundled. It is only needed for cinematics and
    quest maps, it is larger than everything else here put together, and the
    tool already offers to fetch it on request.

    The build environment is kept out of .venv so the runtime venv stays a
    faithful "nothing installed" test bed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\Build-Exe.ps1
#>
param(
    [string]$OutputDir = "",
    [string]$PyInstallerVersion = "6.21.0",
    [switch]$KeepBuildFiles
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BuildVenv = Join-Path $RepoRoot ".venv-build"
$Work = Join-Path $RepoRoot ".tmp\pyinstaller"
if (-not $OutputDir) { $OutputDir = Join-Path $RepoRoot "dist" }

Write-Host "Majesty Gold HD Art Extractor - executable build"
Write-Host "Repo:   $RepoRoot"
Write-Host "Output: $OutputDir"
Write-Host ""

function Invoke-Native {
    <#
        Native tools write progress and warnings to stderr, which a strict
        ErrorActionPreference turns into a terminating error. Exit codes are
        the only signal worth trusting here.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Quiet) {
            & $FilePath @Arguments *> $null
        } else {
            & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host "  $_" }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not (Test-Path (Join-Path $BuildVenv "Scripts\python.exe"))) {
    Write-Host "Creating build environment..."
    if ((Invoke-Native -FilePath "py" -Arguments @("-3", "-m", "venv", $BuildVenv) -Quiet) -ne 0) {
        throw "Could not create the build virtual environment."
    }
}
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

$installedPyInstaller = (& $BuildPython -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or $installedPyInstaller -ne $PyInstallerVersion) {
    Write-Host "Installing PyInstaller $PyInstallerVersion into the build environment..."
    $install = @(
        "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
        "pyinstaller==$PyInstallerVersion"
    )
    if ((Invoke-Native -FilePath $BuildPython -Arguments $install -Quiet) -ne 0) {
        throw "Could not install PyInstaller."
    }
}

$version = (& $BuildPython -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Select-Object -Last 1)
Write-Host "PyInstaller $version"
Write-Host ""

$entry = Join-Path $PSScriptRoot "majesty_art_extractor.py"
$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    # No console: this is double-clicked. The window keeps its own log, and the
    # entry point substitutes a sink for stdout so nothing raises without one.
    "--windowed",
    "--name", "Majesty Art Extractor",
    "--distpath", $OutputDir,
    "--workpath", $Work,
    "--specpath", $Work,
    "--paths", $PSScriptRoot
)
foreach ($module in @("extract_assets", "extractor_gui", "imaging", "ffmpeg_support", "app_paths")) {
    $arguments += @("--hidden-import", $module)
}
# Nothing here needs these, and they pull in a lot.
foreach ($module in @("numpy", "PIL", "pytest", "setuptools", "pip", "unittest", "email", "http", "xmlrpc")) {
    $arguments += @("--exclude-module", $module)
}
$arguments += $entry

$code = Invoke-Native -FilePath $BuildPython -Arguments $arguments
if ($code -ne 0) { throw "PyInstaller failed with exit code $code." }

$exe = Join-Path $OutputDir "Majesty Art Extractor.exe"
if (-not (Test-Path $exe)) { throw "Build reported success but produced no executable." }

if (-not $KeepBuildFiles) {
    Remove-Item (Join-Path $RepoRoot ".tmp") -Recurse -Force -ErrorAction SilentlyContinue
}

$size = (Get-Item $exe).Length
Write-Host ""
Write-Host ("Built {0}" -f $exe)
Write-Host ("  {0:N1} MB" -f ($size / 1MB))
Write-Host ""
Write-Host "Nothing needs installing to run it. Cinematics and quest maps still"
Write-Host "ask before fetching FFmpeg, exactly as they do from source."
