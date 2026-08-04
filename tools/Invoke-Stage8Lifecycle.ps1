[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$assets = [System.IO.Path]::GetFullPath($AssetRoot)
$evidence = [System.IO.Path]::GetFullPath($EvidenceRoot)
$manifest = Join-Path $assets "unified-release-v0.8.0-rc.2.json"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Unified manifest is missing: $manifest" }
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$runId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$base = "C:\AIVCP-S8-$runId"
$unicodeInstallName = "$([char]0x4E2D)$([char]0x6587) Install"
$unicodeDataName = "$([char]0x7528)$([char]0x6237) Data"
$offlineInstall = Join-Path $base $unicodeInstallName
$offlineData = Join-Path $base $unicodeDataName
$onlineInstall = Join-Path $base "Online Install"
$onlineData = Join-Path $base "Online Data"
$sentinel = Join-Path $offlineData "preserve-me.txt"
$oldPath = $env:PATH
$hadDisable = Test-Path Env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION
$oldDisable = $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION
$server = $null

try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION = "1"
    & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData
    if (-not $?) { throw "Offline unified installation failed." }
    [System.IO.File]::WriteAllText($sentinel, "preserve-user-data", [System.Text.UTF8Encoding]::new($false))
    $stateBefore = Get-Content -LiteralPath (Join-Path $offlineInstall "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Get-Command uv -ErrorAction SilentlyContinue) { throw "No-uv simulation failed: uv remained visible in PATH." }
    if (Get-Command python -ErrorAction SilentlyContinue) { throw "No-Python simulation failed: python remained visible in PATH." }
    if (-not (Test-Path -LiteralPath (Join-Path $offlineInstall "current\CODEX-PLUGIN-SETUP.txt") -PathType Leaf)) { throw "Missing-Codex fallback guide was not created." }

    & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData
    if (-not $?) { throw "Idempotent reinstallation failed." }

    $tamperRoot = Join-Path $evidence "tampered-source"
    New-Item -ItemType Directory -Path $tamperRoot -Force | Out-Null
    $core = (Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).assets | Where-Object { $_.assetId -eq "core" } | Select-Object -First 1
    Copy-Item -LiteralPath (Join-Path $assets ([string]$core.fileName)) -Destination $tamperRoot
    [System.IO.File]::AppendAllText((Join-Path $tamperRoot ([string]$core.fileName)), "tamper")
    $tamperRejected = $false
    try {
        & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $tamperRoot -InstallMode Offline -InstallRoot (Join-Path $base "Tamper Install") -DataRoot (Join-Path $base "Tamper Data") -SkipCodexRegistration
    }
    catch { $tamperRejected = $_.Exception.Message -match "size mismatch|SHA-256 mismatch" }
    if (-not $tamperRejected) { throw "Tampered release asset was not rejected." }

    $failureRejected = $false
    try {
        & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -Force -FailureInjectionPoint AfterSwitch
    }
    catch { $failureRejected = $_.Exception.Message -match "restored automatically" }
    if (-not $failureRejected) { throw "Injected activation failure was not rolled back." }
    $stateAfterFailure = Get-Content -LiteralPath (Join-Path $offlineInstall "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$stateAfterFailure.releaseManifestSha256 -ne [string]$stateBefore.releaseManifestSha256 -or -not (Test-Path -LiteralPath $sentinel)) { throw "Rollback did not restore the previous version and user data." }

    & (Join-Path $root "installer\Upgrade-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -SkipCodexRegistration
    if (-not $?) { throw "Upgrade entry point failed." }
    & (Join-Path $offlineInstall "current\installer\Rollback-AIVideoChannelProduction.ps1") -InstallRoot $offlineInstall -SkipCodexRegistration -Confirm:$false
    if (-not $? -or -not (Test-Path -LiteralPath $sentinel)) { throw "Explicit rollback entry point failed or changed user data." }
    & (Join-Path $offlineInstall "current\installer\Repair-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -SkipCodexRegistration
    if (-not $? -or -not (Test-Path -LiteralPath $sentinel)) { throw "Repair failed or changed user data." }

    $runtimePython = Join-Path $offlineInstall "current\runtime\python\python.exe"
    $port = Get-Random -Minimum 52000 -Maximum 59000
    $server = Start-Process -FilePath $runtimePython -ArgumentList @("-m", "http.server", "$port", "--bind", "127.0.0.1", "--directory", $assets) -PassThru -WindowStyle Hidden
    $baseUrl = "http://127.0.0.1:$port"
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Invoke-WebRequest -Uri "$baseUrl/unified-release-v0.8.0-rc.2.json" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $ready) { throw "Fake online release source did not start." }
    $onlineSource = Join-Path $evidence "online-source"
    New-Item -ItemType Directory -Path $onlineSource -Force | Out-Null
    if (@(Get-ChildItem -LiteralPath $onlineSource -Force).Count -ne 0) { throw "Single-file online test source must start without a manifest or component assets." }
    & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestUrl "$baseUrl/unified-release-v0.8.0-rc.2.json" -AllowInsecureTestTransport -AssetRoot $onlineSource -DownloadBaseUrl $baseUrl -InstallMode Online -InstallRoot $onlineInstall -DataRoot $onlineData -SkipCodexRegistration
    if (-not $?) { throw "Fake online unified installation failed." }
    $server.Kill(); $server.WaitForExit(); $server = $null

    $offlineHealthPath = Join-Path $evidence "offline-health.json"
    $onlineHealthPath = Join-Path $evidence "online-health.json"
    & (Join-Path $offlineInstall "current\installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $offlineInstall -DataRoot $offlineData -AsJson | Set-Content -LiteralPath $offlineHealthPath -Encoding UTF8
    & (Join-Path $onlineInstall "current\installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $onlineInstall -DataRoot $onlineData -AsJson | Set-Content -LiteralPath $onlineHealthPath -Encoding UTF8
    foreach ($healthPath in @($offlineHealthPath, $onlineHealthPath)) {
        $health = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (
            [string]$health.status -ne "PASS" -or
            -not [bool]$health.serviceChecked -or
            -not [bool]$health.contentCapabilitiesChecked -or
            -not [bool]$health.productionCapabilitiesChecked -or
            -not [bool]$health.dataCenterCapabilitiesChecked
        ) {
            throw "Installed MCP health did not pass tools/list plus all capability checks: $healthPath"
        }
    }
    Copy-Item -LiteralPath (Join-Path $offlineInstall "current\install-state.json") -Destination (Join-Path $evidence "offline-install-state.json")
    Copy-Item -LiteralPath (Join-Path $onlineInstall "current\install-state.json") -Destination (Join-Path $evidence "online-install-state.json")
    Copy-Item -LiteralPath (Join-Path $offlineInstall "current\CODEX-PLUGIN-SETUP.txt") -Destination (Join-Path $evidence "missing-codex-guide.txt")

    & (Join-Path $offlineInstall "current\installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $offlineInstall -SkipCodexRemoval -Confirm:$false
    & (Join-Path $onlineInstall "current\installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $onlineInstall -SkipCodexRemoval -Confirm:$false
    if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf) -or -not (Test-Path -LiteralPath $onlineData -PathType Container)) { throw "Uninstall did not preserve user data." }
    $summary = [ordered]@{
        schemaVersion="1.0.0"; status="PASS"; offlineInstall=$true; fakeOnlineInstall=$true; singleFileOnlineEntry=$true; versionLockedManifestDownload=$true; noPreinstalledPython=$true; noPreinstalledUv=$true
        unicodeAndSpacesPath=$true; idempotentInstall=$true; tamperRejected=$true; injectedFailureRollback=$true; upgradeEntry=$true; explicitRollback=$true; repair=$true
        missingCodexGuidance=$true; windowsPowerShellMcpNoBomUtf8Health=$true; sandboxAttempt5RerunRequired=$true
        uninstallPreservedData=$true; externalActionsExecuted=$false; formalProgramTouched=$false; userDataSentinel=$sentinel
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence "lifecycle-summary.json") -Encoding UTF8
}
finally {
    if ($null -ne $server -and -not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
    $env:PATH = $oldPath
    if ($hadDisable) { $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION = $oldDisable } else { Remove-Item Env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION -ErrorAction SilentlyContinue }
}
Write-Output "Unified offline/online installation lifecycle PASS: $evidence"
