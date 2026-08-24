[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$ManifestUrl = "https://github.com/coisu772-code/AI-/releases/download/v0.14.0-rc.1/unified-release-v0.14.0-rc.1.json",
    [string]$AssetRoot = $PSScriptRoot,
    [string]$DownloadBaseUrl,
    [ValidateSet("Auto", "Offline", "Online")]
    [string]$InstallMode = "Auto",
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [string]$DataRoot,
    [switch]$AllowInsecureTestTransport,
    [switch]$SkipCodexRegistration,
    [switch]$Force,
    [ValidateSet("install", "upgrade", "repair")]
    [string]$LocatorOperation = "install",
    [ValidateSet("None", "AfterAssetVerification", "AfterMcpDescriptorBinding", "AfterStagingHealth", "AfterSwitch", "AfterLocatorWrite")]
    [string]$FailureInjectionPoint = "None"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "CodexCli.ps1")

$operationLock = Enter-AivcpOperationLock
$locatorSnapshot = $null
$descriptorSnapshot = $null
try {
$assetFull = Resolve-AivcpFullPath $AssetRoot
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$null = Assert-AivcpPathBudget (Join-Path $installFull "current\runtime\python\Lib\site-packages\lxml\isoschematron\resources\xsl\iso-schematron-xslt1\iso_schematron_skeleton_for_xslt1.xsl") "known longest bundled runtime path"
$null = Assert-AivcpPathBudget (Join-Path $installFull "downloads\manifest-cache\unified-release-v0.14.0-rc.1.json") "locked manifest cache"
$dataFull = Resolve-AivcpDataRoot -InstallRoot $installFull -RequestedDataRoot $DataRoot
$locatorSnapshot = Get-AivcpFileSnapshot (Get-AivcpRuntimeLocatorPath)
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $localManifest = Join-Path $assetFull "unified-release-v0.14.0-rc.1.json"
    if (Test-Path -LiteralPath $localManifest -PathType Leaf) {
        $ManifestPath = $localManifest
    }
    else {
        if ($InstallMode -eq "Offline") { throw "Offline installation requires unified-release-v0.14.0-rc.1.json beside install.cmd." }
        $manifestUri = [System.Uri]::new($ManifestUrl)
        if ($manifestUri.Scheme -ne "https" -and -not ($AllowInsecureTestTransport -and $manifestUri.IsLoopback)) {
            throw "Manifest download must use HTTPS. Only an explicit loopback test transport may use HTTP."
        }
        $manifestCache = Join-Path $installFull "downloads\manifest-cache"
        New-Item -ItemType Directory -Path $manifestCache -Force | Out-Null
        $ManifestPath = Join-Path $manifestCache "unified-release-v0.14.0-rc.1.json"
        Invoke-WebRequest -Uri $manifestUri.AbsoluteUri -OutFile $ManifestPath -UseBasicParsing
    }
}
$manifestFull = Resolve-AivcpFullPath $ManifestPath
if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) { throw "Locked release manifest is missing: $manifestFull" }
$manifest = Get-Content -LiteralPath $manifestFull -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$manifest.schemaVersion -ne "2.0.0" -or [string]$manifest.productId -ne $script:AivcpProductId) {
    throw "Unsupported or incorrect unified release manifest."
}
if ([string]$manifest.productVersion -ne "0.14.0-rc.1" -or @($manifest.assets).Count -ne 5 -or $null -eq $manifest.runtime -or $null -eq $manifest.safetyBoundaries) {
    throw "The downloaded manifest does not match the locked v0.14.0-rc.1 schema and product version."
}
if ([string]$manifest.releaseStatus -ne "candidate") { throw "Only a candidate locked manifest can be installed by this RC entry point." }
if ([string]$manifest.hashAlgorithm -ne "SHA-256") { throw "Unsupported release hash algorithm." }
if ([string]::IsNullOrWhiteSpace($DownloadBaseUrl)) { $DownloadBaseUrl = [string]$manifest.downloadBaseUrl }
$manifestHash = Get-AivcpManifestHash $manifestFull
$assets = @($manifest.assets | Where-Object { [bool]$_.install })
$requiredIds = @("core", "python-runtime", "workshop", "publisher-center")
foreach ($id in $requiredIds) {
    if (@($assets | Where-Object { [string]$_.assetId -eq $id }).Count -ne 1) { throw "Locked manifest requires exactly one install asset: $id" }
}

New-Item -ItemType Directory -Path $installFull -Force | Out-Null
New-Item -ItemType Directory -Path $dataFull -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dataFull "workshop-isolation") -Force | Out-Null
$cacheRoot = Join-Path $installFull ("downloads\" + $manifestHash)
$verified = @{}
foreach ($asset in $assets) {
    $null = Assert-AivcpPathBudget (Join-Path $cacheRoot ([string]$asset.fileName)) "asset cache $($asset.assetId)"
    $verified[[string]$asset.assetId] = Get-AivcpVerifiedAsset -Asset $asset -AssetRoot $assetFull -CacheRoot $cacheRoot -InstallMode $InstallMode -DownloadBaseUrl $DownloadBaseUrl
}
if ($FailureInjectionPoint -eq "AfterAssetVerification") { throw "TEST_FAILURE_INJECTION:AfterAssetVerification" }

$currentPath = Join-Path $installFull "current"
$markerPath = Join-Path $installFull "installation.json"
$existingStatePath = Join-Path $currentPath "install-state.json"
$descriptorSnapshot = Get-AivcpFileSnapshot (Join-Path $currentPath "plugins\ai-video-channel-production\.mcp.json")
if (-not $Force -and (Test-Path -LiteralPath $existingStatePath -PathType Leaf)) {
    $existing = Get-Content -LiteralPath $existingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$existing.releaseManifestSha256 -eq $manifestHash) {
        $null = Write-AivcpRuntimeBoundMcpDescriptor -PluginRoot (Join-Path $currentPath "plugins\ai-video-channel-production") -InstallRoot $installFull -DataRoot $dataFull -ProductVersion ([string]$existing.productVersion) -ReleaseManifestSha256 ([string]$existing.releaseManifestSha256)
        if ($FailureInjectionPoint -eq "AfterMcpDescriptorBinding") { throw "TEST_FAILURE_INJECTION:AfterMcpDescriptorBinding" }
        $locatorPath = Get-AivcpRuntimeLocatorPath
        if ((Test-Path -LiteralPath $locatorPath -PathType Leaf) -and -not (Test-AivcpRuntimeLocatorOwnedBy -InstallRoot $installFull)) {
            Write-Warning "This idempotent verification did not take over the runtime locator from another installation. Run Repair explicitly to transfer ownership."
        }
        else {
            $null = Write-AivcpRuntimeLocator -InstallRoot $installFull -DataRoot $dataFull -ProductVersion ([string]$existing.productVersion) -Operation idempotent
        }
        $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason "Registration was not requested during this idempotent verification."
        if (-not $SkipCodexRegistration) {
            $codex = Get-CompatibleCodexPluginCli
            if ($null -ne $codex) {
                try {
                    & $codex plugin marketplace add $currentPath --json | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "marketplace add returned $LASTEXITCODE" }
                    & $codex plugin add "$($script:AivcpProductId)@$($script:AivcpMarketplaceName)" --json | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "plugin add returned $LASTEXITCODE" }
                    Remove-Item -LiteralPath $guide -Force -ErrorAction SilentlyContinue
                }
                catch { $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason $_.Exception.Message }
            }
            else { $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason "No compatible Codex CLI was found." }
        }
        Write-Output "Already installed and verified: $($manifest.productVersion)"
        if (Test-Path -LiteralPath $guide) { Write-Warning "Codex registration needs a manual step. See $guide" }
        return
    }
}

$stagingPath = Join-Path $installFull (".s-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$extractRoot = Join-Path $stagingPath "x"
$backupRoot = Join-Path $installFull "backups"
$createdBackupPath = $null
$activated = $false
$previousMarker = if (Test-Path -LiteralPath $markerPath -PathType Leaf) { [System.IO.File]::ReadAllBytes($markerPath) } else { $null }
for ($assetIndex = 0; $assetIndex -lt $assets.Count; $assetIndex++) {
    $asset = $assets[$assetIndex]
    $installSubpath = [string]$asset.installSubpath
    $stagedAssetRoot = if ([string]::IsNullOrWhiteSpace($installSubpath)) { $stagingPath } else { Join-Path $stagingPath $installSubpath }
    $activeAssetRoot = if ([string]::IsNullOrWhiteSpace($installSubpath)) { $currentPath } else { Join-Path $currentPath $installSubpath }
    Assert-AivcpArchivePathBudget -ArchivePath $verified[[string]$asset.assetId] -ExpectedRoot ([string]$asset.archiveRoot) -ExtractionRoot (Join-Path $extractRoot ([string]$assetIndex)) -StagedInstallRoot $stagedAssetRoot -ActiveInstallRoot $activeAssetRoot -AssetId ([string]$asset.assetId)
}
New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null

try {
    for ($assetIndex = 0; $assetIndex -lt $assets.Count; $assetIndex++) {
        $asset = $assets[$assetIndex]
        $assetId = [string]$asset.assetId
        $destination = if ([string]::IsNullOrWhiteSpace([string]$asset.installSubpath)) { $stagingPath } else { Join-Path $stagingPath ([string]$asset.installSubpath) }
        $expanded = Expand-AivcpVerifiedZip -ArchivePath $verified[$assetId] -DestinationPath (Join-Path $extractRoot ([string]$assetIndex)) -ExpectedRoot ([string]$asset.archiveRoot)
        Copy-AivcpDirectoryContents -SourcePath $expanded -DestinationPath $destination
    }
    Remove-Item -LiteralPath $extractRoot -Recurse -Force
    Copy-Item -LiteralPath $manifestFull -Destination (Join-Path $stagingPath "unified-release-manifest.json") -Force
    $runtimePython = Join-Path $stagingPath "runtime\python\python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) { throw "Bundled standalone Python runtime is missing python.exe." }
    & $runtimePython -c "import docx,jsonschema,lxml,pypdf,yaml; print('runtime-ok')" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Bundled standalone Python runtime health check failed." }
    $workshopExe = Get-ChildItem -LiteralPath (Join-Path $stagingPath "apps\workshop") -Filter "*.exe" -File | Sort-Object Length -Descending | Select-Object -First 1
    $publisherExe = Join-Path $stagingPath "apps\publisher\youtube-publisher-center.exe"
    if ($null -eq $workshopExe) { throw "Workshop component executable is missing." }
    if (-not (Test-Path -LiteralPath $publisherExe -PathType Leaf)) { throw "Publisher component executable is missing: $publisherExe" }
    foreach ($logical in @($manifest.logicalComponents)) {
        foreach ($file in @($logical.files)) {
            $logicalPath = Join-Path $stagingPath ([string]$file.relativeInstallPath)
            if (-not (Test-Path -LiteralPath $logicalPath -PathType Leaf)) { throw "Logical component file is missing: $($file.relativeInstallPath)" }
            if ((Get-AivcpFileSha256 $logicalPath) -ne [string]$file.sha256) { throw "Logical component hash mismatch: $($file.relativeInstallPath)" }
        }
    }
    $pluginRoot = Join-Path $stagingPath "plugins\$($script:AivcpProductId)"
    $pluginManifest = Get-Content -LiteralPath (Join-Path $pluginRoot ".codex-plugin\plugin.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$pluginManifest.version -ne [string]$manifest.productVersion) { throw "Core plugin and unified release versions differ." }
    $null = Write-AivcpRuntimeBoundMcpDescriptor -PluginRoot $pluginRoot -InstallRoot $installFull -DataRoot $dataFull -ProductVersion ([string]$manifest.productVersion) -ReleaseManifestSha256 $manifestHash -ComponentVerificationRoot $stagingPath
    if ($FailureInjectionPoint -eq "AfterMcpDescriptorBinding") { throw "TEST_FAILURE_INJECTION:AfterMcpDescriptorBinding" }
    $state = [ordered]@{
        schemaVersion = "2.0.0"; productId = $script:AivcpProductId; productVersion = [string]$manifest.productVersion
        marketplaceName = $script:AivcpMarketplaceName; releaseManifestSha256 = $manifestHash; userDataRoot = $dataFull
        installedAssets = @($assets | ForEach-Object { [ordered]@{ assetId = $_.assetId; fileName = $_.fileName; sha256 = $_.sha256; sizeBytes = $_.sizeBytes } })
        runtime = [ordered]@{
            bundled = $true
            python = "runtime/python/python.exe"
            youtubeCollectorModule = "runtime/python/Lib/site-packages/yt_dlp/__init__.py"
            youtubeJavascriptRuntime = "runtime/python/tools/deno.exe"
            locator = "AIVCP-Config/runtime-locator.json"
            version = [string]$manifest.runtime.pythonVersion
        }
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-AivcpJsonFile -Value $state -PathValue (Join-Path $stagingPath "install-state.json")
    & (Join-Path $stagingPath "installer\Test-AIVideoChannelProductionHealth.ps1") -PluginRoot $pluginRoot -SkipServiceCheck | Out-Null
    if ($FailureInjectionPoint -eq "AfterStagingHealth") { throw "TEST_FAILURE_INJECTION:AfterStagingHealth" }

    if (Test-Path -LiteralPath $currentPath) {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $oldVersion = if (Test-Path -LiteralPath $existingStatePath) { [string](Get-Content -LiteralPath $existingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json).productVersion } else { "unknown" }
        $createdBackupPath = Join-Path $backupRoot ("v$oldVersion-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
        Move-Item -LiteralPath $currentPath -Destination $createdBackupPath
    }
    Move-Item -LiteralPath $stagingPath -Destination $currentPath
    $activated = $true
    Write-AivcpJsonFile -Value ([ordered]@{ schemaVersion = "2.0.0"; productId = $script:AivcpProductId; activeVersion = [string]$manifest.productVersion; activeRoot = "current"; userDataRoot = $dataFull; releaseManifestSha256 = $manifestHash }) -PathValue $markerPath
    if ($FailureInjectionPoint -eq "AfterSwitch") { throw "TEST_FAILURE_INJECTION:AfterSwitch" }
    $null = Write-AivcpRuntimeLocator -InstallRoot $installFull -DataRoot $dataFull -ProductVersion ([string]$manifest.productVersion) -Operation $LocatorOperation -AllowTakeover
    if ($FailureInjectionPoint -eq "AfterLocatorWrite") { throw "TEST_FAILURE_INJECTION:AfterLocatorWrite" }
    & (Join-Path $currentPath "installer\Test-AIVideoChannelProductionHealth.ps1") -InstallRoot $installFull -DataRoot $dataFull | Out-Null

    $registrationReason = if ($SkipCodexRegistration) { "Automatic Codex registration was skipped by request." } else { "No compatible Codex CLI was found." }
    $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason $registrationReason
    if (-not $SkipCodexRegistration) {
        $codex = Get-CompatibleCodexPluginCli
        if ($null -ne $codex) {
            try {
                & $codex plugin marketplace add $currentPath --json | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "marketplace add returned $LASTEXITCODE" }
                & $codex plugin add "$($script:AivcpProductId)@$($script:AivcpMarketplaceName)" --json | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "plugin add returned $LASTEXITCODE" }
                Remove-Item -LiteralPath $guide -Force
                $guide = $null
            }
            catch { $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason $_.Exception.Message }
        }
    }
}
catch {
    $failure = $_
    if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue }
    if ($activated -and (Test-Path -LiteralPath $currentPath)) {
        $failedRoot = Join-Path $installFull "failed-installs"
        New-Item -ItemType Directory -Path $failedRoot -Force | Out-Null
        Move-Item -LiteralPath $currentPath -Destination (Join-Path $failedRoot ("failed-" + (Get-Date -Format "yyyyMMdd-HHmmssfff")))
    }
    if ($null -ne $createdBackupPath -and (Test-Path -LiteralPath $createdBackupPath) -and -not (Test-Path -LiteralPath $currentPath)) { Move-Item -LiteralPath $createdBackupPath -Destination $currentPath }
    if ($null -ne $previousMarker) { [System.IO.File]::WriteAllBytes($markerPath, $previousMarker) } elseif (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath -Force }
    Restore-AivcpFileSnapshot $locatorSnapshot
    throw "Installation failed and the previous program version was restored automatically. $($failure.Exception.Message)"
}

Write-Output "Installed $($manifest.productVersion) to $currentPath"
Write-Output "User data is preserved separately at $dataFull"
if ($null -ne $guide) { Write-Warning "Codex registration needs a manual step. See $guide" }
Write-Output "Restart Codex and create a new task after registration."
}
catch {
    if ($null -ne $descriptorSnapshot) { Restore-AivcpFileSnapshot $descriptorSnapshot }
    if ($null -ne $locatorSnapshot) { Restore-AivcpFileSnapshot $locatorSnapshot }
    throw
}
finally {
    Exit-AivcpOperationLock $operationLock
}
