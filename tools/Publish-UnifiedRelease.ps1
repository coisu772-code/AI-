[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [string]$Tag = "v0.8.0-rc.2",
    [switch]$Execute,
    [string]$ApprovalFile
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$assetFull = [System.IO.Path]::GetFullPath($AssetRoot)
$manifestPath = Join-Path $assetFull "unified-release-v0.8.0-rc.2.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8).Contains("LOCAL_COMMIT_TO_BE_RECORDED")) { throw "Release manifest still contains an unbound source commit placeholder." }
$boundSourceCommits = @(
    $manifest.assets |
        Where-Object { [string]$_.assetId -in @("unified-installer", "core") } |
        ForEach-Object { [string]$_.source.commit } |
        Sort-Object -Unique
)
if ($boundSourceCommits.Count -ne 1 -or $boundSourceCommits[0] -notmatch '^[0-9a-f]{40}$') { throw "Installer and core are not bound to one exact implementation/source commit." }
$boundSourceCommit = $boundSourceCommits[0]
foreach ($asset in @($manifest.assets)) {
    $path = Join-Path $assetFull ([string]$asset.fileName)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing release asset: $($asset.fileName)" }
    if ((Get-Item -LiteralPath $path).Length -ne [int64]$asset.sizeBytes) { throw "Size mismatch: $($asset.fileName)" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$asset.sha256) { throw "Hash mismatch: $($asset.fileName)" }
}
if (@($manifest.publicationGates | Where-Object { $_ -eq "release-license-owner-approval" }).Count -ne 1) { throw "External release-owner license approval gate is missing." }
if (-not $Execute) {
    Write-Output "DRY_RUN_PASS: all locked assets are present and verified. No tag, push, or GitHub Release action was executed."
    exit 0
}
if ([string]::IsNullOrWhiteSpace($ApprovalFile) -or -not (Test-Path -LiteralPath $ApprovalFile -PathType Leaf)) { throw "Execution requires a main-thread-approved machine-readable approval file." }
$approval = Get-Content -LiteralPath $ApprovalFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$approval.tag -ne $Tag -or
    [bool]$approval.githubReleaseApproved -ne $true -or
    [bool]$approval.releaseLicenseOwnerApproved -ne $true -or
    [bool]$approval.cleanWindowsApproved -ne $true -or
    [bool]$approval.codeSigningApproved -ne $true -or
    [string]$approval.implementationSourceCommitSha -ne $boundSourceCommit -or
    [string]$approval.manifestSha256 -ne (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
) {
    throw "Approval file does not authorize this exact tag and manifest."
}
$gh = Get-Command gh -ErrorAction Stop
$tagCommit = (& git -C $repositoryRoot rev-list -n 1 $Tag).Trim()
if ($LASTEXITCODE -ne 0 -or $tagCommit -ne $boundSourceCommit) { throw "The approved tag does not resolve to the bound implementation/source commit; this script will not create or push tags." }
$releaseFiles = New-Object System.Collections.Generic.List[string]
foreach ($asset in @($manifest.assets)) { $releaseFiles.Add((Join-Path $assetFull ([string]$asset.fileName))) }
foreach ($metadataName in @("unified-release-v0.8.0-rc.2.json", "SHA256SUMS.txt")) {
    $metadataPath = Join-Path $assetFull $metadataName
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) { $releaseFiles.Add($metadataPath) }
}
& $gh.Source release create $Tag @releaseFiles --verify-tag --prerelease --latest=false --title "AI Video Channel Production $Tag" --notes-file (Join-Path $repositoryRoot "docs\release-notes-v0.8.0-rc.2.md")
if ($LASTEXITCODE -ne 0) { throw "GitHub Release creation failed. No push or tag creation was attempted." }
