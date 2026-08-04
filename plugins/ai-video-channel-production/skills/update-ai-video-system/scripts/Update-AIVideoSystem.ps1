[CmdletBinding()]
param(
    [ValidateSet("Check", "Update")][string]$Action = "Check",
    [ValidateSet("stable", "prerelease")][string]$Channel = "stable",
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [string]$ExpectedVersion,
    [switch]$ConfirmUpdate,
    [string]$ReleaseFixturePath,
    [switch]$AllowLocalFixture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:ProductId = "ai-video-channel-production"
$script:RepositoryReleasesApi = "https://api.github.com/repos/coisu772-code/AI-/releases?per_page=100"
$script:UserAgent = "AIVCP-Update-Skill/1.0"
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false, $true)
[Console]::OutputEncoding = $script:Utf8NoBom
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12

if ($Action -eq "Update") {
    if (-not $ConfirmUpdate) { throw "UPDATE_CONFIRMATION_REQUIRED: run Check first and obtain the user's explicit confirmation in the current turn." }
    if ([string]::IsNullOrWhiteSpace($ExpectedVersion)) { throw "EXPECTED_VERSION_REQUIRED: confirmed updates must lock the version shown by Check." }
}
if (-not [string]::IsNullOrWhiteSpace($ReleaseFixturePath) -and -not $AllowLocalFixture) {
    throw "LOCAL_FIXTURE_NOT_ALLOWED: local Release fixtures require -AllowLocalFixture."
}

function Get-AivcpSha256Bytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function ConvertFrom-AivcpJsonBytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes, [Parameter(Mandatory = $true)][string]$Label)
    try {
        $text = $script:Utf8NoBom.GetString($Bytes)
        return $text | ConvertFrom-Json
    }
    catch { throw "$Label is not valid UTF-8 JSON. $($_.Exception.Message)" }
}

function Get-AivcpDownloadBytes {
    param([Parameter(Mandatory = $true)][string]$Source, [Parameter(Mandatory = $true)][string]$Label)
    if ($AllowLocalFixture) {
        [System.Uri]$fixtureUri = $null
        if ([System.Uri]::TryCreate($Source, [System.UriKind]::Absolute, [ref]$fixtureUri) -and $fixtureUri.IsFile) {
            if (-not (Test-Path -LiteralPath $fixtureUri.LocalPath -PathType Leaf)) { throw "$Label fixture is missing: $($fixtureUri.LocalPath)" }
            return [System.IO.File]::ReadAllBytes($fixtureUri.LocalPath)
        }
        if (Test-Path -LiteralPath $Source -PathType Leaf) {
            return [System.IO.File]::ReadAllBytes([System.IO.Path]::GetFullPath($Source))
        }
    }

    [System.Uri]$uri = $null
    if (-not [System.Uri]::TryCreate($Source, [System.UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne "https") {
        throw "$Label must use HTTPS."
    }
    if ($uri.Host -notin @("api.github.com", "github.com")) { throw "$Label must come from the built-in GitHub repository." }
    $client = New-Object System.Net.WebClient
    try {
        $client.Headers[[System.Net.HttpRequestHeader]::UserAgent] = $script:UserAgent
        $client.Headers[[System.Net.HttpRequestHeader]::Accept] = "application/vnd.github+json"
        return [byte[]]$client.DownloadData($uri)
    }
    catch { throw "$Label download failed. $($_.Exception.Message)" }
    finally { $client.Dispose() }
}

function ConvertTo-AivcpSemVer {
    param([Parameter(Mandatory = $true)][string]$Value)
    $normalized = $Value.Trim()
    if ($normalized.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) { $normalized = $normalized.Substring(1) }
    $match = [regex]::Match($normalized, '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$')
    if (-not $match.Success) { return $null }
    $hasPrerelease = $match.Groups[4].Success
    $parts = if ($hasPrerelease) { @($match.Groups[4].Value.Split('.')) } else { @() }
    foreach ($part in $parts) {
        if ($part -match '^[0-9]+$' -and $part.Length -gt 1 -and $part.StartsWith("0")) { return $null }
    }
    return [pscustomobject]@{
        Normalized = $normalized
        Major = [int64]$match.Groups[1].Value
        Minor = [int64]$match.Groups[2].Value
        Patch = [int64]$match.Groups[3].Value
        IsPrerelease = $hasPrerelease
        Prerelease = if ($hasPrerelease) { [string[]]$parts } else { $null }
    }
}

function Compare-AivcpSemVer {
    param([Parameter(Mandatory = $true)]$Left, [Parameter(Mandatory = $true)]$Right)
    foreach ($field in @("Major", "Minor", "Patch")) {
        if ([int64]$Left.$field -lt [int64]$Right.$field) { return -1 }
        if ([int64]$Left.$field -gt [int64]$Right.$field) { return 1 }
    }
    $leftPre = if ([bool]$Left.IsPrerelease) { @($Left.Prerelease) } else { @() }
    $rightPre = if ([bool]$Right.IsPrerelease) { @($Right.Prerelease) } else { @() }
    if (-not [bool]$Left.IsPrerelease -and -not [bool]$Right.IsPrerelease) { return 0 }
    if (-not [bool]$Left.IsPrerelease) { return 1 }
    if (-not [bool]$Right.IsPrerelease) { return -1 }
    $limit = [Math]::Min($leftPre.Count, $rightPre.Count)
    for ($index = 0; $index -lt $limit; $index++) {
        $leftPart = [string]$leftPre[$index]
        $rightPart = [string]$rightPre[$index]
        $leftNumeric = $leftPart -match '^[0-9]+$'
        $rightNumeric = $rightPart -match '^[0-9]+$'
        if ($leftNumeric -and $rightNumeric) {
            if ([int64]$leftPart -lt [int64]$rightPart) { return -1 }
            if ([int64]$leftPart -gt [int64]$rightPart) { return 1 }
        }
        elseif ($leftNumeric -and -not $rightNumeric) { return -1 }
        elseif (-not $leftNumeric -and $rightNumeric) { return 1 }
        else {
            $comparison = [string]::CompareOrdinal($leftPart, $rightPart)
            if ($comparison -lt 0) { return -1 }
            if ($comparison -gt 0) { return 1 }
        }
    }
    if ($leftPre.Count -lt $rightPre.Count) { return -1 }
    if ($leftPre.Count -gt $rightPre.Count) { return 1 }
    return 0
}

function Get-AivcpInstalledVersion {
    $installFull = [System.IO.Path]::GetFullPath($InstallRoot)
    $markerPath = Join-Path $installFull "installation.json"
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$marker.productId -ne $script:ProductId -or [string]::IsNullOrWhiteSpace([string]$marker.activeVersion)) {
            throw "Installed product marker is invalid: $markerPath"
        }
        $statePath = Join-Path $installFull "current\install-state.json"
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$state.productId -ne $script:ProductId -or [string]$state.productVersion -ne [string]$marker.activeVersion) {
                throw "Installed product marker and state versions do not match."
            }
        }
        return [pscustomobject]@{ Version = [string]$marker.activeVersion; Source = "installation-marker" }
    }

    $pluginManifestPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\..\.codex-plugin\plugin.json"))
    if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) { throw "Cannot determine the installed product version." }
    $plugin = Get-Content -LiteralPath $pluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$plugin.name -ne $script:ProductId -or [string]::IsNullOrWhiteSpace([string]$plugin.version)) {
        throw "Installed plugin manifest is invalid."
    }
    return [pscustomobject]@{ Version = [string]$plugin.version; Source = "plugin-manifest" }
}

function Get-AivcpReleases {
    if (-not [string]::IsNullOrWhiteSpace($ReleaseFixturePath)) {
        $bytes = [System.IO.File]::ReadAllBytes([System.IO.Path]::GetFullPath($ReleaseFixturePath))
    }
    else { $bytes = Get-AivcpDownloadBytes -Source $script:RepositoryReleasesApi -Label "GitHub Release catalog" }
    $parsed = ConvertFrom-AivcpJsonBytes -Bytes $bytes -Label "GitHub Release catalog"
    foreach ($release in @($parsed)) { Write-Output $release }
}

function Select-AivcpRelease {
    param([Parameter(Mandatory = $true)][object[]]$Releases)
    $bestRelease = $null
    $bestVersion = $null
    foreach ($release in $Releases) {
        if ([bool]$release.draft) { continue }
        $version = ConvertTo-AivcpSemVer ([string]$release.tag_name)
        if ($null -eq $version) { continue }
        $isPrerelease = [bool]$release.prerelease
        if ($Channel -eq "stable" -and ($isPrerelease -or [bool]$version.IsPrerelease)) { continue }
        if ($Channel -eq "prerelease" -and (-not $isPrerelease -or -not [bool]$version.IsPrerelease)) { continue }
        if ($null -eq $bestVersion -or (Compare-AivcpSemVer -Left $version -Right $bestVersion) -gt 0) {
            $bestRelease = $release
            $bestVersion = $version
        }
    }
    if ($null -eq $bestRelease) { return $null }
    return [pscustomobject]@{ Release = $bestRelease; Version = $bestVersion }
}

function Get-AivcpReleaseAsset {
    param([Parameter(Mandatory = $true)]$Release, [Parameter(Mandatory = $true)][string]$FileName)
    $matches = @($Release.assets | Where-Object { [string]$_.name -eq $FileName })
    if ($matches.Count -ne 1) { throw "Release must contain exactly one asset named $FileName." }
    if ([string]::IsNullOrWhiteSpace([string]$matches[0].browser_download_url)) { throw "Release asset has no download URL: $FileName" }
    return $matches[0]
}

function Get-AivcpManifestInfo {
    param([Parameter(Mandatory = $true)]$Selection)
    $version = [string]$Selection.Version.Normalized
    $manifestName = "unified-release-v$version.json"
    $manifestAsset = Get-AivcpReleaseAsset -Release $Selection.Release -FileName $manifestName
    $manifestBytes = Get-AivcpDownloadBytes -Source ([string]$manifestAsset.browser_download_url) -Label "Unified Release manifest"
    $manifestAssetSize = $manifestAsset.PSObject.Properties["size"]
    if ($null -ne $manifestAssetSize -and [int64]$manifestAssetSize.Value -gt 0 -and [int64]$manifestAssetSize.Value -ne $manifestBytes.Length) {
        throw "Unified Release manifest size differs from the GitHub Release asset record."
    }
    $manifest = ConvertFrom-AivcpJsonBytes -Bytes $manifestBytes -Label "Unified Release manifest"
    $expectedDownloadBaseUrl = "https://github.com/coisu772-code/AI-/releases/download/v$version"
    if (
        [string]$manifest.schemaVersion -ne "2.0.0" -or
        [string]$manifest.productId -ne $script:ProductId -or
        [string]$manifest.productVersion -ne $version -or
        [string]$manifest.hashAlgorithm -ne "SHA-256" -or
        ([string]$manifest.downloadBaseUrl).TrimEnd('/') -ne $expectedDownloadBaseUrl -or
        $null -eq $manifest.safetyBoundaries -or
        [bool]$manifest.safetyBoundaries.userDataIncluded -or
        [bool]$manifest.safetyBoundaries.credentialsIncluded
    ) { throw "Unified Release manifest identity, version, hash algorithm, or safety boundary is invalid." }

    $records = @($manifest.assets | Where-Object { [string]$_.assetId -eq "unified-installer" })
    if ($records.Count -ne 1) { throw "Unified Release manifest must contain exactly one unified-installer record." }
    $record = $records[0]
    $fileName = [string]$record.fileName
    if (
        [System.IO.Path]::GetFileName($fileName) -ne $fileName -or
        $fileName -ne "AI-Video-Channel-Production-Unified-Installer-v$version.zip" -or
        [int64]$record.sizeBytes -le 0 -or
        [string]$record.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]::IsNullOrWhiteSpace([string]$record.archiveRoot) -or
        [bool]$record.install -or
        @($record.compatibleProductVersions) -notcontains $version
    ) { throw "Unified Release manifest installer record is invalid." }
    $installerAsset = Get-AivcpReleaseAsset -Release $Selection.Release -FileName $fileName
    $installerAssetSize = $installerAsset.PSObject.Properties["size"]
    if ($null -ne $installerAssetSize -and [int64]$installerAssetSize.Value -gt 0 -and [int64]$installerAssetSize.Value -ne [int64]$record.sizeBytes) {
        throw "Unified installer size differs between the manifest and GitHub Release asset record."
    }
    return [pscustomobject]@{
        Manifest = $manifest
        ManifestName = $manifestName
        ManifestBytes = [byte[]]$manifestBytes
        Installer = $record
        InstallerAsset = $installerAsset
    }
}

function Expand-AivcpInstallerZip {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$ExpectedRoot
    )
    if ([System.IO.Path]::GetFileName($ExpectedRoot) -ne $ExpectedRoot) { throw "Unified installer archive root is unsafe." }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $normalized = $entry.FullName.Replace("\", "/")
            if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.StartsWith("/") -or $normalized -match '^[A-Za-z]:' -or -not $seen.Add($normalized)) {
                throw "Unified installer ZIP contains an unsafe or duplicate path: $normalized"
            }
            $parts = @($normalized.Split('/'))
            if ($parts[0] -ne $ExpectedRoot -or @($parts | Where-Object { $_ -in @(".", "..") -or $_.Contains(":") }).Count -gt 0) {
                throw "Unified installer ZIP root or entry path is invalid: $normalized"
            }
            $unixMode = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if ($unixMode -eq 0xA000) { throw "Unified installer ZIP symbolic links are not allowed: $normalized" }
        }
    }
    finally { $archive.Dispose() }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $DestinationPath)
    return Join-Path $DestinationPath $ExpectedRoot
}

$installed = Get-AivcpInstalledVersion
$currentSemVer = ConvertTo-AivcpSemVer $installed.Version
if ($null -eq $currentSemVer) { throw "Installed product version is not valid semantic versioning: $($installed.Version)" }
$selection = Select-AivcpRelease -Releases @(Get-AivcpReleases)
if ($null -eq $selection) {
    [ordered]@{
        status = "NO_RELEASE_AVAILABLE"
        action = "check"
        channel = $Channel
        currentVersion = $currentSemVer.Normalized
        targetVersion = $null
        confirmationRequired = $false
        userDataImpact = "This Skill did not write user data and did not run the unified installer."
    } | ConvertTo-Json -Depth 6
    return
}

$comparison = Compare-AivcpSemVer -Left $selection.Version -Right $currentSemVer
if ($comparison -le 0) {
    [ordered]@{
        status = "NO_UPDATE"
        action = "check"
        channel = $Channel
        currentVersion = $currentSemVer.Normalized
        targetVersion = $selection.Version.Normalized
        releaseUrl = [string]$selection.Release.html_url
        changeSummary = [string]$selection.Release.body
        confirmationRequired = $false
        userDataImpact = "This Skill did not write user data and did not run the unified installer."
    } | ConvertTo-Json -Depth 6
    return
}

$manifestInfo = Get-AivcpManifestInfo -Selection $selection
$checkResult = [ordered]@{
    status = "UPDATE_AVAILABLE"
    action = "check"
    channel = $Channel
    currentVersion = $currentSemVer.Normalized
    targetVersion = $selection.Version.Normalized
    releaseUrl = [string]$selection.Release.html_url
    changeSummary = [string]$selection.Release.body
    installer = [ordered]@{
        fileName = [string]$manifestInfo.Installer.fileName
        sizeBytes = [int64]$manifestInfo.Installer.sizeBytes
        sha256 = ([string]$manifestInfo.Installer.sha256).ToLowerInvariant()
    }
    confirmationRequired = $true
    confirmationPrompt = "Confirm update to $($selection.Version.Normalized)?"
    userDataImpact = "This Skill does not write user data directly. The existing unified installer preserves the separate data root and handles rollback."
}
if ($Action -eq "Check") {
    $checkResult | ConvertTo-Json -Depth 6
    return
}

$expected = ConvertTo-AivcpSemVer $ExpectedVersion
if ($null -eq $expected -or [string]$expected.Normalized -ne [string]$selection.Version.Normalized) {
    throw "CONFIRMED_VERSION_CHANGED: run Check again and confirm the currently selected version."
}

$temporaryBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$temporaryRoot = [System.IO.Path]::GetFullPath((Join-Path $temporaryBase ("aivcp-update-" + [guid]::NewGuid().ToString("N"))))
if (-not $temporaryRoot.StartsWith($temporaryBase, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Temporary update path escaped the system temporary directory." }
$archivePath = Join-Path $temporaryRoot ([string]$manifestInfo.Installer.fileName)
$extractRoot = Join-Path $temporaryRoot "extracted"
try {
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    $installerBytes = Get-AivcpDownloadBytes -Source ([string]$manifestInfo.InstallerAsset.browser_download_url) -Label "Unified installer ZIP"
    if ([int64]$installerBytes.Length -ne [int64]$manifestInfo.Installer.sizeBytes) { throw "Unified installer ZIP size mismatch." }
    $actualHash = Get-AivcpSha256Bytes $installerBytes
    if ($actualHash -ne ([string]$manifestInfo.Installer.sha256).ToLowerInvariant()) { throw "Unified installer ZIP SHA-256 mismatch." }
    [System.IO.File]::WriteAllBytes($archivePath, $installerBytes)
    $installerRoot = Expand-AivcpInstallerZip -ArchivePath $archivePath -DestinationPath $extractRoot -ExpectedRoot ([string]$manifestInfo.Installer.archiveRoot)
    $manifestPath = Join-Path $installerRoot ([string]$manifestInfo.ManifestName)
    [System.IO.File]::WriteAllBytes($manifestPath, [byte[]]$manifestInfo.ManifestBytes)
    $installerScript = Join-Path $installerRoot "Install-AIVideoChannelProduction.ps1"
    if (-not (Test-Path -LiteralPath $installerScript -PathType Leaf)) { throw "Unified installer ZIP is missing Install-AIVideoChannelProduction.ps1." }
    $powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
    $installerOutput = & $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installerScript -ManifestPath $manifestPath -AssetRoot $installerRoot -DownloadBaseUrl ([string]$manifestInfo.Manifest.downloadBaseUrl) -InstallMode Auto -InstallRoot $InstallRoot -Force -LocatorOperation upgrade 2>&1 | Out-String
    $installerExitCode = $LASTEXITCODE
    if ($installerExitCode -ne 0) {
        $tail = if ($installerOutput.Length -gt 1200) { $installerOutput.Substring($installerOutput.Length - 1200) } else { $installerOutput }
        throw "Existing unified installer failed with exit code $installerExitCode. $tail"
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}

[ordered]@{
    status = "UPDATED"
    action = "update"
    channel = $Channel
    previousVersion = $currentSemVer.Normalized
    targetVersion = $selection.Version.Normalized
    installerInvoked = $true
    installerExitCode = 0
    userDataImpact = "User data was not written directly by this Skill. The existing unified installer owns data separation and rollback."
    restartRequired = $true
    nextStep = "Restart Codex and create a new task."
} | ConvertTo-Json -Depth 6
