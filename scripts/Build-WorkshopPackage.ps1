<#
.SYNOPSIS
    Build the minimal Steam Workshop upload package for RGSeditor.

.DESCRIPTION
    Produces two deliberately separate directories under dist\workshop-upload:

      content\   Files Steam Workshop subscribers receive.
      project    The RGSeditor project, preview and checksum used by the author.

    The content directory contains only the standalone executable and a short
    start-here note. Source, build environments, project metadata and the
    preview image are not included in the subscriber download.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\Build-WorkshopPackage.ps1 `
        -PreviewImagePath .\local\image.jpg
#>
param(
    [string]$PreviewImagePath = "",
    [UInt64]$WorkshopId = 0,
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist"
$PackageRoot = Join-Path $DistRoot "workshop-upload"
$ContentRoot = Join-Path $PackageRoot "content"
$ExeSource = Join-Path $DistRoot "Majesty Art Extractor.exe"

if (-not $PreviewImagePath) {
    $PreviewImagePath = Join-Path $RepoRoot "local\image.jpg"
}

if (-not $SkipExeBuild) {
    & (Join-Path $PSScriptRoot "Build-Exe.ps1")
}

if (-not (Test-Path -LiteralPath $ExeSource -PathType Leaf)) {
    throw "Missing executable. Run scripts\Build-Exe.ps1 first: $ExeSource"
}

$PreviewSource = (Resolve-Path -LiteralPath $PreviewImagePath -ErrorAction Stop).Path
$PreviewExtension = [IO.Path]::GetExtension($PreviewSource).ToLowerInvariant()
if ($PreviewExtension -notin @(".jpg", ".jpeg", ".png")) {
    throw "RGSeditor preview must be a JPG or PNG: $PreviewSource"
}

# This is generated output, but validate its exact location before clearing it.
$ResolvedDist = [IO.Path]::GetFullPath($DistRoot).TrimEnd("\")
$ResolvedPackage = [IO.Path]::GetFullPath($PackageRoot).TrimEnd("\")
if (
    [IO.Path]::GetFileName($ResolvedPackage) -ne "workshop-upload" -or
    [IO.Path]::GetDirectoryName($ResolvedPackage) -ne $ResolvedDist
) {
    throw "Refusing to clear an unexpected package path: $ResolvedPackage"
}
if (Test-Path -LiteralPath $ResolvedPackage) {
    Remove-Item -LiteralPath $ResolvedPackage -Recurse -Force
}

New-Item -ItemType Directory -Path $ContentRoot -Force | Out-Null

$ContentExe = Join-Path $ContentRoot "Majesty Art Extractor.exe"
Copy-Item -LiteralPath $ExeSource -Destination $ContentExe

$StartHere = @"
MAJESTY GOLD HD ART EXTRACTOR

Double-click "Majesty Art Extractor.exe" to begin.

Nothing needs installing: Python and everything required for normal art
extraction are contained in the EXE. The tool reads your own Majesty Gold HD
installation and writes PNG files to the folder you choose. It does not modify
the game.

Cinematics and animated quest maps are optional. They require FFmpeg; if it is
not already installed, the extractor explains the download and asks permission
before fetching anything. All other art extracts without FFmpeg.

Source and current releases:
https://github.com/Phantomstar721/majesty-gold-hd-art-asset-extractor
"@
Set-Content -LiteralPath (Join-Path $ContentRoot "START HERE.txt") -Value $StartHere -Encoding UTF8

$PreviewName = "workshop-preview$PreviewExtension"
$PreviewDestination = Join-Path $PackageRoot $PreviewName
Copy-Item -LiteralPath $PreviewSource -Destination $PreviewDestination

$ExeHash = (Get-FileHash -LiteralPath $ContentExe -Algorithm SHA256).Hash
Set-Content -LiteralPath (Join-Path $PackageRoot "SHA256.txt") -Encoding ASCII -Value (
    "$ExeHash  Majesty Art Extractor.exe"
)

function ConvertTo-XmlText([string]$Value) {
    return [System.Security.SecurityElement]::Escape($Value)
}

$ProjectPath = Join-Path $PackageRoot "Majesty Art Extractor.mswproj"
$ProjectXml = @"
<Majesty>
	<SteamWorkshop id="$WorkshopId" visibility="Private">
		<Title lang="en_US">Majesty Gold HD Art Extractor</Title>
		<Description lang="en_US">Standalone utility that extracts organised PNG art from your own installed copy of Majesty Gold HD. Open the subscribed item folder and run Majesty Art Extractor.exe. Includes no game assets and does not modify the game.</Description>
		<ContentPath>$(ConvertTo-XmlText $ContentRoot)</ContentPath>
		<PreviewImagePath>$(ConvertTo-XmlText $PreviewDestination)</PreviewImagePath>
		<IDTag>Mod</IDTag>
	</SteamWorkshop>
</Majesty>
"@
Set-Content -LiteralPath $ProjectPath -Value $ProjectXml -Encoding UTF8

$ContentFiles = @(
    Get-ChildItem -LiteralPath $ContentRoot -Recurse -File |
        ForEach-Object { $_.Name } |
        Sort-Object
)
$ContentDirectories = @(Get-ChildItem -LiteralPath $ContentRoot -Recurse -Directory)
if ($ContentDirectories.Count -ne 0) {
    throw "Workshop content must remain flat and minimal."
}
$ExpectedContent = @("Majesty Art Extractor.exe", "START HERE.txt") | Sort-Object
if (($ContentFiles -join "`n") -ne ($ExpectedContent -join "`n")) {
    throw "Unexpected Workshop content: $($ContentFiles -join ', ')"
}

$SourceHash = (Get-FileHash -LiteralPath $ExeSource -Algorithm SHA256).Hash
if ($SourceHash -ne $ExeHash) {
    throw "Packaged executable does not match the validated dist build."
}

Write-Host ""
Write-Host "RGSeditor upload package is ready:"
Write-Host "  Project: $ProjectPath"
Write-Host "  Content: $ContentRoot"
Write-Host ""
Write-Host "Subscribers receive only:"
foreach ($File in $ContentFiles) {
    Write-Host "  $File"
}
Write-Host ""
Write-Host "Executable SHA-256: $ExeHash"
