[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$server = Join-Path $PSScriptRoot "server.py"

$configuredPython = [Environment]::GetEnvironmentVariable("AIVCP_PYTHON", "Process")
if (-not [string]::IsNullOrWhiteSpace($configuredPython) -and (Test-Path -LiteralPath $configuredPython -PathType Leaf)) {
    & $configuredPython $server mcp
    exit $LASTEXITCODE
}

$installedRuntime = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\runtime\python\python.exe"))
if (Test-Path -LiteralPath $installedRuntime -PathType Leaf) {
    & $installedRuntime $server mcp
    exit $LASTEXITCODE
}

$bundledPython = Join-Path $env:LOCALAPPDATA "AI Video Channel Production\current\runtime\python\python.exe"
if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
    & $bundledPython $server mcp
    exit $LASTEXITCODE
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uv) {
    & $uv.Source run --no-project python $server mcp
    exit $LASTEXITCODE
}

throw "The local tool service needs a compatible Python runtime. Run the installer repair action."
