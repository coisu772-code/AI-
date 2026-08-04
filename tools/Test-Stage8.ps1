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
    $officialPluginValidator = Join-Path $env:USERPROFILE ".codex\skills\.system\plugin-creator\scripts\validate_plugin.py"
    if (-not (Test-Path -LiteralPath $officialPluginValidator -PathType Leaf)) { throw "Bundled official plugin validator is unavailable." }
    & $uv.Source run python $officialPluginValidator (Join-Path $root "plugins\ai-video-channel-production")
    if ($LASTEXITCODE -ne 0) { throw "Bundled official plugin validator failed." }
    & $uv.Source run python tools\validate_plugin.py
    if ($LASTEXITCODE -ne 0) { throw "Official-structure plugin/repository marketplace validation failed." }
    & $uv.Source run python tools\validate_release_manifest.py
    if ($LASTEXITCODE -ne 0) { throw "Committed unified manifest validation failed." }
    & $uv.Source run python tools\run_unittest_suite.py --output (Join-Path $evidence "unit-test-summary.json")
    if ($LASTEXITCODE -ne 0) { throw "Full unit test suite failed." }
    & $uv.Source run python tools\validate_unified_release.py --manifest (Join-Path $assets "unified-release-v0.8.0-rc.2.json") --asset-root $assets --report (Join-Path $evidence "unified-release-scan.json")
    if ($LASTEXITCODE -ne 0) { throw "Unified asset security validation failed." }
    & $uv.Source run python tools\validate_mcp_utf8_stdin_package.py --manifest (Join-Path $assets "unified-release-v0.8.0-rc.2.json") --asset-root $assets --report (Join-Path $evidence "mcp-utf8-stdin-validation.json")
    if ($LASTEXITCODE -ne 0) { throw "Packaged Windows PowerShell MCP no-BOM UTF-8 stdin validation failed." }
    & (Join-Path $root "tools\Invoke-Stage8Lifecycle.ps1") -AssetRoot $assets -EvidenceRoot (Join-Path $evidence "installation-lifecycle")
    if (-not $?) { throw "Isolated installation lifecycle failed." }
    $shortE2eRoot = "C:\AIVCP-S8-E2E-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    & $uv.Source run python (Join-Path $root "tools\generate_stage8_fixture_outputs.py") --output $shortE2eRoot
    if ($LASTEXITCODE -ne 0) { throw "Three-market synthetic workflow validation failed." }
    & $uv.Source run python (Join-Path $root "tools\validate_publisher_relock.py") --publisher-zip (Join-Path $assets "youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip") --stage8-output $shortE2eRoot --report (Join-Path $evidence "publisher-relock-validation.json")
    if ($LASTEXITCODE -ne 0) { throw "Final publisher Stage6 catalog re-lock validation failed." }
    Copy-Item -LiteralPath (Join-Path $shortE2eRoot "summary.json") -Destination (Join-Path $evidence "three-market-summary.json")
    $shortE2eFull = [System.IO.Path]::GetFullPath($shortE2eRoot)
    if (-not $shortE2eFull.StartsWith("C:\AIVCP-S8-E2E-", [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unexpected synthetic evidence cleanup root." }
    Remove-Item -LiteralPath $shortE2eFull -Recurse -Force
    $approval = Get-Content -LiteralPath (Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $binding = $approval.gates | Where-Object { [string]$_.id -eq "implementation-source-binding" } | Select-Object -First 1
    if ($null -eq $binding -or -not [bool]$binding.executed -or [string]$binding.classification -ne "local-evidence" -or [string]$binding.evidence.implementationSourceCommitSha -ne "511954e008e097bccb679ba53b3455aed35554cf") {
        throw "Completed implementation/source binding evidence is missing or inconsistent."
    }
    if (@($approval.gates | Where-Object { [string]$_.classification -eq "external-approval" -and [bool]$_.executed }).Count -ne 0) { throw "An external approval gate was incorrectly marked executed." }
    $summary = [ordered]@{
        schemaVersion="1.0.0"; productVersion="0.8.0-rc.2"; status="LOCAL_UNIFIED_RC_PASS"; fullMvpStatus="WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE"
        unitSuite="PASS"; officialPluginValidator="PASS"; repositoryMarketplaceValidator="PASS"; codexCliSmoke="NOT_RUN_REQUIRES_EXECUTABLE_CLI_OR_APP_RESTART"
        unifiedAssetScan="PASS"; winPs51McpUtf8Stdin="PASS"; sandboxAttempt5="FAIL_FIX_REQUIRES_CONTROLLED_RERUN"
        lifecycle="PASS"; threeMarketSynthetic="PASS"; publisherStage6Relock="PASS"; stalePublisherCatalogRejected="CONSTRAINTS_CATALOG_MISMATCH"
        implementationSourceBinding="PASS"; implementationSourceCommit="511954e008e097bccb679ba53b3455aed35554cf"; externalActionsExecuted=$false; approvalChecklist=(Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json")
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence "stage8-summary.json") -Encoding UTF8
    & $uv.Source run python tools\validate_release_json_parsers.py --asset-root $assets --evidence-root $evidence --report (Join-Path $evidence "json-parser-validation.json")
    if ($LASTEXITCODE -ne 0) { throw "PowerShell/Python/Node JSON parser validation failed." }
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    Pop-Location
}
Write-Output "Stage8C local unified RC validation PASS: $evidence"
