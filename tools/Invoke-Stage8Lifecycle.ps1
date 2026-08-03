[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$EvidenceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$evidence = [System.IO.Path]::GetFullPath($EvidenceRoot)
if ($evidence -eq [System.IO.Path]::GetPathRoot($evidence) -or $evidence.Length -lt 20) { throw "EvidenceRoot is too broad." }
if (Test-Path -LiteralPath $evidence) { Remove-Item -LiteralPath $evidence -Recurse -Force }
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for Stage8 lifecycle validation." }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Run uv sync --locked before Stage8 lifecycle validation." }

$expectedWorkshopHash = "2c168cf5e1a886427fc564fc0d381d7a0915786a6d6ad10dec04131bb9d786a4"
$expectedPublisherHash = "a81ce665c4d7c7bb97e46760cdde5606e90982a692a901d552165125f3af86f9"
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $root)
$workshopExe = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot "apps") -Filter *.exe -File -Recurse -ErrorAction Stop |
    Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedWorkshopHash } |
    Select-Object -First 1 -ExpandProperty FullName
$publisherParents = @(Get-ChildItem -Path "E:\YouTube*" -Directory -ErrorAction SilentlyContinue)
$publisherExe = $publisherParents | ForEach-Object {
    Get-ChildItem -LiteralPath (Join-Path $_.FullName "youtube-publisher-center\build\bin") -Filter *.exe -File -ErrorAction SilentlyContinue
} | Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedPublisherHash } |
    Select-Object -First 1 -ExpandProperty FullName
if ([string]::IsNullOrWhiteSpace($workshopExe) -or [string]::IsNullOrWhiteSpace($publisherExe)) {
    throw "Frozen formal executable baselines could not be located by SHA-256."
}
$workshopBefore = (Get-FileHash -LiteralPath $workshopExe -Algorithm SHA256).Hash.ToLowerInvariant()
$publisherBefore = (Get-FileHash -LiteralPath $publisherExe -Algorithm SHA256).Hash.ToLowerInvariant()

$unicodeSandboxName = ([string][char]0x9A8C) + ([string][char]0x6536) + " space"
$unicodeProgramName = ([string][char]0x7A0B) + ([string][char]0x5E8F)
$unicodeDataName = ([string][char]0x6570) + ([string][char]0x636E)
$sandbox = Join-Path $evidence $unicodeSandboxName
$installRoot = Join-Path $sandbox $unicodeProgramName
$dataRoot = Join-Path $sandbox $unicodeDataName
$configRoot = Join-Path $sandbox "cfg"
$backupRoot = Join-Path $sandbox "bak"
$restoredData = Join-Path $sandbox "restored"
$codexHome = Join-Path $sandbox "Codex Home"
New-Item -ItemType Directory -Path $sandbox,$codexHome -Force | Out-Null

$installer = Join-Path $root "installer\Install-AIVideoChannelProduction.ps1"
$wheelhouse = Join-Path $sandbox "wheels"
& (Join-Path $root "installer\Build-OfflineWheelhouse.ps1") -OutputRoot $wheelhouse -PythonExecutable $python | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Offline wheelhouse preparation failed." }
$offlineInstall = Join-Path $sandbox "off-program"
$offlineData = Join-Path $sandbox "off-data"
& $installer -SourceRoot $root -InstallRoot $offlineInstall -DataRoot $offlineData -RuntimeMode Offline -PythonExecutable $python -OfflineWheelhouseRoot $wheelhouse -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Fresh isolated offline installation failed." }
$offlineHealth = (& (Join-Path $offlineInstall "current\installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $offlineInstall -DataRoot $offlineData -AsJson | Out-String) | ConvertFrom-Json
if ([string]$offlineHealth.status -ne "PASS" -or -not [bool]$offlineHealth.serviceChecked) { throw "Offline installation dynamic health check failed." }
& (Join-Path $root "installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $offlineInstall -SkipCodexRemoval -Confirm:$false | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $offlineData -PathType Container)) { throw "Offline installation uninstall/preservation check failed." }

& $installer -SourceRoot $root -InstallRoot $installRoot -DataRoot $dataRoot -RuntimeMode Online -PythonExecutable $python -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Fresh isolated online installation failed." }
$firstState = Get-Content -LiteralPath (Join-Path $installRoot "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$firstState.productVersion -ne "0.8.0-rc.1" -or [string]$firstState.userDataRoot -ne $dataRoot -or -not [bool]$firstState.runtime.bundled) {
    throw "Fresh installation state is invalid."
}
$backupCountBeforeRepeat = @(Get-ChildItem -LiteralPath (Join-Path $installRoot "backups") -Directory -ErrorAction SilentlyContinue).Count
& $installer -SourceRoot $root -InstallRoot $installRoot -DataRoot $dataRoot -RuntimeMode Existing -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Repeated isolated installation failed." }
$backupCountAfterRepeat = @(Get-ChildItem -LiteralPath (Join-Path $installRoot "backups") -Directory -ErrorAction SilentlyContinue).Count
if ($backupCountBeforeRepeat -ne $backupCountAfterRepeat) { throw "Idempotent repeat installation created an unnecessary backup." }

. (Join-Path $root "installer\CodexCli.ps1")
$codex = Get-CompatibleCodexPluginCli
if ($null -eq $codex) { throw "Compatible Codex CLI is required for isolated plugin discovery." }
$previousCodexHome = [Environment]::GetEnvironmentVariable("CODEX_HOME", "Process")
try {
    $env:CODEX_HOME = $codexHome
    $marketplaceResult = ((& $codex plugin marketplace add (Join-Path $installRoot "current") --json) | Out-String) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Isolated Codex marketplace registration failed." }
    & $codex plugin add "ai-video-channel-production@novel-manga-production" --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Isolated Codex plugin installation failed." }
    $installedPlugins = ((& $codex plugin list --json) | Out-String) | ConvertFrom-Json
    $pluginLoaded = $null -ne ($installedPlugins.installed | Where-Object { $_.name -eq "ai-video-channel-production" -and $_.enabled } | Select-Object -First 1)
    if (-not $pluginLoaded) { throw "Isolated Codex did not report the plugin as enabled." }
}
finally {
    if ($null -eq $previousCodexHome) { Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue } else { $env:CODEX_HOME = $previousCodexHome }
}

$seed = (& $uv.Source run python (Join-Path $root "tools\stage8_channel_state.py") seed --data-root $dataRoot --config-root $configRoot | Out-String) | ConvertFrom-Json
if ([string]$seed.status -ne "SEEDED") { throw "Lifecycle channel seed failed." }
$backupJson = (& (Join-Path $root "installer\Backup-AIVideoChannelProductionData.ps1") -InstallRoot $installRoot -DataRoot $dataRoot -DestinationRoot $backupRoot | Out-String) | ConvertFrom-Json
if ([string]$backupJson.status -ne "BACKUP_COMPLETE") { throw "User data backup failed." }

$pluginHashBeforeFailure = [string]$firstState.pluginTreeSha256
$failureObserved = $false
try {
    & $installer -SourceRoot $root -InstallRoot $installRoot -DataRoot $dataRoot -RuntimeMode Existing -SkipCodexRegistration -Force -FailureInjectionPoint AfterSwitch | Out-Null
}
catch {
    if ($_.Exception.Message -match "TEST_FAILURE_INJECTION:AfterSwitch") { $failureObserved = $true } else { throw }
}
if (-not $failureObserved) { throw "Intentional post-switch failure was not observed." }
$stateAfterFailure = Get-Content -LiteralPath (Join-Path $installRoot "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$stateAfterFailure.productVersion -ne "0.8.0-rc.1" -or [string]$stateAfterFailure.pluginTreeSha256 -ne $pluginHashBeforeFailure) {
    throw "Automatic rollback did not restore the previously active RC."
}

$legacyRoot = Join-Path $evidence "legacy-upgrade"
$legacySourceZip = Join-Path $legacyRoot "v0.1.0-beta.2.zip"
$legacySource = Join-Path $legacyRoot "source"
$legacyInstall = Join-Path $legacyRoot "program"
$legacyData = Join-Path $legacyInstall "data"
New-Item -ItemType Directory -Path $legacyRoot -Force | Out-Null
& git -C $root archive --format=zip --output=$legacySourceZip v0.1.0-beta.2
if ($LASTEXITCODE -ne 0) { throw "Could not construct the published v0.1.0-beta.2 source fixture." }
Expand-Archive -LiteralPath $legacySourceZip -DestinationPath $legacySource
& (Join-Path $legacySource "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $legacySource -InstallRoot $legacyInstall -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Legacy beta installation failed." }
New-Item -ItemType Directory -Path (Join-Path $legacyData "channels\legacy-fixture") -Force | Out-Null
"synthetic legacy marker`n" | Set-Content -LiteralPath (Join-Path $legacyData "channels\legacy-fixture\marker.txt") -Encoding UTF8
& (Join-Path $root "installer\Upgrade-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $legacyInstall -DataRoot $legacyData -RuntimeMode Existing -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Upgrade from v0.1.0-beta.2 failed." }
$legacyUpgradedState = Get-Content -LiteralPath (Join-Path $legacyInstall "current\install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$legacyUpgradedState.productVersion -ne "0.8.0-rc.1" -or -not (Test-Path -LiteralPath (Join-Path $legacyData "channels\legacy-fixture\marker.txt"))) {
    throw "Legacy upgrade did not preserve the existing user data location."
}

& (Join-Path $root "installer\Uninstall-AIVideoChannelProduction.ps1") -InstallRoot $installRoot -SkipCodexRemoval -Confirm:$false | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Isolated uninstall failed." }
if (Test-Path -LiteralPath $installRoot -PathType Container) { throw "Program root still exists after uninstall with external data root." }
if (-not (Test-Path -LiteralPath $dataRoot -PathType Container)) { throw "Uninstall removed the user data root." }

& (Join-Path $root "installer\Restore-AIVideoChannelProductionData.ps1") -ArchivePath $backupJson.archivePath -InstallRoot $installRoot -DataRoot $restoredData -Confirm:$false | Out-Null
if ($LASTEXITCODE -ne 0) { throw "User data restore failed." }
& $installer -SourceRoot $root -InstallRoot $installRoot -DataRoot $restoredData -RuntimeMode Existing -SkipCodexRegistration | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Reinstallation after restore failed." }
$restored = (& $uv.Source run python (Join-Path $root "tools\stage8_channel_state.py") verify --data-root $restoredData --config-root $configRoot | Out-String) | ConvertFrom-Json
if ([string]$restored.status -ne "RESTORED_AND_REBOUND" -or [string]$restored.channelProfileId -ne [string]$seed.channelProfileId) {
    throw "Restored channel could not be rebound from a new task."
}

$workshopAfter = (Get-FileHash -LiteralPath $workshopExe -Algorithm SHA256).Hash.ToLowerInvariant()
$publisherAfter = (Get-FileHash -LiteralPath $publisherExe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($workshopBefore -ne $workshopAfter -or $publisherBefore -ne $publisherAfter) { throw "A formal executable changed during isolated lifecycle validation." }
$summary = [ordered]@{
    schemaVersion = "1.0.0"
    productVersion = "0.8.0-rc.1"
    status = "PASS"
    isolationRoot = $sandbox
    formalCodexConfigurationTouched = $false
    freshInstall = "PASS"
    runtimeProvisioning = [ordered]@{ online = "PASS"; offline = "PASS"; offlineWheelhouse = $wheelhouse; offlineServiceHealth = [bool]$offlineHealth.serviceChecked }
    repeatedInstall = "IDEMPOTENT_PASS"
    codexHome = $codexHome
    codexPluginLoaded = $pluginLoaded
    upgrade = [ordered]@{ from = "0.1.0-beta.2"; to = "0.8.0-rc.1"; status = "PASS"; legacyDataPreserved = $true }
    intentionalFailureRollback = [ordered]@{ status = "PASS"; injectionPoint = "AfterSwitch"; restoredVersion = [string]$stateAfterFailure.productVersion }
    backup = [ordered]@{ status = "PASS"; path = [string]$backupJson.archivePath; sha256 = [string]$backupJson.sha256; payloadHash = [string]$backupJson.payloadHash }
    uninstall = [ordered]@{ status = "PASS"; programRemoved = $true; userDataPreserved = $true }
    restoreAndRebind = [ordered]@{ status = "PASS"; channelProfileId = [string]$restored.channelProfileId; newTaskBound = [bool]$restored.bindingProofPresent }
    pathCoverage = @("Unicode", "spaces", "separate program/data/Codex home")
    formalExecutables = [ordered]@{
        workshop = [ordered]@{ before = $workshopBefore; after = $workshopAfter; unchanged = $workshopBefore -eq $workshopAfter }
        publisherCenter = [ordered]@{ before = $publisherBefore; after = $publisherAfter; unchanged = $publisherBefore -eq $publisherAfter }
    }
    boundaries = [ordered]@{ oauth = "not_called"; upload = "not_called"; userMigration = "isolated_fixture_only"; longTermLearning = "not_called" }
}
$summaryPath = Join-Path $evidence "lifecycle-summary.json"
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$summary
