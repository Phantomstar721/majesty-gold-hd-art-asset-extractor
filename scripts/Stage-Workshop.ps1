param(
    [string]$ProjectPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$projectPath = if ([string]::IsNullOrWhiteSpace($ProjectPath)) {
    Join-Path $repoRoot "dist\workshop-upload"
} elseif ([IO.Path]::IsPathRooted($ProjectPath)) {
    [IO.Path]::GetFullPath($ProjectPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $ProjectPath))
}

$contentPath = Join-Path $projectPath "content"
$exePath = Join-Path $repoRoot "Majesty Art Extractor.exe"
$projectSource = Join-Path $repoRoot "workshop\MajestyArtExtractor.mswproj"
$previewSource = Join-Path $repoRoot "workshop\workshop-preview.jpg"
$instructionsSource = Join-Path $repoRoot "workshop\START HERE.txt"

foreach ($required in @($exePath, $projectSource, $previewSource, $instructionsSource)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required Workshop source file is missing: $required"
    }
}

New-Item -ItemType Directory -Path $contentPath -Force | Out-Null
Copy-Item -LiteralPath $projectSource -Destination (Join-Path $projectPath "MajestyArtExtractor.mswproj") -Force
Copy-Item -LiteralPath $previewSource -Destination (Join-Path $projectPath "workshop-preview.jpg") -Force
Copy-Item -LiteralPath $instructionsSource -Destination (Join-Path $contentPath "START HERE.txt") -Force
Copy-Item -LiteralPath $exePath -Destination (Join-Path $contentPath "Majesty Art Extractor.exe") -Force

$hash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToUpperInvariant()
[IO.File]::WriteAllText((Join-Path $projectPath "SHA256.txt"), "$hash  Majesty Art Extractor.exe`r`n", [Text.Encoding]::ASCII)

Write-Host "Workshop upload staged in repository: $projectPath"
Write-Host "SHA256: $hash"
