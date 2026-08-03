[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$isolated = [System.IO.Path]::GetFullPath((Join-Path $root ".stage6-plugin-isolated"))
if (-not $isolated.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 6 plugin test root."
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 6 plugin validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source run python "tools/validate_plugin.py"
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 plugin manifest validation failed." }

    $pluginRoot = Join-Path $root "plugins\ai-video-channel-production"
    $skillRoot = Join-Path $pluginRoot "skills"
    foreach ($skill in @(Get-ChildItem -LiteralPath $skillRoot -Directory | Sort-Object Name | ForEach-Object { $_.Name })) {
        & $uv.Source run python "C:\Users\Administrator\.codex\skills\.system\skill-creator\scripts\quick_validate.py" (Join-Path $skillRoot $skill)
        if ($LASTEXITCODE -ne 0) { throw "Stage 6 Skill validation failed: $skill" }
    }
    & $uv.Source run --no-project python (Join-Path $skillRoot "publish-video\scripts\check_publisher_install.py") --plugin-root $pluginRoot --json
    if ($LASTEXITCODE -ne 0) { throw "Source-tree publisher Skill dynamic health failed." }

    if (Test-Path -LiteralPath $isolated) { Remove-Item -LiteralPath $isolated -Recurse -Force }
    New-Item -ItemType Directory -Path $isolated -Force | Out-Null
    $installRoot = Join-Path $isolated "install"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $installRoot -SkipCodexRegistration
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 isolated installation failed." }

    $env:AIVCP_DATA_ROOT = Join-Path $isolated "data"
    $healthJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installRoot "current\installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $installRoot -AsJson | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Installed stage 6 health check failed." }
    $health = $healthJson | ConvertFrom-Json
    if (
        [string]$health.status -ne "PASS" -or
        [int]$health.skillCount -ne 8 -or
        [int]$health.contentToolCount -ne 25 -or
        -not [bool]$health.serviceChecked -or
        -not [bool]$health.contentCapabilitiesChecked -or
        -not [bool]$health.productionCapabilitiesChecked
    ) {
        throw "Installed health result did not verify all Stage 6 Skills and tools."
    }
    $installedPlugin = Join-Path $installRoot "current\plugins\ai-video-channel-production"
    & $uv.Source run --no-project python (Join-Path $installedPlugin "skills\publish-video\scripts\check_publisher_install.py") --plugin-root $installedPlugin --json
    if ($LASTEXITCODE -ne 0) { throw "Installed publisher Skill dynamic health failed." }
}
finally {
    Remove-Item Env:AIVCP_DATA_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $isolated) { Remove-Item -LiteralPath $isolated -Recurse -Force }
    Pop-Location
}

Write-Output "Stage 6 Skill, five-tool surface, offline boundaries, and isolated installation passed."
