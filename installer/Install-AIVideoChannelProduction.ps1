[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [switch]$SkipCodexRegistration,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "CodexCli.ps1")

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}

$productId = "ai-video-channel-production"
$marketplaceName = "novel-manga-production"

function Get-FullPath([string]$PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Get-RelativePath([string]$RootPath, [string]$FilePath) {
    $rootWithSlash = $RootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $rootUri = [System.Uri]::new($rootWithSlash)
    $fileUri = [System.Uri]::new($FilePath)
    return [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString())
}

function Get-TreeHash([string]$RootPath) {
    $rootFull = Get-FullPath $RootPath
    $lines = New-Object System.Collections.Generic.List[string]
    $relativePaths = New-Object System.Collections.Generic.List[string]
    $filesByRelativePath = [System.Collections.Generic.Dictionary[string,System.IO.FileInfo]]::new([System.StringComparer]::Ordinal)
    Get-ChildItem -LiteralPath $rootFull -File -Recurse | ForEach-Object {
        $relative = Get-RelativePath $rootFull $_.FullName
        $relativePaths.Add($relative)
        $filesByRelativePath.Add($relative, $_)
    }
    $relativePaths.Sort([System.StringComparer]::Ordinal)
    foreach ($relative in $relativePaths) {
        $file = $filesByRelativePath[$relative]
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines.Add("$relative`t$($file.Length)`t$hash`n")
    }
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($lines -join ""))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

$sourceFull = Get-FullPath $SourceRoot
$installFull = Get-FullPath $InstallRoot
$alreadyInstalled = $false
$createdBackupPath = $null
$pluginManifestPath = Join-Path $sourceFull "plugins\$productId\.codex-plugin\plugin.json"
$marketplacePath = Join-Path $sourceFull ".agents\plugins\marketplace.json"
$releaseManifestPath = Join-Path $sourceFull "release-manifests\release-v0.1.0-beta.1.json"

if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) {
    throw "Plugin manifest not found: $pluginManifestPath"
}
if (-not (Test-Path -LiteralPath $marketplacePath -PathType Leaf)) {
    throw "Marketplace manifest not found: $marketplacePath"
}
if (-not (Test-Path -LiteralPath $releaseManifestPath -PathType Leaf)) {
    throw "Release manifest not found: $releaseManifestPath"
}

$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$marketplace = Get-Content -LiteralPath $marketplacePath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseManifest = Get-Content -LiteralPath $releaseManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$pluginManifest.name -ne $productId) {
    throw "Unexpected plugin name: $($pluginManifest.name)"
}
if ([string]$marketplace.name -ne $marketplaceName) {
    throw "Unexpected marketplace name: $($marketplace.name)"
}
if ([string]$releaseManifest.productVersion -ne [string]$pluginManifest.version) {
    throw "Release manifest and plugin versions do not match."
}

$payloadItems = @(".agents", "plugins", "contracts", "installer", "release-manifests", "docs", "README.md", "LICENSE.md")
foreach ($item in $payloadItems) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceFull $item))) {
        throw "Installation payload is incomplete: $item"
    }
}

foreach ($componentId in @("codex-plugin", "windows-installer", "cross-center-contracts")) {
    $component = $releaseManifest.components | Where-Object { $_.componentId -eq $componentId } | Select-Object -First 1
    if ($null -eq $component -or -not [bool]$component.includedInRelease -or $component.artifacts.Count -ne 1) {
        throw "Release manifest is missing one required stage 1 artifact: $componentId"
    }
    $artifact = $component.artifacts[0]
    if ([string]$artifact.kind -ne "directory-tree") {
        throw "Unsupported release artifact kind for $componentId"
    }
    $artifactPath = Get-FullPath (Join-Path $sourceFull ([string]$artifact.relativePath))
    $sourcePrefix = $sourceFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $artifactPath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release artifact escapes SourceRoot: $componentId"
    }
    $actualArtifactHash = Get-TreeHash $artifactPath
    if ($actualArtifactHash -ne [string]$artifact.sha256) {
        throw "Release artifact fingerprint mismatch: $componentId (expected $($artifact.sha256), got $actualArtifactHash)"
    }
}

New-Item -ItemType Directory -Path $installFull -Force | Out-Null
$currentPath = Join-Path $installFull "current"
$backupRoot = Join-Path $installFull "backups"
$stagingPath = Join-Path $installFull (".installing-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null

try {
    foreach ($item in $payloadItems) {
        Copy-Item -LiteralPath (Join-Path $sourceFull $item) -Destination $stagingPath -Recurse -Force
    }

    $sourceFingerprint = Get-TreeHash (Join-Path $sourceFull "plugins\$productId")
    $installedFingerprint = Get-TreeHash (Join-Path $stagingPath "plugins\$productId")
    if ($sourceFingerprint -ne $installedFingerprint) {
        throw "Installed plugin fingerprint does not match the source payload."
    }

    $state = [ordered]@{
        schemaVersion = "1.0.0"
        productId = $productId
        productVersion = [string]$pluginManifest.version
        marketplaceName = $marketplaceName
        releaseManifestContentHash = [string]$releaseManifest.contentHash
        pluginTreeSha256 = $installedFingerprint
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stagingPath "install-state.json") -Encoding UTF8

    if (Test-Path -LiteralPath $currentPath) {
        $existingStatePath = Join-Path $currentPath "install-state.json"
        $existingVersion = "unknown"
        if (Test-Path -LiteralPath $existingStatePath) {
            $existingState = Get-Content -LiteralPath $existingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $existingVersion = [string]$existingState.productVersion
            if (-not $Force -and [string]$existingState.pluginTreeSha256 -eq $installedFingerprint) {
                Remove-Item -LiteralPath $stagingPath -Recurse -Force
                Write-Output "Already installed: $productId $($pluginManifest.version)"
                $alreadyInstalled = $true
            }
        }
        if (-not $alreadyInstalled) {
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            $backupName = "v$existingVersion-" + (Get-Date -Format "yyyyMMdd-HHmmssfff")
            $createdBackupPath = Join-Path $backupRoot $backupName
            Move-Item -LiteralPath $currentPath -Destination $createdBackupPath
        }
    }

    if (-not $alreadyInstalled) {
        Move-Item -LiteralPath $stagingPath -Destination $currentPath
        [ordered]@{
            schemaVersion = "1.0.0"
            productId = $productId
            activeVersion = [string]$pluginManifest.version
            activeRoot = "current"
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installFull "installation.json") -Encoding UTF8
    }
}
catch {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
    if ($null -ne $createdBackupPath -and -not (Test-Path -LiteralPath $currentPath) -and (Test-Path -LiteralPath $createdBackupPath)) {
        Move-Item -LiteralPath $createdBackupPath -Destination $currentPath
    }
    throw
}

if (-not $SkipCodexRegistration) {
    $codex = Get-CompatibleCodexPluginCli
    if ($null -eq $codex) {
        throw "A Codex CLI with plugin install support was not found. Files were installed, but marketplace registration was not completed."
    }
    & $codex plugin marketplace add $currentPath
    if ($LASTEXITCODE -ne 0) {
        throw "Codex marketplace registration failed."
    }
    & $codex plugin add "$productId@$marketplaceName"
    if ($LASTEXITCODE -ne 0) {
        throw "Codex plugin installation failed."
    }
}

Write-Output "Installed $productId $($pluginManifest.version) to $currentPath"
Write-Output "Restart Codex and open a new task to load the plugin."
