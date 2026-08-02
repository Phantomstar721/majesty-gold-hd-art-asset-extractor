<#
.SYNOPSIS
    Shown by run_extractor.cmd when Python is missing. Offers to install it.

.DESCRIPTION
    The extractor is written in Python, so it cannot present this itself: with
    no Python there is nothing to run the window. PowerShell and WinForms ship
    with Windows, so this stands in until Python is there, and never appears
    again once it is.

    Installation goes through winget when available, which is present on
    Windows 10 1809 and later. Otherwise the official download page is opened
    and the user installs by hand.
#>
param(
    [string]$LauncherPath = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$PythonDownloadUrl = "https://www.python.org/downloads/windows/"
$WingetPackageId = "Python.Python.3.12"
# Kept separate: the package id contains its own dots, so splitting it for a
# version to show produced "Python 12".
$PythonDisplayVersion = "3.12"

# Matches the extractor window so this does not feel like a different program.
$ColorWindow = [System.Drawing.ColorTranslator]::FromHtml("#12100c")
$ColorSurface = [System.Drawing.ColorTranslator]::FromHtml("#1e1a14")
$ColorText = [System.Drawing.ColorTranslator]::FromHtml("#ece3d0")
$ColorMuted = [System.Drawing.ColorTranslator]::FromHtml("#a89880")
$ColorGold = [System.Drawing.ColorTranslator]::FromHtml("#d8a058")
$ColorGoldText = [System.Drawing.ColorTranslator]::FromHtml("#1a1206")
$ColorSuccess = [System.Drawing.ColorTranslator]::FromHtml("#8fbf7a")
$ColorError = [System.Drawing.ColorTranslator]::FromHtml("#d97a62")

function Test-PythonPresent {
    # Re-read PATH from the registry so a Python installed a moment ago is
    # seen without the user having to sign out or reboot.
    $machine = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $user = [Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = @($machine, $user | Where-Object { $_ }) -join ";"
    return [bool](Get-Command py -ErrorAction SilentlyContinue) -or
           [bool](Get-Command python -ErrorAction SilentlyContinue)
}

if (Test-PythonPresent) { exit 0 }

$form = New-Object System.Windows.Forms.Form
$form.Text = "Majesty Gold HD Art Extractor"
$form.ClientSize = New-Object System.Drawing.Size(560, 320)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.BackColor = $ColorWindow

$title = New-Object System.Windows.Forms.Label
$title.Text = "Python is required"
$title.ForeColor = $ColorText
$title.Font = New-Object System.Drawing.Font("Georgia", 19)
$title.Location = New-Object System.Drawing.Point(26, 22)
$title.Size = New-Object System.Drawing.Size(500, 34)
$form.Controls.Add($title)

$body = New-Object System.Windows.Forms.Label
$body.Text = @"
This extractor is a Python program, and Python is not installed on this
computer. It needs nothing else: no other downloads, no setup steps.

Install Python, then this message will stop appearing.
"@
$body.ForeColor = $ColorMuted
$body.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$body.Location = New-Object System.Drawing.Point(28, 64)
$body.Size = New-Object System.Drawing.Size(504, 92)
$form.Controls.Add($body)

$statusPanel = New-Object System.Windows.Forms.Panel
$statusPanel.BackColor = $ColorSurface
$statusPanel.Location = New-Object System.Drawing.Point(26, 162)
$statusPanel.Size = New-Object System.Drawing.Size(508, 60)
$form.Controls.Add($statusPanel)

$status = New-Object System.Windows.Forms.Label
$status.ForeColor = $ColorMuted
$status.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$status.Location = New-Object System.Drawing.Point(14, 10)
$status.Size = New-Object System.Drawing.Size(480, 42)
$hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
if ($hasWinget) {
    $status.Text = "Ready to install Python $PythonDisplayVersion using Windows Package Manager."
} else {
    $status.Text = "Windows Package Manager is not available here, so the official download page will open instead."
}
$statusPanel.Controls.Add($status)

$install = New-Object System.Windows.Forms.Button
$install.Text = if ($hasWinget) { "Install Python" } else { "Open download page" }
$install.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$install.BackColor = $ColorGold
$install.ForeColor = $ColorGoldText
$install.FlatStyle = "Flat"
$install.FlatAppearance.BorderSize = 0
$install.Size = New-Object System.Drawing.Size(170, 40)
$install.Location = New-Object System.Drawing.Point(364, 250)
$form.Controls.Add($install)

$recheck = New-Object System.Windows.Forms.Button
$recheck.Text = "I've installed it"
$recheck.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$recheck.BackColor = $ColorSurface
$recheck.ForeColor = $ColorText
$recheck.FlatStyle = "Flat"
$recheck.FlatAppearance.BorderSize = 0
$recheck.Size = New-Object System.Drawing.Size(140, 40)
$recheck.Location = New-Object System.Drawing.Point(212, 250)
$form.Controls.Add($recheck)

$close = New-Object System.Windows.Forms.Button
$close.Text = "Close"
$close.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$close.BackColor = $ColorSurface
$close.ForeColor = $ColorMuted
$close.FlatStyle = "Flat"
$close.FlatAppearance.BorderSize = 0
$close.Size = New-Object System.Drawing.Size(90, 40)
$close.Location = New-Object System.Drawing.Point(26, 250)
$form.Controls.Add($close)

function Set-Status {
    param([string]$Message, [System.Drawing.Color]$Color = $ColorMuted)
    $status.Text = $Message
    $status.ForeColor = $Color
    $form.Refresh()
}

function Complete-IfPresent {
    if (Test-PythonPresent) {
        Set-Status "Python is installed. Starting the extractor..." $ColorSuccess
        Start-Sleep -Milliseconds 700
        $form.Tag = "installed"
        $form.Close()
        return $true
    }
    return $false
}

$install.Add_Click({
    if (-not $hasWinget) {
        Start-Process $PythonDownloadUrl
        Set-Status "The download page has been opened. Install Python, then choose ""I've installed it""."
        return
    }
    $install.Enabled = $false
    $recheck.Enabled = $false
    Set-Status "Installing Python. This can take a few minutes; the window may look idle."
    try {
        $arguments = @(
            "install", "--id", $WingetPackageId, "-e",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity"
        )
        $process = Start-Process -FilePath "winget" -ArgumentList $arguments -Wait -PassThru -NoNewWindow
        if ($process.ExitCode -ne 0) {
            throw "Windows Package Manager exited with code $($process.ExitCode)."
        }
        if (-not (Complete-IfPresent)) {
            Set-Status "Python was installed but is not on PATH yet. Close this and run the tool again." $ColorError
        }
    } catch {
        Set-Status "That did not work: $($_.Exception.Message)  Use the download page instead." $ColorError
        Start-Process $PythonDownloadUrl
    } finally {
        $install.Enabled = $true
        $recheck.Enabled = $true
    }
})

$recheck.Add_Click({
    if (-not (Complete-IfPresent)) {
        Set-Status "Still cannot find Python. If you have just installed it, close this and run the tool again." $ColorError
    }
})

$close.Add_Click({ $form.Close() })

[void]$form.ShowDialog()

if ($form.Tag -eq "installed") {
    if ($LauncherPath -and (Test-Path -LiteralPath $LauncherPath)) {
        Start-Process -FilePath $LauncherPath
    }
    exit 0
}
exit 1
