[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [string]$Tag = "v0.11.0-rc.1",
    [switch]$Execute,
    [string]$ApprovalFile
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$assetFull = [System.IO.Path]::GetFullPath($AssetRoot)
$manifestPath = Join-Path $assetFull "unified-release-v0.11.0-rc.1.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-ExistingGitHubCredential {
    $credentialLines = @("protocol=https", "host=github.com", "") | & git credential fill
    if ($LASTEXITCODE -ne 0) { throw "Existing GitHub credential could not be read from Git Credential Manager." }
    $credential = @{}
    foreach ($line in @($credentialLines)) {
        $separator = ([string]$line).IndexOf("=")
        if ($separator -gt 0) {
            $credential[([string]$line).Substring(0, $separator)] = ([string]$line).Substring($separator + 1)
        }
    }
    if (-not $credential.ContainsKey("password") -or [string]::IsNullOrWhiteSpace([string]$credential.password)) {
        throw "Existing GitHub credential is unavailable. This publisher never starts an interactive browser login."
    }
    return $credential
}

function New-GitHubHeaders {
    param([Parameter(Mandatory = $true)][string]$Token)
    return @{
        Authorization = "Bearer $Token"
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent" = "AIVCP-Release-Center"
    }
}

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("Get", "Post")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        $Body
    )
    $parameters = @{ Method = $Method; Uri = $Uri; Headers = $Headers }
    if ($null -ne $Body) {
        Add-Type -AssemblyName System.Web.Extensions
        $serializableBody = [System.Collections.Generic.Dictionary[string,object]]::new()
        foreach ($key in $Body.Keys) {
            $serializableBody.Add([string]$key, $Body[$key])
        }
        $serializer = [System.Web.Script.Serialization.JavaScriptSerializer]::new()
        $serializer.MaxJsonLength = [int]::MaxValue
        $parameters.Body = $serializer.Serialize($serializableBody)
        $parameters.ContentType = "application/json; charset=utf-8"
    }
    return Invoke-RestMethod @parameters
}

function Get-GitHubReleaseByTag {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$ReleaseTag,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )
    $encodedTag = [System.Uri]::EscapeDataString($ReleaseTag)
    try {
        return Invoke-GitHubJson -Method Get -Uri "https://api.github.com/repos/$Repository/releases/tags/$encodedTag" -Headers $Headers
    }
    catch {
        $response = $_.Exception.Response
        if ($null -ne $response -and [int]$response.StatusCode -eq 404) { return $null }
        throw
    }
}

function Send-GitHubReleaseAsset {
    param(
        [Parameter(Mandatory = $true)][string]$UploadUrl,
        [Parameter(Mandatory = $true)][string]$PathValue,
        [Parameter(Mandatory = $true)][string]$Token
    )
    Add-Type -AssemblyName System.Net.Http
    $templateIndex = $UploadUrl.IndexOf("{")
    $baseUrl = if ($templateIndex -ge 0) { $UploadUrl.Substring(0, $templateIndex) } else { $UploadUrl }
    $file = Get-Item -LiteralPath $PathValue
    $targetUrl = "$baseUrl`?name=$([System.Uri]::EscapeDataString($file.Name))"
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [System.Threading.Timeout]::InfiniteTimeSpan
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    $client.DefaultRequestHeaders.Accept.Add([System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new("application/vnd.github+json"))
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("AIVCP-Release-Center")
    $client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28")
    $stream = $null
    $content = $null
    $request = $null
    $response = $null
    try {
        $stream = [System.IO.File]::Open($file.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        $content = [System.Net.Http.StreamContent]::new($stream, 1048576)
        $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new("application/octet-stream")
        $content.Headers.ContentLength = $file.Length
        $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $targetUrl)
        $request.Content = $content
        $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "GitHub rejected release asset $($file.Name) with HTTP $([int]$response.StatusCode): $responseText"
        }
        return $responseText | ConvertFrom-Json
    }
    finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $request) { $request.Dispose() }
        elseif ($null -ne $content) { $content.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
        $client.Dispose()
    }
}

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
$runtimePackages = @($manifest.optionalRuntimePackages)
$runtimeVariants = @($runtimePackages | ForEach-Object { [string]$_.variant } | Sort-Object -Unique)
if ($runtimePackages.Count -ne 3 -or $runtimeVariants.Count -ne 3 -or @($runtimeVariants | Where-Object { $_ -notin @("cpu", "nvidia", "nvidia-blackwell") }).Count -ne 0) {
    throw "The release must contain exactly the CPU, NVIDIA, and NVIDIA Blackwell Kokoro runtime packages."
}
$optionalReleaseFiles = New-Object System.Collections.Generic.List[string]
$reusedRuntimePackages = New-Object System.Collections.Generic.List[object]
foreach ($package in $runtimePackages) {
    $releaseTagProperty = $package.source.PSObject.Properties["releaseTag"]
    $sourceReleaseTag = if ($null -eq $releaseTagProperty) { "" } else { [string]$releaseTagProperty.Value }
    if (-not [string]::IsNullOrWhiteSpace($sourceReleaseTag)) {
        if ([string]$package.source.repository -ne "coisu772-code/AI-" -or $sourceReleaseTag -eq $Tag) {
            throw "Reused optional runtime provenance is invalid: $($package.variant)"
        }
        $reusedRuntimePackages.Add($package)
        continue
    }
    $records = @($package.manifest) + @($package.parts)
    foreach ($record in $records) {
        $path = Join-Path $assetFull ([string]$record.fileName)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing optional runtime attachment: $($record.fileName)" }
        if ((Get-Item -LiteralPath $path).Length -ne [int64]$record.sizeBytes) { throw "Size mismatch: $($record.fileName)" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$record.sha256) { throw "Hash mismatch: $($record.fileName)" }
        $optionalReleaseFiles.Add($path)
    }
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
$tagCommit = (& git -C $repositoryRoot rev-list -n 1 $Tag).Trim()
if ($LASTEXITCODE -ne 0 -or $tagCommit -ne $boundSourceCommit) { throw "The approved tag does not resolve to the bound implementation/source commit; this script will not create or push tags." }
$remoteTagRecords = @(& git -C $repositoryRoot ls-remote origin "refs/tags/$Tag" "refs/tags/$Tag^{}")
if ($LASTEXITCODE -ne 0 -or @($remoteTagRecords | Where-Object { ([string]$_).Split("`t")[0] -eq $boundSourceCommit }).Count -ne 1) {
    throw "The approved tag is not present on origin at the bound implementation/source commit; this script will not create or push tags."
}
$releaseFiles = New-Object System.Collections.Generic.List[string]
foreach ($asset in @($manifest.assets)) { $releaseFiles.Add((Join-Path $assetFull ([string]$asset.fileName))) }
$releaseFiles.AddRange($optionalReleaseFiles)
foreach ($metadataName in @("unified-release-v0.11.0-rc.1.json", "SHA256SUMS.txt")) {
    $metadataPath = Join-Path $assetFull $metadataName
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) { $releaseFiles.Add($metadataPath) }
}
$repository = "coisu772-code/AI-"
$credential = Get-ExistingGitHubCredential
$token = [string]$credential.password
$headers = New-GitHubHeaders -Token $token
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    $repositoryRecord = Invoke-GitHubJson -Method Get -Uri "https://api.github.com/repos/$repository" -Headers $headers
    if ([string]$repositoryRecord.full_name -ne $repository -or -not [bool]$repositoryRecord.permissions.push) {
        throw "The existing GitHub credential does not have push permission for $repository."
    }
    foreach ($package in $reusedRuntimePackages) {
        $sourceRelease = Get-GitHubReleaseByTag -Repository ([string]$package.source.repository) -ReleaseTag ([string]$package.source.releaseTag) -Headers $headers
        if ($null -eq $sourceRelease -or [bool]$sourceRelease.draft -or -not [bool]$sourceRelease.prerelease) {
            throw "Reused optional runtime Release is missing or not a public prerelease: $($package.source.releaseTag)"
        }
        foreach ($record in @($package.manifest) + @($package.parts)) {
            $remote = @($sourceRelease.assets | Where-Object { [string]$_.name -eq [string]$record.fileName })
            $expectedDigest = "sha256:$([string]$record.sha256)"
            if ($remote.Count -ne 1 -or [int64]$remote[0].size -ne [int64]$record.sizeBytes -or [string]$remote[0].digest -ne $expectedDigest) {
                throw "Reused optional runtime asset failed remote digest verification: $($record.fileName)"
            }
            Write-Output "REUSED_REMOTE_VERIFY_PASS: $($record.fileName) from $($package.source.releaseTag)"
        }
    }
    $release = Get-GitHubReleaseByTag -Repository $repository -ReleaseTag $Tag -Headers $headers
    if ($null -eq $release) {
        $notesPath = Join-Path $repositoryRoot "docs\release-notes-v0.11.0-rc.1.md"
        $release = Invoke-GitHubJson -Method Post -Uri "https://api.github.com/repos/$repository/releases" -Headers $headers -Body @{
            tag_name = $Tag
            target_commitish = $boundSourceCommit
            name = "AI Video Channel Production $Tag"
            body = Get-Content -LiteralPath $notesPath -Raw -Encoding UTF8
            draft = $false
            prerelease = $true
            make_latest = "false"
        }
    }
    if ([string]$release.tag_name -ne $Tag -or [bool]$release.draft -or -not [bool]$release.prerelease) {
        throw "GitHub returned a Release whose tag or prerelease state does not match the approval."
    }
    foreach ($path in @($releaseFiles | Sort-Object -Unique)) {
        $file = Get-Item -LiteralPath $path
        $localDigest = "sha256:$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
        $existing = @($release.assets | Where-Object { [string]$_.name -eq $file.Name })
        if ($existing.Count -gt 1) { throw "GitHub Release contains duplicate asset names: $($file.Name)" }
        if ($existing.Count -eq 1) {
            if ([int64]$existing[0].size -ne $file.Length -or [string]$existing[0].digest -ne $localDigest) {
                throw "Existing GitHub Release asset does not match the approved local file: $($file.Name)"
            }
            Write-Output "UPLOAD_SKIP_VERIFIED: $($file.Name)"
            continue
        }
        Write-Output "UPLOAD_START: $($file.Name) ($($file.Length) bytes)"
        Send-GitHubReleaseAsset -UploadUrl ([string]$release.upload_url) -PathValue $file.FullName -Token $token | Out-Null
        Write-Output "UPLOAD_PASS: $($file.Name)"
        $release = Get-GitHubReleaseByTag -Repository $repository -ReleaseTag $Tag -Headers $headers
    }
    $release = Get-GitHubReleaseByTag -Repository $repository -ReleaseTag $Tag -Headers $headers
    foreach ($path in @($releaseFiles | Sort-Object -Unique)) {
        $file = Get-Item -LiteralPath $path
        $expectedDigest = "sha256:$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
        $remote = @($release.assets | Where-Object { [string]$_.name -eq $file.Name })
        if ($remote.Count -ne 1 -or [int64]$remote[0].size -ne $file.Length -or [string]$remote[0].digest -ne $expectedDigest) {
            throw "Remote GitHub Release verification failed: $($file.Name)"
        }
        Write-Output "REMOTE_VERIFY_PASS: $($file.Name)"
    }
    Write-Output "GITHUB_RELEASE_PASS: existing Git credential reused; no browser login was started."
}
finally {
    $token = $null
    $credential = $null
}
