param(
    [string]$PythonExe = "python",
    [string]$OutputDir = "build\runtime-tools",
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $repoRoot $OutputDir
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$Description
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

$scriptsDir = (& $PythonExe -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not locate the build Python scripts directory."
}
$uvSource = Join-Path $scriptsDir "uv.exe"
if (-not (Test-Path $uvSource)) {
    throw "uv.exe is not installed for the build interpreter. Install backend/requirements-build.txt first."
}

if (Test-Path $OutputDir) {
    Remove-Item -Recurse -Force $OutputDir
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null
Copy-Item $uvSource (Join-Path $OutputDir "uv.exe")

$pythonInstallDir = Join-Path $OutputDir "python-managed"
$oldInstallDir = $env:UV_PYTHON_INSTALL_DIR
try {
    $env:UV_PYTHON_INSTALL_DIR = $pythonInstallDir
    Invoke-Checked -FilePath $uvSource -ArgumentList @(
        "python", "install", $PythonVersion,
        "--install-dir", $pythonInstallDir,
        "--no-bin",
        "--no-registry"
    ) -Description "Installing private Python $PythonVersion"

    $managedPythons = @(
        Get-ChildItem $pythonInstallDir -Directory |
            Where-Object { -not $_.LinkType } |
            ForEach-Object { Get-Item (Join-Path $_.FullName "python.exe") -ErrorAction SilentlyContinue } |
            Sort-Object FullName
    )
    if ($managedPythons.Count -ne 1) {
        throw "Expected exactly one private Python executable under $pythonInstallDir; found $($managedPythons.Count)."
    }
    $managedPython = $managedPythons[0].FullName
}
finally {
    $env:UV_PYTHON_INSTALL_DIR = $oldInstallDir
}

$relativePython = [System.IO.Path]::GetRelativePath($OutputDir, $managedPython)
if ($relativePython.StartsWith("..")) {
    throw "Private Python marker escaped the runtime tools directory: $relativePython"
}
Set-Content -Path (Join-Path $OutputDir "python-path.txt") -Value $relativePython -NoNewline -Encoding ascii

$metadata = [ordered]@{
    schema_version = 1
    python_version = (& $managedPython -c "import platform; print(platform.python_version())").Trim()
    python_path = $relativePython
    uv_version = (& $uvSource --version).Trim()
}
$metadata | ConvertTo-Json | Set-Content -Path (Join-Path $OutputDir "tools.json") -Encoding utf8
Write-Host "Prepared private runtime tools at $OutputDir"