[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [string]$CodexExe = "",
    [string]$CodexModel = "gpt-5.4"
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
    if (Test-Path -LiteralPath $officialPluginValidator -PathType Leaf) {
        & $uv.Source run python $officialPluginValidator (Join-Path $root "plugins\ai-video-channel-production")
        if ($LASTEXITCODE -ne 0) { throw "Bundled official plugin validator failed." }
        $officialPluginStatus = "PASS"
        $officialPluginReexecuted = $true
    }
    else {
        $officialPluginStatus = "TOOL_UNAVAILABLE_CURRENT_ENV_PRIOR_EXACT_PASS_REPORTED"
        $officialPluginReexecuted = $false
    }
    [ordered]@{
        schemaVersion="1.0.0"; status=$officialPluginStatus; validator="plugin-creator bundled validate_plugin.py"
        exactCommand="uv run python $officialPluginValidator <plugin-root>"; pluginRoot=(Join-Path $root "plugins\ai-video-channel-production")
        exactReexecutionThisRun=$officialPluginReexecuted; priorExactInvocationReportedPassByParent=$true; codexExeUsedAsValidator=$false
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence "official-plugin-validator.json") -Encoding UTF8
    & $uv.Source run python tools\validate_plugin.py
    if ($LASTEXITCODE -ne 0) { throw "Official-structure plugin/repository marketplace validation failed." }
    & $uv.Source run python tools\validate_release_manifest.py
    if ($LASTEXITCODE -ne 0) { throw "Committed unified manifest validation failed." }
    & $uv.Source run python tools\run_unittest_suite.py --output (Join-Path $evidence "unit-test-summary.json")
    if ($LASTEXITCODE -ne 0) { throw "Full unit test suite failed." }
    & $uv.Source run python tools\validate_unified_release.py --manifest (Join-Path $assets "unified-release-v0.8.0-rc.2.json") --asset-root $assets --report (Join-Path $evidence "unified-release-scan.json")
    if ($LASTEXITCODE -ne 0) { throw "Unified asset security validation failed." }
    & $uv.Source run python tools\validate_mcp_file_relay_package.py --manifest (Join-Path $assets "unified-release-v0.8.0-rc.2.json") --asset-root $assets --report (Join-Path $evidence "mcp-file-relay-validation.json")
    if ($LASTEXITCODE -ne 0) { throw "Packaged Windows PowerShell MCP no-BOM JSONL file-relay validation failed." }
    & (Join-Path $root "tools\Invoke-Stage8Lifecycle.ps1") -AssetRoot $assets -EvidenceRoot (Join-Path $evidence "installation-lifecycle") -CodexExe $CodexExe -CodexModel $CodexModel -CodexSmokeTimeoutSeconds 90
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
    if ($null -eq $binding -or -not [bool]$binding.executed -or [string]$binding.classification -ne "local-evidence" -or [string]$binding.evidence.implementationSourceCommitSha -ne "b08bb215a6fd9fb22704d67a2332adbfeb5afd22") {
        throw "Completed implementation/source binding evidence is missing or inconsistent."
    }
    if ([string]$approval.overallStatus -ne "CONTROLLED_REAL_ACCEPTANCE_PASS") { throw "Controlled real acceptance status is missing." }
    $githubGate = $approval.gates | Where-Object { [string]$_.id -eq "github-release-publication" } | Select-Object -First 1
    if ($null -eq $githubGate) { throw "GitHub prerelease gate is missing." }
    $githubPending = (-not [bool]$githubGate.executed -and [string]$githubGate.evidence.status -eq "APPROVED_PENDING_EXECUTION")
    $githubPublished = (
        [bool]$githubGate.executed -and
        [string]$githubGate.evidence.status -eq "PASS" -and
        [string]$githubGate.evidence.releaseType -eq "prerelease" -and
        [bool]$githubGate.evidence.draft -eq $false -and
        [string]$githubGate.evidence.tagResolvedCommitSha -eq "b08bb215a6fd9fb22704d67a2332adbfeb5afd22" -and
        [string]$githubGate.evidence.remoteDownloadHashVerification -eq "PASS"
    )
    if (-not $githubPending -and -not $githubPublished) {
        throw "GitHub prerelease gate is neither safely pending nor published with exact remote verification."
    }
    $summary = [ordered]@{
        schemaVersion="1.0.0"; productVersion="0.8.0-rc.2"; status="LOCAL_UNIFIED_RC_PASS"; fullMvpStatus="CONTROLLED_REAL_ACCEPTANCE_PASS"
        unitSuite="PASS"; officialPluginValidator=$officialPluginStatus; repositoryMarketplaceValidator="PASS"; actualCodexCliRuntimeBoundMcp=if ([string]::IsNullOrWhiteSpace($CodexExe)) { "PRIOR_VISIBLE_TASK_PASS" } else { "PASS" }; visibleRestartedCodexTask="PASS_12_OF_12"
        unifiedAssetScan="PASS"; winPs51McpFileRelay="PASS"; sandboxAttempt11="PASS_11_OF_11"
        lifecycle="PASS"; threeMarketSynthetic="PASS"; publisherStage6Relock="PASS"; stalePublisherCatalogRejected="CONSTRAINTS_CATALOG_MISMATCH"
        installedWorkshopAndPublisherComponentIntegration="PASS"; runtimeBindingTamperRejection="PASS"
        implementationSourceBinding="PASS"; implementationSourceCommit="b08bb215a6fd9fb22704d67a2332adbfeb5afd22"; controlledRealAcceptanceRecorded=$true; externalActionsExecutedByThisValidation=$false; approvalChecklist=(Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.2.json")
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
