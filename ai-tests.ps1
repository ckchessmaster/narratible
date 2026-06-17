param(
    [ValidateSet('fast', 'ai-mock', 'ai-replay', 'ai-live', 'all')]
    [string[]]$Suite = @(),
    [string[]]$Case = @(),
    [switch]$List,
    [switch]$Live,
    [ValidateSet('', 'kokoro', 'f5-tts')]
    [string]$LocalTts = '',
    [string]$F5Sample = '',
    [string]$F5Reference = '',
    [string]$CondaEnv = 'py312',
    [switch]$SyncDependencies
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'
$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'
$requirementsPath = Join-Path $backendDir 'requirements.txt'
$runnerPath = Join-Path $backendDir 'tools\ai_test_runner.py'

function New-BackendVenv {
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if (-not $conda) {
        throw "backend\.venv is missing and conda was not found. Create backend\.venv first, then rerun this script."
    }

    $candidates = @()
    foreach ($candidate in @($CondaEnv, '312', 'py312')) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and $candidates -notcontains $candidate) {
            $candidates += $candidate
        }
    }

    foreach ($candidate in $candidates) {
        Write-Host "Trying conda environment '$candidate' for backend\.venv..."
        & conda run -n $candidate python --version *> $null
        if ($LASTEXITCODE -ne 0) {
            continue
        }

        & conda run -n $candidate python -m venv $venvPython.Replace('\Scripts\python.exe', '')
        if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) {
            Write-Host "Created backend\.venv from conda environment '$candidate'."
            return
        }
    }

    throw "Could not create backend\.venv from conda environments: $($candidates -join ', ')."
}

if (-not (Test-Path $runnerPath)) {
    throw "AI test runner was not found at $runnerPath."
}

$createdVenv = $false
if (-not (Test-Path $venvPython)) {
    New-BackendVenv
    $createdVenv = $true
}

if ($createdVenv -or $SyncDependencies) {
    Write-Host "Installing backend requirements..."
    & $venvPython -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($Live) {
    $env:NARRATIBLE_AI_TEST_LIVE = '1'
}
if (-not [string]::IsNullOrWhiteSpace($LocalTts)) {
    $env:NARRATIBLE_AI_TEST_LOCAL_TTS = $LocalTts
}
if (-not [string]::IsNullOrWhiteSpace($F5Sample)) {
    $env:NARRATIBLE_AI_TEST_F5_SAMPLE = $F5Sample
}
if (-not [string]::IsNullOrWhiteSpace($F5Reference)) {
    $env:NARRATIBLE_AI_TEST_F5_REFERENCE = $F5Reference
}

$runnerArgs = @()
if ($List) {
    $runnerArgs += '--list'
}
foreach ($item in $Suite) {
    $runnerArgs += '--suite'
    $runnerArgs += $item
}
foreach ($item in $Case) {
    $runnerArgs += '--case'
    $runnerArgs += $item
}

Push-Location $backendDir
try {
    & $venvPython $runnerPath @runnerArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
