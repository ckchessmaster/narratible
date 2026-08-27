param(
    [switch]$SkipFrontend = $false,
    [switch]$SkipPackageVerification = $false,
    [switch]$Full = $false,
    [switch]$RecreateBuildEnv = $false,
    [switch]$SetupOnly = $false,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$buildEnv = Join-Path $repoRoot ".venv-build"
$buildPython = Join-Path $buildEnv "Scripts\python.exe"
$dependencyStamp = Join-Path $buildEnv ".dependency-fingerprint"

if ([string]::IsNullOrWhiteSpace($Version)) {
    $commit = (& git rev-parse --short=7 HEAD 2>$null)
    if ([string]::IsNullOrWhiteSpace($commit)) {
        $commit = "local"
    }
    $nonce = [guid]::NewGuid().ToString("N").Substring(0, 6)
    $Version = "0.0.0-dev-$commit-$nonce"
}
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z.+-]*$') {
    throw "Version '$Version' contains unsupported characters. Use letters, numbers, dots, plus signs, and hyphens."
}
$env:NARRATIBLE_APP_VERSION = $Version
$env:VITE_APP_VERSION = $Version

function Test-Python312 {
    param(
        [string]$FilePath,
        [string[]]$PrefixArguments = @()
    )

    & $FilePath @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$Description
    )

    & $FilePath @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description failed (exit code $exitCode)."
    }
}

function New-BuildEnvironment {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher -and (Test-Python312 -FilePath $pyLauncher.Source -PrefixArguments @("-3.12"))) {
        Invoke-NativeCommand -FilePath $pyLauncher.Source -ArgumentList @("-3.12", "-m", "venv", $buildEnv) -Description "Creating .venv-build with Python 3.12"
        return
    }

    $backendPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
    if ((Test-Path $backendPython) -and (Test-Python312 -FilePath $backendPython)) {
        Invoke-NativeCommand -FilePath $backendPython -ArgumentList @("-m", "venv", $buildEnv) -Description "Creating .venv-build from backend\.venv"
        return
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-Python312 -FilePath $pythonCommand.Source)) {
        Invoke-NativeCommand -FilePath $pythonCommand.Source -ArgumentList @("-m", "venv", $buildEnv) -Description "Creating .venv-build with Python 3.12"
        return
    }

    throw "Python 3.12 was not found. Install it or create backend\.venv with Python 3.12, then rerun this script."
}

if ($SetupOnly) {
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host " Preparing narratible build environment" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
} elseif ($Full) {
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host " Building narratible (exe + installer)" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
} else {
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host " Building narratible (exe only)" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
}
Write-Host "Version: $Version" -ForegroundColor DarkGray

# 1. Prepare the isolated Python build environment
Write-Host "`n[1] Preparing dedicated build environment..." -ForegroundColor Yellow
if ($RecreateBuildEnv -and (Test-Path $buildEnv)) {
    Write-Host "Removing existing .venv-build..." -ForegroundColor DarkGray
    Remove-Item -Recurse -Force $buildEnv
}
if (-not (Test-Path $buildPython)) {
    New-BuildEnvironment
}
if (-not (Test-Python312 -FilePath $buildPython)) {
    throw ".venv-build is not using Python 3.12. Rerun with -RecreateBuildEnv."
}

$dependencyFiles = @(
    (Join-Path $repoRoot "backend\constraints.txt"),
    (Join-Path $repoRoot "backend\requirements.txt"),
    (Join-Path $repoRoot "backend\requirements-build.txt")
)
$fingerprintLines = @(
    "python=3.12",
    "pip=26.2.1",
    "setuptools=70.2.0",
    "dependency-layout=4-slim-runtime"
)
foreach ($dependencyFile in $dependencyFiles) {
    $fingerprintLines += "$(Split-Path $dependencyFile -Leaf)=$((Get-FileHash $dependencyFile -Algorithm SHA256).Hash)"
}
$dependencyFingerprint = $fingerprintLines -join "`n"
$installedFingerprint = if (Test-Path $dependencyStamp) {
    (Get-Content $dependencyStamp -Raw).Trim()
} else {
    ""
}
$dependenciesInstalled = $false

if ($installedFingerprint -ne $dependencyFingerprint.Trim()) {
    Write-Host "Installing locked build dependencies (first setup can take several minutes)..." -ForegroundColor Yellow
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "pip==26.2.1", "setuptools==70.2.0") -Description "Installing build tooling"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[1]) -Description "Installing backend dependencies"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[2]) -Description "Installing PyInstaller"
    $dependenciesInstalled = $true
} else {
    Write-Host "Build dependencies are current." -ForegroundColor DarkGray
}

if ($dependenciesInstalled -or $SetupOnly -or $RecreateBuildEnv) {
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-c", "from PyInstaller import __version__ as pyinstaller_version; from backend.app.runtime_engines import load_runtime_catalog; import edge_tts, numpy; catalog=load_runtime_catalog(); print('Slim build environment ready | PyInstaller', pyinstaller_version, '| edge-tts', edge_tts.__version__, '| profiles', len(catalog['profiles']))") -Description "Validating the slim build environment"
} else {
    Write-Host "Build environment unchanged; skipping heavyweight dependency import checks." -ForegroundColor DarkGray
}
if ($dependenciesInstalled) {
    Set-Content -Path $dependencyStamp -Value $dependencyFingerprint
    $pyinstallerWorkPath = Join-Path $repoRoot "build\pyinstaller-work"
    if (Test-Path $pyinstallerWorkPath) {
        Write-Host "Clearing stale PyInstaller analysis after dependency changes..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $pyinstallerWorkPath
    }
}

Write-Host "Preparing private Python and uv runtime tools..." -ForegroundColor DarkGray
& (Join-Path $repoRoot "packaging\prepare_runtime_tools.ps1") -PythonExe $buildPython -OutputDir (Join-Path $repoRoot "build\runtime-tools")
if ($SetupOnly) {
    Write-Host "`nSUCCESS! Dedicated build environment is ready at: .venv-build" -ForegroundColor Green
    exit 0
}

# 2. Build Frontend
if (-not $SkipFrontend) {
    Write-Host "`n[2] Building frontend static assets..." -ForegroundColor Yellow
    Push-Location frontend
    try {
        Invoke-NativeCommand -FilePath "npm" -ArgumentList @("run", "build") -Description "Building frontend assets"
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[2] Skipping frontend build..." -ForegroundColor DarkGray
}

# 3. PyInstaller
Write-Host "`n[3] Freezing Python backend with PyInstaller..." -ForegroundColor Yellow
# --workpath keeps the analysis cache between runs so re-builds are faster
Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "PyInstaller", "narratible.spec", "--noconfirm", "--workpath", "build\pyinstaller-work", "--distpath", "dist") -Description "Freezing narratible with PyInstaller"

$packageDirectory = Join-Path $repoRoot "dist\narratible"
$packagedExecutable = Join-Path $packageDirectory "narratible.exe"
& (Join-Path $repoRoot "packaging\stage_runtime_profiles.ps1") -DestinationDir (Join-Path $packageDirectory "_internal\runtime_profiles")
Set-Content -Path (Join-Path $packageDirectory "app-version.txt") -Value $Version -NoNewline
if (-not $SkipPackageVerification) {
    Write-Host "`nVerifying slim packaged runtime..." -ForegroundColor Yellow
    Invoke-NativeCommand -FilePath $packagedExecutable -ArgumentList @("--verify-tts-imports") -Description "Validating slim packaged imports"
    $forbiddenPackages = @("torch", "torchaudio", "transformers", "kokoro", "f5_tts", "chatterbox", "qwen_tts", "bitsandbytes")
    foreach ($packageName in $forbiddenPackages) {
        if (Test-Path (Join-Path $packageDirectory "_internal\$packageName")) {
            throw "Slim package unexpectedly contains $packageName."
        }
    }
    if (Get-ChildItem $packageDirectory -Recurse -Filter "torch_cuda.dll" -ErrorAction SilentlyContinue) {
        throw "Slim package unexpectedly contains torch_cuda.dll."
    }
    foreach ($tclName in @("_tcl_data", "_tk_data", "tkinter")) {
        if (Test-Path (Join-Path $packageDirectory "_internal\$tclName")) {
            throw "Slim package unexpectedly contains $tclName."
        }
    }
} else {
    Write-Host "`nSkipping slim packaged runtime verification..." -ForegroundColor DarkGray
}

Write-Host "`nSUCCESS! Executable is at: dist\narratible\narratible.exe" -ForegroundColor Green

if (-not $Full) {
    exit 0
}

# 4. Inno Setup (Full mode only)
Write-Host "`n[4] Compiling Inno Setup installer..." -ForegroundColor Yellow
$isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (Test-Path $isccPath) {
    & $isccPath "/DMyAppVersion=$Version" "packaging\installer.iss"
    if ($LASTEXITCODE -eq 0) {
        $installerPath = Join-Path $repoRoot "packaging\Output\narratible_Installer.exe"
        $installerSize = (Get-Item $installerPath).Length
        $maxReleaseSize = 1800MB
        Write-Host ("Installer size: {0:N1} MB" -f ($installerSize / 1MB)) -ForegroundColor DarkGray
        if ($installerSize -gt $maxReleaseSize) {
            throw "Installer exceeds the 1.8 GiB release safety limit."
        }
        Write-Host "`nSUCCESS! Installer is at: packaging\Output\narratible_Installer.exe" -ForegroundColor Green
    } else {
        Write-Host "`n[ERROR] Inno Setup compilation failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    }
} else {
    Write-Host "`n[ERROR] Inno Setup compiler not found at '$isccPath'." -ForegroundColor Red
    Write-Host "Please install Inno Setup 6 from https://jrsoftware.org/isdl.php or compile packaging\installer.iss manually using the GUI." -ForegroundColor Red
}
