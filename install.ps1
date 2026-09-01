[CmdletBinding()]
param(
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"

function Assert-Succeeded([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed. See the error above."
    }
}

function Get-PythonVersion([string]$PythonPath) {
    $version = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Assert-Succeeded "Reading the Python version"
    return $version.Trim()
}

if (Test-Path -LiteralPath $venvPython) {
    $existingVersion = Get-PythonVersion $venvPython
    if ($existingVersion -ne "3.11" -and -not $Recreate) {
        throw "This project's .venv uses Python $existingVersion. Run '.\install.ps1 -Recreate' to replace it with Python 3.11."
    }
}
elseif ((Test-Path -LiteralPath $venvPath) -and -not $Recreate) {
    throw "This project's .venv is incomplete. Run '.\install.ps1 -Recreate' to replace it."
}

$createEnvironment = $Recreate -or -not (Test-Path -LiteralPath $venvPython)
if ($createEnvironment) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw "Python 3.11 was not found. Install 64-bit Python 3.11, then run this installer again."
    }

    & $pythonLauncher.Source -3.11 -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "64-bit Python 3.11 was not found. Install it, then run this installer again."
    }

    $venvArguments = @("-3.11", "-m", "venv")
    if ($Recreate) {
        $venvArguments += "--clear"
    }
    $venvArguments += $venvPath
    & $pythonLauncher.Source @venvArguments
    Assert-Succeeded "Creating the Python 3.11 environment"
}

if ((Get-PythonVersion $venvPython) -ne "3.11") {
    throw "The project environment was not created with Python 3.11."
}

& $venvPython -m pip install --upgrade pip
Assert-Succeeded "Updating pip"
& $venvPython -m pip install -r $requirementsPath
Assert-Succeeded "Installing requirements.txt"

& $venvPython -c "import psychopy, serial; from psychopy import core, visual; from psychopy.hardware import keyboard; assert psychopy.__version__ == '2026.2.3'; print(f'PsychoPy {psychopy.__version__} is ready.')"
Assert-Succeeded "Checking PsychoPy"

Write-Host "Setup complete. In PyCharm, run main.py with .venv\Scripts\python.exe."
