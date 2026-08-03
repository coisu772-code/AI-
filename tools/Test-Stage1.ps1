[CmdletBinding()]
param(
    [switch]$SkipInstallSmoke,
    [switch]$SkipCodexLoadSmoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pluginManifest = Get-Content -LiteralPath (Join-Path $root "plugins\ai-video-channel-production\.codex-plugin\plugin.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedProductVersion = [string]$pluginManifest.version
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw "uv was not found. Install uv or run the Python validators directly in an environment with project dependencies."
}

Push-Location $root
try {
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }

    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "-m", "unittest", "discover", "-s", "tests", "-v")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 1 validation command failed: uv $($arguments -join ' ')" }
    }

    if (-not $SkipInstallSmoke) {
        $smokeRoot = [System.IO.Path]::GetFullPath((Join-Path $root ".stage1-smoke"))
        $smokeDataRoot = [System.IO.Path]::GetFullPath((Join-Path $root ".stage1-smoke-data"))
        $expectedSmokeRoot = [System.IO.Path]::GetFullPath((Join-Path $root ".stage1-smoke"))
        if ($smokeRoot -ne $expectedSmokeRoot -or -not $smokeRoot.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected smoke-test path; refusing cleanup: $smokeRoot"
        }
        if (Test-Path -LiteralPath $smokeRoot) {
            Remove-Item -LiteralPath $smokeRoot -Recurse -Force
        }
        if (Test-Path -LiteralPath $smokeDataRoot) { Remove-Item -LiteralPath $smokeDataRoot -Recurse -Force }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -InstallRoot $smokeRoot -DataRoot $smokeDataRoot -SkipCodexRegistration
        if ($LASTEXITCODE -ne 0) { throw "Local installation smoke test failed." }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -InstallRoot $smokeRoot -DataRoot $smokeDataRoot -SkipCodexRegistration
        if ($LASTEXITCODE -ne 0) { throw "Idempotent installation smoke test failed." }
        & (Join-Path $root "installer\Upgrade-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $smokeRoot -DataRoot $smokeDataRoot -SkipCodexRegistration
        $backup = Get-ChildItem -LiteralPath (Join-Path $smokeRoot "backups") -Directory | Select-Object -First 1
        if ($null -eq $backup) { throw "Upgrade did not preserve a rollback backup." }
        & (Join-Path $root "installer\Rollback-AIVideoChannelProduction.ps1") -InstallRoot $smokeRoot -BackupName $backup.Name -SkipCodexRegistration -Confirm:$false
        $state = Get-Content -LiteralPath (Join-Path $smokeRoot "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$state.productId -ne "ai-video-channel-production" -or [string]$state.productVersion -ne $expectedProductVersion) {
            throw "Installed state does not match the current candidate after lifecycle validation."
        }
        & (Join-Path $root "installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $smokeRoot -SkipCodexRemoval -Confirm:$false
        if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $smokeRoot)) {
            throw "Local uninstall smoke test failed."
        }
        if (-not (Test-Path -LiteralPath $smokeDataRoot -PathType Container)) { throw "Uninstall did not preserve isolated user data." }
        Remove-Item -LiteralPath $smokeDataRoot -Recurse -Force
    }

    if (-not $SkipCodexLoadSmoke) {
        . (Join-Path $root "installer\CodexCli.ps1")
        $codex = Get-CompatibleCodexPluginCli
        if ($null -eq $codex) {
            throw "A Codex CLI with plugin install support was not found for isolated loading validation."
        }
        $codexHome = [System.IO.Path]::GetFullPath((Join-Path $root ".stage1-codex-home"))
        $expectedCodexHome = [System.IO.Path]::GetFullPath((Join-Path $root ".stage1-codex-home"))
        if ($codexHome -ne $expectedCodexHome -or -not $codexHome.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected Codex smoke-test path; refusing cleanup: $codexHome"
        }
        if (Test-Path -LiteralPath $codexHome) {
            Remove-Item -LiteralPath $codexHome -Recurse -Force
        }
        New-Item -ItemType Directory -Path $codexHome -Force | Out-Null
        $previousCodexHome = [Environment]::GetEnvironmentVariable("CODEX_HOME", "Process")
        try {
            $env:CODEX_HOME = $codexHome
            $marketplaceJson = (& $codex plugin marketplace add $root --json) | Out-String
            if ($LASTEXITCODE -ne 0) { throw "Isolated marketplace loading failed." }
            $marketplaceResult = $marketplaceJson | ConvertFrom-Json
            if ([string]$marketplaceResult.marketplaceName -ne "novel-manga-production") {
                throw "Codex loaded an unexpected marketplace."
            }
            $availableJson = (& $codex plugin list --available --json) | Out-String
            if ($LASTEXITCODE -ne 0) { throw "Codex plugin discovery failed." }
            $available = $availableJson | ConvertFrom-Json
            if (-not ($available.available | Where-Object { $_.name -eq "ai-video-channel-production" })) {
                throw "Codex did not discover ai-video-channel-production."
            }
            & $codex plugin add "ai-video-channel-production@novel-manga-production" --json | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Isolated Codex plugin installation failed." }
            $installedJson = (& $codex plugin list --json) | Out-String
            if ($LASTEXITCODE -ne 0) { throw "Installed plugin listing failed." }
            $installed = $installedJson | ConvertFrom-Json
            if (-not ($installed.installed | Where-Object { $_.name -eq "ai-video-channel-production" -and $_.enabled })) {
                throw "Installed plugin was not reported as enabled."
            }
        }
        finally {
            if ($null -eq $previousCodexHome) {
                Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue
            }
            else {
                $env:CODEX_HOME = $previousCodexHome
            }
            if (Test-Path -LiteralPath $codexHome) {
                Remove-Item -LiteralPath $codexHome -Recurse -Force
            }
        }
    }
}
finally {
    Pop-Location
}

Write-Output "Stage 1 local validation passed. Codex user configuration was not changed."
