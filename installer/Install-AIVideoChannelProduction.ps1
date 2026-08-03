[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [ValidateSet("Existing", "Online", "Offline")]
    [string]$RuntimeMode = "Existing",
    [string]$PythonExecutable,
    [string]$OfflineWheelhouseRoot,
    [switch]$SkipCodexRegistration,
    [switch]$Force,
    [ValidateSet("None", "AfterStagingHealth", "AfterSwitch", "AfterCodexRegistration")]
    [string]$FailureInjectionPoint = "None"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "CodexCli.ps1")

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}

function Invoke-AivcpRuntimeProvisioning {
    param(
        [Parameter(Mandatory = $true)][string]$StagingRoot,
        [Parameter(Mandatory = $true)][string]$Mode,
        [string]$RequestedPython,
        [string]$WheelhouseRoot
    )
    if ($Mode -eq "Existing") {
        return [ordered]@{ mode = "existing"; bundled = $false }
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv) {
        throw "Runtime provisioning needs uv. Install uv, or use RuntimeMode=Existing with AIVCP_PYTHON configured."
    }
    $requirements = Join-Path $StagingRoot "installer\runtime-requirements.txt"
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "Runtime requirements are missing from the installation payload."
    }
    $runtimeRoot = Join-Path $StagingRoot "runtime\python"
    $venvArguments = @("venv", $runtimeRoot)
    if (-not [string]::IsNullOrWhiteSpace($RequestedPython)) {
        $pythonFull = Resolve-AivcpFullPath $RequestedPython
        if (-not (Test-Path -LiteralPath $pythonFull -PathType Leaf)) {
            throw "Requested Python executable was not found: $pythonFull"
        }
        $venvArguments += @("--python", $pythonFull)
    }
    & $uv.Source @venvArguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the isolated Python runtime." }
    $runtimePython = Join-Path $runtimeRoot "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
        throw "The isolated Python runtime was not created correctly."
    }
    $installArguments = @("pip", "install", "--python", $runtimePython, "--requirement", $requirements)
    if ($Mode -eq "Offline") {
        if ([string]::IsNullOrWhiteSpace($WheelhouseRoot)) {
            throw "Offline runtime installation requires -OfflineWheelhouseRoot."
        }
        $wheelhouseFull = Resolve-AivcpFullPath $WheelhouseRoot
        if (-not (Test-Path -LiteralPath $wheelhouseFull -PathType Container)) {
            throw "Offline wheelhouse was not found: $wheelhouseFull"
        }
        $installArguments += @("--offline", "--find-links", $wheelhouseFull)
    }
    & $uv.Source @installArguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to install the isolated Python runtime dependencies." }
    & $runtimePython -c "import docx,jsonschema,pypdf,yaml; print('runtime-ok')" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "The isolated Python runtime dependency check failed." }
    return [ordered]@{ mode = $Mode.ToLowerInvariant(); bundled = $true; python = "runtime/python/Scripts/python.exe" }
}

$sourceFull = Resolve-AivcpFullPath $SourceRoot
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$dataFull = Resolve-AivcpDataRoot -InstallRoot $installFull -RequestedDataRoot $DataRoot
$productId = $script:AivcpProductId
$marketplaceName = $script:AivcpMarketplaceName
$pluginManifestPath = Join-Path $sourceFull "plugins\$productId\.codex-plugin\plugin.json"
$marketplacePath = Join-Path $sourceFull ".agents\plugins\marketplace.json"

if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) { throw "Plugin manifest not found: $pluginManifestPath" }
if (-not (Test-Path -LiteralPath $marketplacePath -PathType Leaf)) { throw "Marketplace manifest not found: $marketplacePath" }
$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseManifestPath = Join-Path $sourceFull "release-manifests\release-v$($pluginManifest.version).json"
if (-not (Test-Path -LiteralPath $releaseManifestPath -PathType Leaf)) { throw "Release manifest not found: $releaseManifestPath" }
$marketplace = Get-Content -LiteralPath $marketplacePath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseManifest = Get-Content -LiteralPath $releaseManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$pluginManifest.name -ne $productId) { throw "Unexpected plugin name: $($pluginManifest.name)" }
if ([string]$marketplace.name -ne $marketplaceName) { throw "Unexpected marketplace name: $($marketplace.name)" }
if ([string]$releaseManifest.productVersion -ne [string]$pluginManifest.version) { throw "Release manifest and plugin versions do not match." }

$payloadItems = @(".agents", "plugins", "contracts", "installer", "release-manifests", "docs", "README.md", "CHANGELOG.md", "LICENSE.md")
foreach ($item in $payloadItems) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceFull $item))) { throw "Installation payload is incomplete: $item" }
}

$requiredComponentIds = @("codex-plugin", "windows-installer", "cross-center-contracts")
$localToolComponent = $releaseManifest.components | Where-Object { $_.componentId -eq "local-tool-service" } | Select-Object -First 1
if ($null -ne $localToolComponent -and [bool]$localToolComponent.includedInRelease) { $requiredComponentIds += "local-tool-service" }
foreach ($componentId in $requiredComponentIds) {
    $component = $releaseManifest.components | Where-Object { $_.componentId -eq $componentId } | Select-Object -First 1
    if ($null -eq $component -or -not [bool]$component.includedInRelease -or $component.artifacts.Count -ne 1) {
        throw "Release manifest is missing one required artifact: $componentId"
    }
    $artifact = $component.artifacts[0]
    if ([string]$artifact.kind -ne "directory-tree") { throw "Unsupported release artifact kind for $componentId" }
    $artifactPath = Resolve-AivcpFullPath (Join-Path $sourceFull ([string]$artifact.relativePath))
    $sourcePrefix = $sourceFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $artifactPath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release artifact escapes SourceRoot: $componentId"
    }
    $actualArtifactHash = Get-AivcpTreeHash $artifactPath
    if ($actualArtifactHash -ne [string]$artifact.sha256) {
        throw "Release artifact fingerprint mismatch: $componentId (expected $($artifact.sha256), got $actualArtifactHash)"
    }
}

$sourceFingerprint = Get-AivcpTreeHash (Join-Path $sourceFull "plugins\$productId")
$currentPath = Join-Path $installFull "current"
$backupRoot = Join-Path $installFull "backups"
$markerPath = Join-Path $installFull "installation.json"
$existingStatePath = Join-Path $currentPath "install-state.json"
if (-not $Force -and (Test-Path -LiteralPath $existingStatePath -PathType Leaf)) {
    $existingState = Get-Content -LiteralPath $existingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$existingState.productVersion -eq [string]$pluginManifest.version -and [string]$existingState.pluginTreeSha256 -eq $sourceFingerprint) {
        if (-not $SkipCodexRegistration) {
            $codex = Get-CompatibleCodexPluginCli
            if ($null -eq $codex) { throw "Files are installed, but a compatible Codex CLI was not found for registration." }
            & $codex plugin marketplace add $currentPath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Codex marketplace registration failed." }
            & $codex plugin add "$productId@$marketplaceName" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Codex plugin installation failed." }
        }
        Write-Output "Already installed: $productId $($pluginManifest.version)"
        exit 0
    }
}

New-Item -ItemType Directory -Path $installFull -Force | Out-Null
New-Item -ItemType Directory -Path $dataFull -Force | Out-Null
$stagingPath = Join-Path $installFull (".i-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$createdBackupPath = $null
$activatedNewCurrent = $false
$previousMarkerBytes = if (Test-Path -LiteralPath $markerPath -PathType Leaf) { [System.IO.File]::ReadAllBytes($markerPath) } else { $null }
New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null

try {
    foreach ($item in $payloadItems) {
        Copy-Item -LiteralPath (Join-Path $sourceFull $item) -Destination $stagingPath -Recurse -Force
    }
    $installedFingerprint = Get-AivcpTreeHash (Join-Path $stagingPath "plugins\$productId")
    if ($sourceFingerprint -ne $installedFingerprint) { throw "Installed plugin fingerprint does not match the source payload." }
    $runtimeState = Invoke-AivcpRuntimeProvisioning -StagingRoot $stagingPath -Mode $RuntimeMode -RequestedPython $PythonExecutable -WheelhouseRoot $OfflineWheelhouseRoot
    $state = [ordered]@{
        schemaVersion = "1.1.0"
        productId = $productId
        productVersion = [string]$pluginManifest.version
        marketplaceName = $marketplaceName
        releaseManifestContentHash = [string]$releaseManifest.contentHash
        pluginTreeSha256 = $installedFingerprint
        userDataRoot = $dataFull
        legacyDataLocation = $dataFull.StartsWith(($installFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar), [System.StringComparison]::OrdinalIgnoreCase)
        runtime = $runtimeState
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stagingPath "install-state.json") -Encoding UTF8
    $stagingHealthCheck = Join-Path $stagingPath "installer\Test-AIVideoChannelProductionHealth.ps1"
    & $stagingHealthCheck -PluginRoot (Join-Path $stagingPath "plugins\$productId") -SkipServiceCheck
    if (-not $?) { throw "Staging files failed the static installation health check." }
    if ($FailureInjectionPoint -eq "AfterStagingHealth") { throw "TEST_FAILURE_INJECTION:AfterStagingHealth" }

    if (Test-Path -LiteralPath $currentPath) {
        $existingVersion = "unknown"
        if (Test-Path -LiteralPath $existingStatePath -PathType Leaf) {
            $existingState = Get-Content -LiteralPath $existingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $existingVersion = [string]$existingState.productVersion
        }
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $backupName = "v$existingVersion-" + (Get-Date -Format "yyyyMMdd-HHmmssfff")
        $createdBackupPath = Join-Path $backupRoot $backupName
        Move-Item -LiteralPath $currentPath -Destination $createdBackupPath
    }
    Move-Item -LiteralPath $stagingPath -Destination $currentPath
    $activatedNewCurrent = $true
    [ordered]@{
        schemaVersion = "1.1.0"
        productId = $productId
        activeVersion = [string]$pluginManifest.version
        activeRoot = "current"
        userDataRoot = $dataFull
        releaseManifestContentHash = [string]$releaseManifest.contentHash
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $markerPath -Encoding UTF8
    if ($FailureInjectionPoint -eq "AfterSwitch") { throw "TEST_FAILURE_INJECTION:AfterSwitch" }

    $postHealth = Join-Path $currentPath "installer\Test-AIVideoChannelProductionHealth.ps1"
    if ($RuntimeMode -eq "Existing") {
        & $postHealth -InstallRoot $installFull -DataRoot $dataFull -SkipServiceCheck
    }
    else {
        & $postHealth -InstallRoot $installFull -DataRoot $dataFull
    }
    if (-not $?) { throw "Activated version failed its installation health check." }

    if (-not $SkipCodexRegistration) {
        $codex = Get-CompatibleCodexPluginCli
        if ($null -eq $codex) { throw "A compatible Codex CLI was not found; automatic rollback will restore the previous version." }
        & $codex plugin marketplace add $currentPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Codex marketplace registration failed." }
        & $codex plugin add "$productId@$marketplaceName" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Codex plugin installation failed." }
    }
    if ($FailureInjectionPoint -eq "AfterCodexRegistration") { throw "TEST_FAILURE_INJECTION:AfterCodexRegistration" }
}
catch {
    $failure = $_
    if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue }
    if ($activatedNewCurrent -and (Test-Path -LiteralPath $currentPath)) {
        $failedRoot = Join-Path $installFull "failed-installs"
        New-Item -ItemType Directory -Path $failedRoot -Force | Out-Null
        Move-Item -LiteralPath $currentPath -Destination (Join-Path $failedRoot ("f-" + (Get-Date -Format "yyyyMMdd-HHmmssfff")))
    }
    if ($null -ne $createdBackupPath -and (Test-Path -LiteralPath $createdBackupPath) -and -not (Test-Path -LiteralPath $currentPath)) {
        Move-Item -LiteralPath $createdBackupPath -Destination $currentPath
    }
    if ($null -ne $previousMarkerBytes) {
        [System.IO.File]::WriteAllBytes($markerPath, $previousMarkerBytes)
    }
    elseif (Test-Path -LiteralPath $markerPath) {
        Remove-Item -LiteralPath $markerPath -Force
    }
    throw "Installation failed and the previous program version was restored automatically. $($failure.Exception.Message)"
}

Write-Output "Installed $productId $($pluginManifest.version) to $currentPath"
Write-Output "User data root: $dataFull"
Write-Output "Restart Codex and open a new task to load the plugin."
