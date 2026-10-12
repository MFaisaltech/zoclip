param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path $PSScriptRoot -Parent
Push-Location $backendRoot
try {
    $env:UV_CACHE_DIR = Join-Path $backendRoot '.tools/uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $backendRoot '.tools/python'
    $env:UV_PYTHON_DOWNLOADS = 'never'
    $localPython = Join-Path $env:UV_PYTHON_INSTALL_DIR 'cpython-3.12.15-windows-x86_64-none/python.exe'
    $localUv = Join-Path $backendRoot '.tools/uv/uv.exe'
    if (-not (Test-Path -LiteralPath $localPython)) { throw 'Install Python 3.12.15 under .tools/python first.' }
    if (-not (Test-Path -LiteralPath $localUv)) { throw 'Project-local uv is missing from .tools/uv.' }
    $syncArgs = @('sync', '--frozen', '--python', $localPython)
    if ($Offline) { $syncArgs += '--offline' }
    & $localUv @syncArgs
    if ($LASTEXITCODE -ne 0) { throw 'Locked environment synchronization failed.' }
} finally { Pop-Location }
