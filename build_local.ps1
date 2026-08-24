param(
    [switch]$SkipFrontend = $false,
    [switch]$Full = $false
)

if ($Full) {
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host " Building narratible (exe + installer)" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
} else {
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host " Building narratible (exe only)" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
}

# 1. Build Frontend
if (-not $SkipFrontend) {
    Write-Host "`n[1] Building frontend static assets..." -ForegroundColor Yellow
    Push-Location frontend
    npm run build
    Pop-Location
} else {
    Write-Host "`n[1] Skipping frontend build..." -ForegroundColor DarkGray
}

# 2. PyInstaller
Write-Host "`n[2] Freezing Python backend with PyInstaller..." -ForegroundColor Yellow
# Ensure the locked PyInstaller version is installed in the active environment
python -m pip install -r backend\requirements-build.txt
# Chatterbox is part of the frozen app, so fail before a long PyInstaller run
# when the active build environment is incomplete. Its requirements file is
# intentionally separate because installing it can replace the selected Torch
# build; install it first, then reinstall the correct PyTorch build for this PC.
python -c "from chatterbox.tts import ChatterboxTTS; import torch; print('Chatterbox ready with torch', torch.__version__)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] Chatterbox is missing from the build environment." -ForegroundColor Red
    Write-Host "Install backend\requirements-chatterbox.txt, then reinstall the PyTorch build appropriate for this machine before rebuilding." -ForegroundColor Red
    exit $LASTEXITCODE
}
# --workpath keeps the analysis cache between runs so re-builds are faster
python -m PyInstaller narratible.spec --noconfirm --workpath build\pyinstaller-work --distpath dist

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] PyInstaller failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`nSUCCESS! Executable is at: dist\narratible\narratible.exe" -ForegroundColor Green

if (-not $Full) {
    exit 0
}

# 3. Inno Setup (Full mode only)
Write-Host "`n[3] Compiling Inno Setup installer..." -ForegroundColor Yellow
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
