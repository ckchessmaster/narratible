param(
    [ValidateSet('backend', 'frontend', 'full')]
    [string]$Scope = 'full',
    [string]$ReportPath = '',
    [string]$MutationTarget = '',
    [string]$MutationSummary = '',
    [switch]$MutationKilled
)

$ErrorActionPreference = 'Continue'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')
Set-Location $repoRoot

$backendVenvPython = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$backendPython = if (Test-Path $backendVenvPython) {
    '& "{0}"' -f $backendVenvPython
}
else {
    'python'
}

function Invoke-Step {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$Command
    )

    $fullDir = Join-Path $repoRoot $WorkingDirectory
    Push-Location $fullDir

    $start = Get-Date
    $output = ''
    $exitCode = 0

    try {
        $output = ((Invoke-Expression "$Command 2>&1") | Out-String)
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) {
            $exitCode = 0
        }
    }
    catch {
        $output = "$_"
        $exitCode = 1
    }

    Pop-Location

    return [PSCustomObject]@{
        Name = $Name
        WorkingDirectory = $WorkingDirectory
        Command = $Command
        ExitCode = [int]$exitCode
        Passed = ([int]$exitCode -eq 0)
        StartedAt = $start.ToString('s')
        Output = $output.Trim()
    }
}

function Get-ChangedTestFiles {
    $raw = (git status --porcelain) 2>$null
    if (-not $raw) {
        return @()
    }

    $files = @()
    foreach ($line in $raw) {
        if ($line.Length -lt 4) {
            continue
        }

        $path = $line.Substring(3).Trim()
        if ($path -match '^backend/tests/.+\.py$' -or
            $path -match '^frontend/src/.+\.test\.(js|jsx|ts|tsx)$' -or
            $path -match '^frontend/src/.+\.spec\.(js|jsx|ts|tsx)$') {
            $files += $path
        }
    }

    return $files | Sort-Object -Unique
}

$steps = @()

if ($Scope -eq 'backend' -or $Scope -eq 'full') {
    $steps += Invoke-Step -Name 'Backend syntax check' -WorkingDirectory 'backend' -Command "$backendPython -m compileall app run.py"

    if (Test-Path (Join-Path $repoRoot 'backend\tests')) {
        $steps += Invoke-Step -Name 'Backend unit tests' -WorkingDirectory 'backend' -Command "$backendPython -m pytest tests -q"
    }
}

if ($Scope -eq 'frontend' -or $Scope -eq 'full') {
    $steps += Invoke-Step -Name 'Frontend lint' -WorkingDirectory 'frontend' -Command 'npm run lint'
    $steps += Invoke-Step -Name 'Frontend build' -WorkingDirectory 'frontend' -Command 'npm run build'
}

$changedTestFiles = Get-ChangedTestFiles
$mutationRequired = ($changedTestFiles.Count -gt 0)
$mutationPass = $true
$mutationNotes = @()

if ($mutationRequired) {
    if ([string]::IsNullOrWhiteSpace($MutationTarget)) {
        $mutationPass = $false
        $mutationNotes += 'Mutation required: set -MutationTarget when tests are changed.'
    }

    if ([string]::IsNullOrWhiteSpace($MutationSummary)) {
        $mutationPass = $false
        $mutationNotes += 'Mutation required: set -MutationSummary when tests are changed.'
    }

    if (-not $MutationKilled) {
        $mutationPass = $false
        $mutationNotes += 'Mutation required: add -MutationKilled only after verifying the mutation triggered a failing test.'
    }
}
else {
    $mutationNotes += 'No changed unit test files detected in git status; mutation gate skipped.'
}

if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $reportDir = Join-Path $repoRoot 'reports\test-validation'
    if (-not (Test-Path $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir | Out-Null
    }

    $ReportPath = Join-Path $reportDir ("test-validation-{0}.md" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
}

$reportParent = Split-Path $ReportPath -Parent
if (-not (Test-Path $reportParent)) {
    New-Item -ItemType Directory -Path $reportParent | Out-Null
}

$hasStepFailure = ($steps | Where-Object { -not $_.Passed }).Count -gt 0
$overallPass = (-not $hasStepFailure) -and $mutationPass
$overallStatus = if ($overallPass) { 'PASS' } else { 'FAIL' }

$reportLines = @()
$reportLines += '# Test Validation Report'
$reportLines += ''
$reportLines += "- Timestamp: $(Get-Date -Format 's')"
$reportLines += "- Scope: $Scope"
$reportLines += "- Overall: $overallStatus"
$reportLines += ''
$reportLines += '## Command Matrix'
$reportLines += ''
$reportLines += '| Command | Status | Exit Code |'
$reportLines += '|---|---|---|'

foreach ($step in $steps) {
    $status = if ($step.Passed) { 'PASS' } else { 'FAIL' }
    $safeCommand = $step.Command.Replace('|', '\|')
    $safeDirectory = $step.WorkingDirectory.Replace('|', '\|')
    $reportLines += "| $($step.Name) ($safeCommand in $safeDirectory) | $status | $($step.ExitCode) |"
}

$reportLines += ''
$reportLines += '## Mutation Validation'
$reportLines += ''
$reportLines += "- Changed test files detected: $($changedTestFiles.Count)"

foreach ($file in $changedTestFiles) {
    $reportLines += "- $file"
}

if ($mutationRequired) {
    $reportLines += "- Mutation target: $MutationTarget"
    $reportLines += "- Mutation summary: $MutationSummary"
    $reportLines += "- Mutation killed (expected fail observed): $MutationKilled"
}

foreach ($note in $mutationNotes) {
    $reportLines += "- Note: $note"
}

$reportLines += ''
$reportLines += '## Step Output Snippets'
$reportLines += ''

foreach ($step in $steps) {
    $reportLines += "### $($step.Name)"
    $reportLines += '```text'
    if ([string]::IsNullOrWhiteSpace($step.Output)) {
        $reportLines += '(no output)'
    }
    else {
        $snippet = $step.Output
        if ($snippet.Length -gt 3500) {
            $snippet = $snippet.Substring(0, 3500) + "`n...[truncated]"
        }
        $reportLines += $snippet
    }
    $reportLines += '```'
    $reportLines += ''
}

Set-Content -Path $ReportPath -Value $reportLines -Encoding utf8

Write-Host "Report written: $ReportPath"
if ($overallPass) {
    exit 0
}

exit 1
