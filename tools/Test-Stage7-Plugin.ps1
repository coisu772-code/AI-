[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$isolated = [System.IO.Path]::GetFullPath((Join-Path $root ".stage7-plugin-isolated"))
if (-not $isolated.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 7 plugin test root."
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 7 plugin validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source run python "tools/validate_plugin.py"
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 plugin manifest validation failed." }

    $pluginRoot = Join-Path $root "plugins\ai-video-channel-production"
    $skillRoot = Join-Path $pluginRoot "skills"
    foreach ($skill in @(Get-ChildItem -LiteralPath $skillRoot -Directory | Sort-Object Name | ForEach-Object { $_.Name })) {
        & $uv.Source run python "C:\Users\Administrator\.codex\skills\.system\skill-creator\scripts\quick_validate.py" (Join-Path $skillRoot $skill)
        if ($LASTEXITCODE -ne 0) { throw "Stage 7 Skill validation failed: $skill" }
    }
    & $uv.Source run --no-project python (Join-Path $skillRoot "data-center\scripts\check_data_center_install.py") --plugin-root $pluginRoot --json
    if ($LASTEXITCODE -ne 0) { throw "Source-tree Data Center Skill dynamic health failed." }

    if (Test-Path -LiteralPath $isolated) { Remove-Item -LiteralPath $isolated -Recurse -Force }
    New-Item -ItemType Directory -Path $isolated -Force | Out-Null
    $installRoot = Join-Path $isolated "install"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $installRoot -SkipCodexRegistration
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 isolated installation failed." }

    $env:AIVCP_DATA_ROOT = Join-Path $isolated "data"
    $healthJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installRoot "current\installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $installRoot -AsJson | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Installed stage 7 health check failed." }
    $health = $healthJson | ConvertFrom-Json
    if (
        [string]$health.status -ne "PASS" -or
        [int]$health.skillCount -ne 9 -or
        [int]$health.contentToolCount -ne 32 -or
        -not [bool]$health.serviceChecked -or
        -not [bool]$health.dataCenterCapabilitiesChecked
    ) {
        throw "Installed health result did not verify all Stage 7 Skills, tools, and data capabilities."
    }
    $installedPlugin = Join-Path $installRoot "current\plugins\ai-video-channel-production"
    & $uv.Source run --no-project python (Join-Path $installedPlugin "skills\data-center\scripts\check_data_center_install.py") --plugin-root $installedPlugin --json
    if ($LASTEXITCODE -ne 0) { throw "Installed Data Center Skill dynamic health failed." }
}
finally {
    Remove-Item Env:AIVCP_DATA_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $isolated) { Remove-Item -LiteralPath $isolated -Recurse -Force }
    Pop-Location
}

Write-Output "Stage 7 Data Center Skill, seven-tool surface, AUTH_REQUIRED boundary, and isolated installation passed."
