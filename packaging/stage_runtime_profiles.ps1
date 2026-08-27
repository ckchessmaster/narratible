param(
    [string]$SourceDir = "backend\runtime_profiles",
    [string]$DestinationDir = "dist\narratible\_internal\runtime_profiles"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Resolve-RepoPath {
    param([string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

$sourceRoot = Resolve-RepoPath $SourceDir
$destinationRoot = Resolve-RepoPath $DestinationDir
if (-not (Test-Path $sourceRoot -PathType Container)) {
    throw "Runtime profile source directory was not found: $sourceRoot"
}

if (Test-Path $destinationRoot) {
    Remove-Item -Recurse -Force $destinationRoot
}
New-Item -ItemType Directory -Path $destinationRoot | Out-Null
Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $destinationRoot -Recurse -Force

$sourceFiles = @(Get-ChildItem $sourceRoot -Recurse -File)
foreach ($sourceFile in $sourceFiles) {
    $relativePath = [System.IO.Path]::GetRelativePath($sourceRoot, $sourceFile.FullName)
    $destinationPath = Join-Path $destinationRoot $relativePath
    if (-not (Test-Path $destinationPath -PathType Leaf)) {
        throw "Packaged runtime profile file is missing: $relativePath"
    }
    $sourceHash = (Get-FileHash $sourceFile.FullName -Algorithm SHA256).Hash
    $destinationHash = (Get-FileHash $destinationPath -Algorithm SHA256).Hash
    if ($sourceHash -ne $destinationHash) {
        throw "Packaged runtime profile file hash mismatch: $relativePath"
    }
}

Write-Host "Staged $($sourceFiles.Count) runtime profile files with matching SHA-256 hashes."