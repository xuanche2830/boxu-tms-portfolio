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
$packagerVersion = & $python -m PyInstaller --version
if ($LASTEXITCODE -ne 0 -or $packagerVersion.Trim() -ne '6.22.3') {
    throw '请在 .venv 中安装 PyInstaller==6.22.3'
}
& $python -m PyInstaller --noconfirm --clean `
    --distpath $OutputDir --workpath $workDir `
    (Join-Path $repoRoot 'packaging\boxu-desktop.spec')
if ($LASTEXITCODE -ne 0) {
    throw 'EXE 打包失败'
}
$exe = Join-Path $OutputDir 'Boxu-Windows-x64.exe'
if (-not (Test-Path $exe)) {
    throw '未找到预期的 EXE 文件'
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash.ToLowerInvariant()
$checksumFile = "$exe.sha256"
Set-Content -LiteralPath $checksumFile -Value "$hash  Boxu-Windows-x64.exe" -Encoding ascii
$packageDir = Join-Path $tempDir ('package-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $packageDir | Out-Null
Copy-Item -LiteralPath $exe, $checksumFile -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\QUICK-START.html') -Destination (Join-Path $packageDir '先读我.html')
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE'), (Join-Path $repoRoot 'THIRD_PARTY_NOTICES.md') -Destination $packageDir
& $python (Join-Path $repoRoot 'scripts\collect_licenses.py') (Join-Path $packageDir 'THIRD-PARTY-LICENSES.txt')
if ($LASTEXITCODE -ne 0) { throw '第三方许可收集失败' }
$zip = Join-Path $OutputDir 'Boxu-Windows-x64.zip'
Compress-Archive -Path (Join-Path $packageDir '*') -DestinationPath $zip -Force
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$zip.sha256" -Value "$zipHash  Boxu-Windows-x64.zip" -Encoding ascii
Write-Output "EXE: $exe"
Write-Output "SHA-256: $hash"
Write-Output "校验文件: $checksumFile"
Write-Output "使用包: $zip"
