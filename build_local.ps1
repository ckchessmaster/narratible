param(
    [switch]$SkipFrontend = $false,
    [switch]$Full = $false,
    [switch]$RecreateBuildEnv = $false,
    [switch]$SetupOnly = $false
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$buildEnv = Join-Path $repoRoot ".venv-build"
$buildPython = Join-Path $buildEnv "Scripts\python.exe"
$dependencyStamp = Join-Path $buildEnv ".dependency-fingerprint"

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
    (Join-Path $repoRoot "backend\requirements-build.txt"),
    (Join-Path $repoRoot "backend\requirements-gpu.txt"),
    (Join-Path $repoRoot "backend\requirements-chatterbox.txt")
)
$fingerprintLines = @(
    "python=3.12",
    "pip=26.2.1",
    "setuptools=70.2.0",
    "torch=2.11.0+cu128",
    "torchaudio=2.11.0+cu128"
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
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-c", $dependencyFiles[0], "torch==2.11.0", "torchaudio==2.11.0", "--index-url", "https://download.pytorch.org/whl/cu128") -Description "Installing CUDA-enabled PyTorch"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[1]) -Description "Installing backend dependencies"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[2]) -Description "Installing PyInstaller"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[3]) -Description "Installing local voice engines"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "-r", $dependencyFiles[4]) -Description "Installing Chatterbox"
    Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-m", "pip", "install", "--upgrade", "--force-reinstall", "-c", $dependencyFiles[0], "torch==2.11.0", "torchaudio==2.11.0", "--index-url", "https://download.pytorch.org/whl/cu128") -Description "Restoring CUDA-enabled PyTorch"
    $dependenciesInstalled = $true
} else {
    Write-Host "Build dependencies are current." -ForegroundColor DarkGray
}

Invoke-NativeCommand -FilePath $buildPython -ArgumentList @("-c", "from PyInstaller import __version__ as pyinstaller_version; from chatterbox.tts import ChatterboxTTS; from f5_tts.api import F5TTS; from kokoro import KPipeline; import en_core_web_sm, torch, torchaudio, sys; en_core_web_sm.load(disable=['tok2vec', 'tagger', 'parser', 'attribute_ruler', 'lemmatizer', 'ner']); print('Build environment ready | PyInstaller', pyinstaller_version, '| torch', torch.__version__, '| torchaudio', torchaudio.__version__, '| cuda', torch.version.cuda); sys.exit(0 if torch.version.cuda else 1)") -Description "Validating the build environment"
if ($dependenciesInstalled) {
    Set-Content -Path $dependencyStamp -Value $dependencyFingerprint
    $pyinstallerWorkPath = Join-Path $repoRoot "build\pyinstaller-work"
    if (Test-Path $pyinstallerWorkPath) {
        Write-Host "Clearing stale PyInstaller analysis after dependency changes..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $pyinstallerWorkPath
    }
}
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

Write-Host "`nVerifying bundled TTS runtimes..." -ForegroundColor Yellow
$packagedExecutable = Join-Path $repoRoot "dist\narratible\narratible.exe"
Invoke-NativeCommand -FilePath $packagedExecutable -ArgumentList @("--verify-tts-imports") -Description "Validating packaged TTS imports"

Write-Host "`nSUCCESS! Executable is at: dist\narratible\narratible.exe" -ForegroundColor Green

if (-not $Full) {
    exit 0
}

# 4. Inno Setup (Full mode only)
Write-Host "`n[4] Compiling Inno Setup installer..." -ForegroundColor Yellow
$isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (Test-Path $isccPath) {
    # Read version from desktop_app.py so local builds match what the workflow does
    $version = (Select-String -Path desktop_app.py -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
    if (-not $version) { $version = "0.0.0-dev" }
    & $isccPath "/DMyAppVersion=$version" "packaging\installer.iss"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nSUCCESS! Installer is at: packaging\Output\narratible_Installer.exe" -ForegroundColor Green
    } else {
        Write-Host "`n[ERROR] Inno Setup compilation failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    }
} else {
    Write-Host "`n[ERROR] Inno Setup compiler not found at '$isccPath'." -ForegroundColor Red
    Write-Host "Please install Inno Setup 6 from https://jrsoftware.org/isdl.php or compile packaging\installer.iss manually using the GUI." -ForegroundColor Red
}
