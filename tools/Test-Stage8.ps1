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
$uv = Get-Command uv -ErrorAction Stop
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
Push-Location $root
try {
    $env:PYTHONUTF8 = "1"; $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Locked dependency synchronization failed." }
    & $uv.Source run python tools\validate_plugin.py
    if ($LASTEXITCODE -ne 0) { throw "Official-structure plugin/repository marketplace validation failed." }
    & $uv.Source run python tools\validate_release_manifest.py
    if ($LASTEXITCODE -ne 0) { throw "Committed unified manifest validation failed." }
    & $uv.Source run python -m unittest discover -s tests -p "test_*.py" -q
    if ($LASTEXITCODE -ne 0) { throw "Full unit test suite failed." }
    & $uv.Source run python tools\validate_unified_release.py --manifest (Join-Path $assets "unified-release-v0.8.0-rc.2.json") --asset-root $assets --report (Join-Path $evidence "unified-release-scan.json")
    if ($LASTEXITCODE -ne 0) { throw "Unified asset security validation failed." }
    & (Join-Path $root "tools\Invoke-Stage8Lifecycle.ps1") -AssetRoot $assets -EvidenceRoot (Join-Path $evidence "installation-lifecycle")
    if (-not $?) { throw "Isolated installation lifecycle failed." }
    $shortE2eRoot = "C:\AIVCP-S8-E2E-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    & $uv.Source run python (Join-Path $root "tools\generate_stage8_fixture_outputs.py") --output $shortE2eRoot
    if ($LASTEXITCODE -ne 0) { throw "Three-market synthetic workflow validation failed." }
    Copy-Item -LiteralPath (Join-Path $shortE2eRoot "summary.json") -Destination (Join-Path $evidence "three-market-summary.json")
    $shortE2eFull = [System.IO.Path]::GetFullPath($shortE2eRoot)
    if (-not $shortE2eFull.StartsWith("C:\AIVCP-S8-E2E-", [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unexpected synthetic evidence cleanup root." }
    Remove-Item -LiteralPath $shortE2eFull -Recurse -Force
    $approval = Get-Content -LiteralPath (Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $binding = $approval.gates | Where-Object { [string]$_.id -eq "implementation-source-binding" } | Select-Object -First 1
    if ($null -eq $binding -or -not [bool]$binding.executed -or [string]$binding.classification -ne "local-evidence" -or [string]$binding.evidence.implementationSourceCommitSha -ne "7a6bfa9f438a72e1f613f5b32b5f8d551be563e5") {
        throw "Completed implementation/source binding evidence is missing or inconsistent."
    }
    if (@($approval.gates | Where-Object { [string]$_.classification -eq "external-approval" -and [bool]$_.executed }).Count -ne 0) { throw "An external approval gate was incorrectly marked executed." }
    $summary = [ordered]@{
        schemaVersion="1.0.0"; productVersion="0.8.0-rc.2"; status="LOCAL_UNIFIED_RC_PASS"; fullMvpStatus="WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE"
        unitSuite="PASS"; pluginValidation="PASS"; unifiedAssetScan="PASS"; lifecycle="PASS"; threeMarketSynthetic="PASS"
        implementationSourceBinding="PASS"; implementationSourceCommit="7a6bfa9f438a72e1f613f5b32b5f8d551be563e5"; externalActionsExecuted=$false; approvalChecklist=(Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json")
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence "stage8-summary.json") -Encoding UTF8
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    Pop-Location
}
Write-Output "Stage8C local unified RC validation PASS: $evidence"
