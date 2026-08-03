[CmdletBinding()]
param(
    [string]$PublisherCliPath = $env:AIVCP_TEST_PUBLISHER_CLI_EXE
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$isolated = [System.IO.Path]::GetFullPath((Join-Path $root ".stage2-isolated"))
if (-not $isolated.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 2 test root."
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for isolated stage 2 validation." }
$pluginManifest = Get-Content -LiteralPath (Join-Path $root "plugins\ai-video-channel-production\.codex-plugin\plugin.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedProductVersion = [string]$pluginManifest.version

Push-Location $root
try {
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }

    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    if (-not [string]::IsNullOrWhiteSpace($PublisherCliPath)) {
        if (-not (Test-Path -LiteralPath $PublisherCliPath -PathType Leaf)) {
            throw "Publisher CLI path does not exist."
        }
        $env:AIVCP_TEST_PUBLISHER_CLI_EXE = [System.IO.Path]::GetFullPath($PublisherCliPath)
    }
    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "-m", "unittest", "discover", "-s", "tests", "-v")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 2 validation failed: uv $($arguments -join ' ')" }
    }

    $skillRoot = Join-Path $root "plugins\ai-video-channel-production\skills"
    foreach ($skill in @(Get-ChildItem -LiteralPath $skillRoot -Directory | Sort-Object Name | ForEach-Object { $_.Name })) {
        & $uv.Source run python "C:\Users\Administrator\.codex\skills\.system\skill-creator\scripts\quick_validate.py" (Join-Path $root "plugins\ai-video-channel-production\skills\$skill")
        if ($LASTEXITCODE -ne 0) { throw "Skill validation failed: $skill" }
    }

    if (Test-Path -LiteralPath $isolated) {
        Remove-Item -LiteralPath $isolated -Recurse -Force
    }
    New-Item -ItemType Directory -Path $isolated -Force | Out-Null
    $installRoot = Join-Path $isolated "install"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $installRoot -SkipCodexRegistration
    if ($LASTEXITCODE -ne 0) { throw "Stage 2 candidate installation failed." }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $installRoot -SkipCodexRegistration
    if ($LASTEXITCODE -ne 0) { throw "Stage 2 candidate idempotent installation failed." }
    $installedState = Get-Content -LiteralPath (Join-Path $installRoot "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$installedState.productVersion -ne $expectedProductVersion) {
        throw "Current candidate installed an unexpected version."
    }
    $isolatedPlugin = Join-Path $installRoot "current\plugins\ai-video-channel-production"
    $env:AIVCP_DATA_ROOT = Join-Path $isolated "data"
    $request = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"stage2-smoke","version":"1"}}}'
    $responseText = $request | powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $isolatedPlugin "mcp\start.ps1") | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Isolated MCP service failed to start." }
    $response = $responseText | ConvertFrom-Json
    if ([string]$response.result.serverInfo.name -ne "ai-video-channel-local-tools") {
        throw "Isolated MCP service returned an unexpected identity."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $isolated "data\system.db") -PathType Leaf)) {
        throw "Isolated MCP service did not initialize its isolated system registry."
    }
}
finally {
    Remove-Item Env:AIVCP_DATA_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    Remove-Item Env:AIVCP_TEST_PUBLISHER_CLI_EXE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $isolated) {
        Remove-Item -LiteralPath $isolated -Recurse -Force
    }
    Pop-Location
}

Write-Output "Stage 2 channel-library and local-tool-service validation passed in isolation."
