param(
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path (Split-Path $repoRoot -Parent) 'release-build'
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$tempDir = Join-Path $repoRoot 'data\build-temp'
$workDir = Join-Path $repoRoot 'data\pyinstaller-work'
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw '请先在仓库根目录创建 .venv 并安装 requirements.txt'
}
& $python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw '请在 .venv 中安装 PyInstaller==6.22.3'
}
& $python -m PyInstaller --noconfirm --clean `
    --distpath $OutputDir --workpath $workDir `
    (Join-Path $repoRoot 'packaging\boxu-demo.spec')
if ($LASTEXITCODE -ne 0) {
    throw 'EXE 打包失败'
}
$exe = Join-Path $OutputDir 'Boxu-Demo-Windows-x64.exe'
if (-not (Test-Path $exe)) {
    throw '未找到预期的 EXE 文件'
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash.ToLowerInvariant()
$checksumFile = Join-Path $OutputDir 'Boxu-Demo-Windows-x64.exe.sha256'
Set-Content -LiteralPath $checksumFile -Value "$hash  Boxu-Demo-Windows-x64.exe" -Encoding ascii
Write-Output "EXE: $exe"
Write-Output "SHA-256: $hash"
Write-Output "校验文件: $checksumFile"
