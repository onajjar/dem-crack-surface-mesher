[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$constraintsPath = Join-Path $projectRoot "constraints-baseline.txt"
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$minimumVersion = [Version]"3.10"

foreach ($requiredPath in @($requirementsPath, $constraintsPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required setup file is missing: $requiredPath"
    }
}

$candidateSpecs = @()
if ($PythonExecutable) {
    $resolvedExplicit = Get-Command $PythonExecutable -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $resolvedExplicit) {
        throw "Python executable not found: $PythonExecutable"
    }
    $candidateSpecs += [PSCustomObject]@{
        Label = $PythonExecutable
        Command = $resolvedExplicit.Source
        Arguments = @()
    }
} elseif ($env:PYTHON_BIN) {
    $resolvedEnvironment = Get-Command $env:PYTHON_BIN -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $resolvedEnvironment) {
        throw "PYTHON_BIN does not identify an executable: $($env:PYTHON_BIN)"
    }
    $candidateSpecs += [PSCustomObject]@{
        Label = "PYTHON_BIN"
        Command = $resolvedEnvironment.Source
        Arguments = @()
    }
} else {
    foreach ($candidate in @(
        [PSCustomObject]@{ Name = "python"; Arguments = @() },
        [PSCustomObject]@{ Name = "py"; Arguments = @("-3") },
        [PSCustomObject]@{ Name = "python3"; Arguments = @() }
    )) {
        $resolved = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue
        if ($null -ne $resolved) {
            $candidateSpecs += [PSCustomObject]@{
                Label = $candidate.Name
                Command = $resolved.Source
                Arguments = $candidate.Arguments
            }
        }
    }
}

$selectedPython = $null
$rejections = @()
foreach ($candidate in $candidateSpecs) {
    try {
        $prefixArguments = @($candidate.Arguments)
        $versionText = & $candidate.Command @prefixArguments -c `
            "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -ne 0) {
            $rejections += "$($candidate.Label): could not run Python"
            continue
        }
        $version = [Version](($versionText | Select-Object -Last 1).Trim())
        if ($version -lt $minimumVersion) {
            $rejections += "$($candidate.Label): Python $version is older than $minimumVersion"
            continue
        }
        $selectedPython = [PSCustomObject]@{
            Label = $candidate.Label
            Command = $candidate.Command
            Arguments = $prefixArguments
            Version = $version
        }
        break
    } catch {
        $rejections += "$($candidate.Label): $($_.Exception.Message)"
    }
}

if ($null -eq $selectedPython) {
    $details = if ($rejections.Count) { "`n" + ($rejections -join "`n") } else { "" }
    throw @"
Python 3.10 or newer was not found.$details
Install Python, or create a Conda environment with:
  conda create -n dem-crack-mesher python=3.11
  conda activate dem-crack-mesher
Then run this script again.
"@
}

Write-Host "Project root: $projectRoot"
Write-Host "Selected Python: $($selectedPython.Command) ($($selectedPython.Version))"

if ($CheckOnly) {
    Write-Host "Setup check passed. No environment was created."
    return
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Creating virtual environment: $venvPath"
    & $selectedPython.Command @($selectedPython.Arguments) -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed to create the virtual environment."
    }
} else {
    Write-Host "Reusing virtual environment: $venvPath"
}

$venvVersionText = & $venvPython -c `
    "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw "The virtual-environment Python executable could not run: $venvPython"
}
$venvVersion = [Version](($venvVersionText | Select-Object -Last 1).Trim())
if ($venvVersion -lt $minimumVersion) {
    throw "The existing .venv uses Python $venvVersion; Python $minimumVersion or newer is required."
}

& $venvPython -m pip install --no-user --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}
& $venvPython -m pip install --no-user -r $requirementsPath -c $constraintsPath
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency installation failed."
}

Write-Host "Windows environment is ready."
Write-Host "Activate it with: .\.venv\Scripts\Activate.ps1"
Write-Host "Launch the Workbench with: python castem_pipeline_gui_scientific.py"
