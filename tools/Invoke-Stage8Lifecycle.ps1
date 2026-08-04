[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [string]$CodexExe = "",
    [string]$CodexModel = "gpt-5.4",
    [ValidateRange(15, 180)][int]$CodexSmokeTimeoutSeconds = 90
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
$localAppData = Join-Path $base "LocalAppData"
$defaultInstall = Join-Path $localAppData "AIVCP"
$defaultData = Join-Path $localAppData "AI Video Channel Production Data"
$oldDefaultData = Join-Path $localAppData "AI Video Channel Production\data"
$oldDefaultSentinel = Join-Path $oldDefaultData "existing-data-do-not-touch.txt"
$locatorPath = Join-Path $localAppData "AIVCP-Config\runtime-locator.json"
$unicodeInstallName = "$([char]0x4E2D)$([char]0x6587) Install"
$unicodeDataName = "$([char]0x7528)$([char]0x6237) Data"
$offlineInstall = Join-Path $base $unicodeInstallName
$offlineData = Join-Path $base $unicodeDataName
$onlineInstall = Join-Path $base "Online Install"
$onlineData = Join-Path $base "Online Data"
$sentinel = Join-Path $offlineData "preserve-me.txt"
$oldPath = $env:PATH
$hadLocalAppData = Test-Path Env:LOCALAPPDATA
$oldLocalAppData = $env:LOCALAPPDATA
$hadDisable = Test-Path Env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION
$oldDisable = $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION
$server = $null

try {
    New-Item -ItemType Directory -Path $oldDefaultData -Force | Out-Null
    [System.IO.File]::WriteAllText($oldDefaultSentinel, "preserve-existing-default-data", [System.Text.UTF8Encoding]::new($false))
    $env:LOCALAPPDATA = $localAppData
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION = "1"

    & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -SkipCodexRegistration
    if (-not $?) { throw "Default-path unified installation failed." }
    if (-not [System.IO.Path]::GetFullPath($defaultInstall).Equals([System.IO.Path]::GetFullPath((Join-Path $localAppData "AIVCP")), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Default program root is not the locked short AIVCP path."
    }
    $longRuntimeFile = Join-Path $defaultInstall "current\runtime\python\Lib\site-packages\lxml\isoschematron\resources\xsl\iso-schematron-xslt1\iso_schematron_skeleton_for_xslt1.xsl"
    if (-not (Test-Path -LiteralPath $longRuntimeFile -PathType Leaf)) { throw "Default-path MAX_PATH regression file did not extract: $longRuntimeFile" }
    if ($longRuntimeFile.Length -ge 260) { throw "Locked short default path still exceeds legacy MAX_PATH: $($longRuntimeFile.Length)" }
    $defaultHealthPath = Join-Path $evidence "default-path-health.json"
    & (Join-Path $defaultInstall "current\installer\Test-AIVideoChannelProductionHealth.ps1") -AsJson | Set-Content -LiteralPath $defaultHealthPath -Encoding UTF8
    $defaultHealth = Get-Content -LiteralPath $defaultHealthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$defaultHealth.status -ne "PASS" -or -not [bool]$defaultHealth.serviceChecked) { throw "Default-path installed MCP health failed." }
    if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf)) { throw "Default installation did not create the runtime locator." }
    $defaultLocator = Get-Content -LiteralPath $locatorPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [System.IO.Path]::GetFullPath([string]$defaultLocator.installRoot).Equals([System.IO.Path]::GetFullPath($defaultInstall), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Default installation runtime locator points to the wrong program root."
    }
    & (Join-Path $defaultInstall "current\installer\Uninstall-AIVideoChannelProduction.ps1") -SkipCodexRemoval -Confirm:$false
    if (Test-Path -LiteralPath $defaultInstall) { throw "Default-path uninstall left program files behind." }
    if (-not (Test-Path -LiteralPath $defaultData -PathType Container)) { throw "Default-path uninstall removed separated user data." }
    if (Test-Path -LiteralPath $locatorPath) { throw "Default-path uninstall left its owned runtime locator behind." }
    if ((Get-Content -LiteralPath $oldDefaultSentinel -Raw -Encoding UTF8) -ne "preserve-existing-default-data") { throw "Default-path lifecycle changed pre-existing data from the retired long path." }

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

    $locatorBeforeInjectedFailure = [System.IO.File]::ReadAllBytes($locatorPath)
    $failureRejected = $false
    try {
        & (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -Force -FailureInjectionPoint AfterLocatorWrite
    }
    catch { $failureRejected = $_.Exception.Message -match "restored automatically" }
    if (-not $failureRejected) { throw "Injected activation failure was not rolled back." }
    $stateAfterFailure = Get-Content -LiteralPath (Join-Path $offlineInstall "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$stateAfterFailure.releaseManifestSha256 -ne [string]$stateBefore.releaseManifestSha256 -or -not (Test-Path -LiteralPath $sentinel)) { throw "Rollback did not restore the previous version and user data." }
    if ([Convert]::ToBase64String($locatorBeforeInjectedFailure) -ne [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($locatorPath))) { throw "Injected install failure did not restore the previous runtime locator bytes." }

    & (Join-Path $root "installer\Upgrade-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -SkipCodexRegistration
    if (-not $?) { throw "Upgrade entry point failed." }
    & (Join-Path $offlineInstall "current\installer\Rollback-AIVideoChannelProduction.ps1") -InstallRoot $offlineInstall -SkipCodexRegistration -Confirm:$false
    if (-not $? -or -not (Test-Path -LiteralPath $sentinel)) { throw "Explicit rollback entry point failed or changed user data." }
    & (Join-Path $offlineInstall "current\installer\Repair-AIVideoChannelProduction.ps1") -ManifestPath $manifest -AssetRoot $assets -InstallMode Offline -InstallRoot $offlineInstall -DataRoot $offlineData -SkipCodexRegistration
    if (-not $? -or -not (Test-Path -LiteralPath $sentinel)) { throw "Repair failed or changed user data." }

    $runtimePython = Join-Path $offlineInstall "current\runtime\python\python.exe"
    $cachedPluginRoot = Join-Path $base "Fresh Codex Cache\ai-video-channel-production"
    New-Item -ItemType Directory -Path (Split-Path -Parent $cachedPluginRoot) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $offlineInstall "current\plugins\ai-video-channel-production") -Destination $cachedPluginRoot -Recurse
    $cachedRuntimeReport = Join-Path $evidence "cached-plugin-runtime-validation.json"
    & $runtimePython (Join-Path $root "tools\validate_cached_plugin_runtime.py") --cached-plugin-root $cachedPluginRoot --local-app-data $localAppData --expected-install-root $offlineInstall --report $cachedRuntimeReport
    if ($LASTEXITCODE -ne 0) { throw "Fresh cached-plugin MCP runtime locator validation failed." }
    $cachedRuntime = Get-Content -LiteralPath $cachedRuntimeReport -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$cachedRuntime.status -ne "PASS" -or [string]$cachedRuntime.mode -ne "RUNTIME_BOUND_DESCRIPTOR_FRESH_PROCESS" -or -not [bool]$cachedRuntime.descriptorCommandDirectToPython -or [bool]$cachedRuntime.powershellOrCmdProxy) { throw "Cached-plugin runtime evidence is invalid." }
    $staleCachedPluginRoot = Join-Path $base "Stale Codex Cache\ai-video-channel-production"
    New-Item -ItemType Directory -Path (Split-Path -Parent $staleCachedPluginRoot) -Force | Out-Null
    Copy-Item -LiteralPath $cachedPluginRoot -Destination $staleCachedPluginRoot -Recurse
    $staleManifestPath = Join-Path $staleCachedPluginRoot ".codex-plugin\plugin.json"
    $staleManifest = Get-Content -LiteralPath $staleManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $staleManifest.version = "0.7.0-stale-cache"
    [System.IO.File]::WriteAllText($staleManifestPath, ($staleManifest | ConvertTo-Json -Depth 12) + "`n", [System.Text.UTF8Encoding]::new($false))
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $staleOutput = (& $runtimePython (Join-Path $root "tools\validate_cached_plugin_runtime.py") --cached-plugin-root $staleCachedPluginRoot --local-app-data $localAppData --expected-install-root $offlineInstall --report (Join-Path $evidence "stale-cache-must-not-pass.json") 2>&1) | Out-String
        $staleExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    [System.IO.File]::WriteAllText((Join-Path $evidence "stale-cache-rejection.txt"), $staleOutput, [System.Text.UTF8Encoding]::new($false))
    if ($staleExitCode -eq 0 -or $staleOutput -notmatch "exited with 2") {
        throw "A stale cached plugin was not rejected by the runtime binding."
    }
    if ((Get-Content -LiteralPath $sentinel -Raw -Encoding UTF8) -ne "preserve-user-data") {
        throw "Stale cached plugin rejection changed user data."
    }
    $actualCodexCliMcp = $false
    $actualCodexCliReport = $null
    if (-not [string]::IsNullOrWhiteSpace($CodexExe)) {
        $actualCodexCliReport = Join-Path $evidence "actual-codex-cli-mcp-validation.json"
        & $runtimePython (Join-Path $root "tools\validate_actual_codex_cli_mcp.py") `
            --codex-exe $CodexExe `
            --cached-plugin-root $cachedPluginRoot `
            --local-app-data $localAppData `
            --expected-install-root $offlineInstall `
            --model $CodexModel `
            --timeout-seconds $CodexSmokeTimeoutSeconds `
            --report $actualCodexCliReport `
            --events (Join-Path $evidence "actual-codex-cli-mcp-events.jsonl") `
            --last-message (Join-Path $evidence "actual-codex-cli-mcp-last-message.json")
        if ($LASTEXITCODE -ne 0) { throw "Actual Codex CLI runtime-bound MCP validation failed." }
        $actualCodex = Get-Content -LiteralPath $actualCodexCliReport -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$actualCodex.status -ne "PASS" -or -not [bool]$actualCodex.toolsListObservedByCodex -or [bool]$actualCodex.timedOut) {
            throw "Actual Codex CLI runtime-bound MCP evidence is invalid."
        }
        $actualCodexCliMcp = $true
    }

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

    $locatorBeforeOtherInstallUninstall = [System.IO.File]::ReadAllBytes($locatorPath)
    & (Join-Path $offlineInstall "current\installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $offlineInstall -SkipCodexRemoval -Confirm:$false
    if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf) -or [Convert]::ToBase64String($locatorBeforeOtherInstallUninstall) -ne [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($locatorPath))) {
        throw "Uninstalling a non-owning installation changed another installation's runtime locator."
    }
    & (Join-Path $onlineInstall "current\installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $onlineInstall -SkipCodexRemoval -Confirm:$false
    if (Test-Path -LiteralPath $locatorPath) { throw "Uninstalling the locator-owning installation did not remove its locator." }
    if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf) -or -not (Test-Path -LiteralPath $onlineData -PathType Container)) { throw "Uninstall did not preserve user data." }
    if ((Get-Content -LiteralPath $oldDefaultSentinel -Raw -Encoding UTF8) -ne "preserve-existing-default-data") { throw "Lifecycle changed pre-existing retired-path user data." }
    $summary = [ordered]@{
        schemaVersion="1.0.0"; status="PASS"; offlineInstall=$true; fakeOnlineInstall=$true; singleFileOnlineEntry=$true; versionLockedManifestDownload=$true; noPreinstalledPython=$true; noPreinstalledUv=$true
        defaultShortInstallRoot=$defaultInstall; defaultPathFullLifecycle=$true; defaultPathMaxPathRegressionFileLength=$longRuntimeFile.Length; retiredDefaultPathDataPreserved=$true
        unicodeAndSpacesPath=$true; idempotentInstall=$true; tamperRejected=$true; injectedFailureRollback=$true; upgradeEntry=$true; explicitRollback=$true; repair=$true
        missingCodexGuidance=$true; windowsPowerShellMcpNoBomJsonlFileRelayHealth=$true; freshCachedPluginRuntimeBoundDescriptor=$true; cachedPluginReport=$cachedRuntimeReport
        staleCachedPluginVersionRejectedBeforeService=$true; actualCodexCliMcp=$actualCodexCliMcp; actualCodexCliReport=$actualCodexCliReport; actualCodexCliTimeoutSeconds=$CodexSmokeTimeoutSeconds; sandboxRerunRequired=$true
        uninstallPreservedData=$true; locatorOwnershipPreservedAcrossOtherInstallUninstall=$true; externalActionsExecuted=$false; formalProgramTouched=$false; userDataSentinel=$sentinel
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence "lifecycle-summary.json") -Encoding UTF8
}
finally {
    if ($null -ne $server -and -not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
    $env:PATH = $oldPath
    if ($hadLocalAppData) { $env:LOCALAPPDATA = $oldLocalAppData } else { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue }
    if ($hadDisable) { $env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION = $oldDisable } else { Remove-Item Env:AIVCP_DISABLE_CODEX_AUTO_REGISTRATION -ErrorAction SilentlyContinue }
}
Write-Output "Unified offline/online installation lifecycle PASS: $evidence"
