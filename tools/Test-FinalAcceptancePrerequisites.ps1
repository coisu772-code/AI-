[CmdletBinding()]
param(
    [string]$ReleaseCandidateZip,
    [string]$WorkshopExecutable,
    [string]$PublisherCenterExecutable,
    [string]$PublisherReadOnlyCli,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$checklistPath = Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json"
$checklist = Get-Content -LiteralPath $checklistPath -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedWorkshop = "2c168cf5e1a886427fc564fc0d381d7a0915786a6d6ad10dec04131bb9d786a4"
$expectedPublisher = "a81ce665c4d7c7bb97e46760cdde5606e90982a692a901d552165125f3af86f9"
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $root)
if ([string]::IsNullOrWhiteSpace($WorkshopExecutable)) {
    $WorkshopExecutable = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot "apps") -Filter *.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedWorkshop } |
        Select-Object -First 1 -ExpandProperty FullName
}
$publisherParents = @(Get-ChildItem -Path "E:\YouTube*" -Directory -ErrorAction SilentlyContinue)
if ([string]::IsNullOrWhiteSpace($PublisherCenterExecutable)) {
    $PublisherCenterExecutable = $publisherParents | ForEach-Object {
        Get-ChildItem -LiteralPath (Join-Path $_.FullName "youtube-publisher-center\build\bin") -Filter *.exe -File -ErrorAction SilentlyContinue
    } | Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedPublisher } |
        Select-Object -First 1 -ExpandProperty FullName
}
if ([string]::IsNullOrWhiteSpace($PublisherReadOnlyCli)) {
    $PublisherReadOnlyCli = $publisherParents | ForEach-Object {
        Get-ChildItem -LiteralPath (Join-Path $_.FullName "youtube-publisher-center\build\bin") -Filter "youtube-publisher-channel-list.exe" -File -ErrorAction SilentlyContinue
    } | Select-Object -First 1 -ExpandProperty FullName
}

function Get-ArtifactCheck([string]$PathValue, [string]$ExpectedHash) {
    $exists = -not [string]::IsNullOrWhiteSpace($PathValue) -and (Test-Path -LiteralPath $PathValue -PathType Leaf)
    $actual = if ($exists) { (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
    return [ordered]@{
        path = $PathValue
        exists = $exists
        expectedSha256 = if ([string]::IsNullOrWhiteSpace($ExpectedHash)) { $null } else { $ExpectedHash }
        actualSha256 = $actual
        unchanged = $exists -and ([string]::IsNullOrWhiteSpace($ExpectedHash) -or $actual -eq $ExpectedHash)
        executed = $false
    }
}

$rcCheck = if ([string]::IsNullOrWhiteSpace($ReleaseCandidateZip)) {
    [ordered]@{ path = $null; exists = $false; sha256 = $null; status = "WAITING_FOR_RC_PATH" }
}
else {
    $rcFull = [System.IO.Path]::GetFullPath($ReleaseCandidateZip)
    [ordered]@{
        path = $rcFull
        exists = Test-Path -LiteralPath $rcFull -PathType Leaf
        sha256 = if (Test-Path -LiteralPath $rcFull -PathType Leaf) { (Get-FileHash -LiteralPath $rcFull -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
        status = if (Test-Path -LiteralPath $rcFull -PathType Leaf) { "GO" } else { "WAITING_FOR_RC_PATH" }
    }
}
$workshop = Get-ArtifactCheck $WorkshopExecutable $expectedWorkshop
$publisher = Get-ArtifactCheck $PublisherCenterExecutable $expectedPublisher
$publisherCli = Get-ArtifactCheck $PublisherReadOnlyCli ""
$gates = @($checklist.gates | ForEach-Object {
    $statusProperty = $_.PSObject.Properties["status"]
    $gateStatus = if ($null -ne $statusProperty) {
        [string]$statusProperty.Value
    }
    elseif ([bool]$_.executed) {
        "LOCAL_EVIDENCE_COMPLETE"
    }
    else {
        "WAITING_FOR_APPROVAL"
    }
    [ordered]@{ id = $_.id; status = $gateStatus; approved = $false; executed = [bool]$_.executed }
})
$artifactsReady = [bool]$workshop.unchanged -and [bool]$publisher.unchanged -and [bool]$publisherCli.unchanged
$result = [ordered]@{
    schemaVersion = "1.0.0"
    productVersion = "0.8.0-rc.2"
    status = if ($artifactsReady -and [bool]$rcCheck.exists) { "READY_FOR_USER_AUTHORIZATION" } else { "WAITING_FOR_PREREQUISITES" }
    readOnlyPreflight = $true
    externalActionExecuted = $false
    releaseCandidate = $rcCheck
    formalArtifacts = [ordered]@{ workshop = $workshop; publisherCenter = $publisher; publisherReadOnlyCli = $publisherCli }
    approvalGates = $gates
    nextAction = "Obtain explicit approval for combinedGateId=final-mvp-live-acceptance-v1, then follow the live acceptance runbook. This preflight does not grant approval."
}
if ($AsJson) { $result | ConvertTo-Json -Depth 8 } else { $result }
