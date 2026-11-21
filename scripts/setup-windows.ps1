<#
.SYNOPSIS
  Creates the Windows-native Python environment used for MIDI I/O.

.DESCRIPTION
  The INTEGRA-7's USB MIDI driver lives on Windows, so mido + python-rtmidi must
  be installed in a *Windows* Python (never the WSL one). This script creates a
  virtual environment under %LOCALAPPDATA%\integra7-conductor\venv, installs the
  two packages, and lists the MIDI ports Windows can see.

  From Windows PowerShell:
      powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
  From WSL:
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/setup-windows.ps1)"

.PARAMETER Python
  Path to a Windows python.exe (3.9+). Defaults to the `py` launcher, then `python`.

.PARAMETER VenvPath
  Where to create the virtual environment.
#>
param(
    [string]$Python = "",
    [string]$VenvPath = (Join-Path $env:LOCALAPPDATA "integra7-conductor\venv")
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

# python-rtmidi publishes prebuilt Windows wheels only for specific CPython
# versions (1.5.8: 3.8 - 3.12). Prefer an interpreter that has one, and never
# fall back to compiling from source (that needs MSVC and fails confusingly).
$launcherArgs = @()
if ($Python -eq "") {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = "py"
        $launcherArgs = @("-3")
        foreach ($v in @("3.12", "3.11", "3.10")) {
            $found = $false
            try { & py "-$v" -c "pass" *> $null; $found = ($LASTEXITCODE -eq 0) } catch { $found = $false }
            if ($found) { $launcherArgs = @("-$v"); break }
        }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = "python"
    } else {
        throw "No Windows Python found. Install one with: winget install --id Python.Python.3.12 -e"
    }
}

$version = (& $Python @launcherArgs -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
Write-Host "Using Windows Python $version ($Python $($launcherArgs -join ' '))"
Write-Host "Creating virtual environment at $VenvPath"
Invoke-Checked $Python ($launcherArgs + @("-m", "venv", "--clear", $VenvPath))

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
Invoke-Checked $venvPython @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
& $venvPython -m pip install --quiet --only-binary ":all:" "mido>=1.3" "python-rtmidi>=1.5"
if ($LASTEXITCODE -ne 0) {
    throw @"
Could not install mido + python-rtmidi for Windows Python $version.
python-rtmidi has no prebuilt wheel for this Python version. Install a supported
one (3.10 - 3.12) next to your current Python and re-run this script:

    winget install --id Python.Python.3.12 -e

or pass an interpreter explicitly:  -Python C:\Path\To\Python312\python.exe
"@
}

$adapter = Join-Path $PSScriptRoot "..\src\integra7_conductor\midi\windows_adapter.py"
Write-Host ""
Write-Host "MIDI ports visible to Windows:"
Invoke-Checked $venvPython @("-X", "utf8", $adapter, "--ports")

Write-Host ""
Write-Host "Windows Python for the adapter:"
Write-Host "  $venvPython"
Write-Host "In WSL, run:  integra7 doctor --write-config"
