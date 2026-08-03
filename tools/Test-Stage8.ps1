[CmdletBinding()]
param(
    [string]$EvidenceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $root)
if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) { $EvidenceRoot = Join-Path $workspaceRoot "runtime\s8\rc1" }
$evidence = [System.IO.Path]::GetFullPath($EvidenceRoot)
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for Stage8 validation." }
New-Item -ItemType Directory -Path $evidence -Force | Out-Null

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Stage8 dependency synchronization failed." }
    & $uv.Source run python -m unittest -q tests.test_stage8_release_candidate
    if ($LASTEXITCODE -ne 0) { throw "Stage8 unit tests failed." }

    $lifecycleRoot = Join-Path $evidence "installation-lifecycle"
    & (Join-Path $root "tools\Invoke-Stage8Lifecycle.ps1") -EvidenceRoot $lifecycleRoot | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage8 installation lifecycle failed." }

    $e2eRoot = Join-Path $evidence "three-market-e2e"
    if (Test-Path -LiteralPath $e2eRoot) { Remove-Item -LiteralPath $e2eRoot -Recurse -Force }
    & $uv.Source run python (Join-Path $root "tools\generate_stage8_fixture_outputs.py") --output $e2eRoot | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage8 three-market end-to-end fixture validation failed." }

    $buildA = Join-Path $evidence "rc-build-a"
    $buildB = Join-Path $evidence "rc-build-b"
    foreach ($build in @($buildA, $buildB)) {
        if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
        & $uv.Source run python (Join-Path $root "tools\build_release_candidate.py") --output $build | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Stage8 deterministic RC build failed." }
    }
    $zipName = "ai-video-channel-production-v0.8.0-rc.1-windows.zip"
    $zipA = Join-Path $buildA $zipName
    $zipB = Join-Path $buildB $zipName
    $hashA = (Get-FileHash -LiteralPath $zipA -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashB = (Get-FileHash -LiteralPath $zipB -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hashA -ne $hashB) { throw "Release candidate ZIP is not reproducible." }
    & $uv.Source run python (Join-Path $root "tools\scan_release_candidate.py") --archive $zipA | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage8 RC safety scan failed." }

    $approval = Get-Content -LiteralPath (Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.1.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($approval.gates | Where-Object { $_.executed -ne $false }).Count -ne 0) { throw "An external approval gate was incorrectly marked executed." }
    $summary = [ordered]@{
        schemaVersion = "1.0.0"
        productVersion = "0.8.0-rc.1"
        status = "LOCAL_RELEASE_CANDIDATE_GO"
        fullMvpStatus = "WAITING_FOR_AUTHORIZED_LIVE_ACCEPTANCE"
        lifecycleSummary = (Join-Path $lifecycleRoot "lifecycle-summary.json")
        threeMarketSummary = (Join-Path $e2eRoot "summary.json")
        releaseCandidate = [ordered]@{ path = $zipA; sha256 = $hashA; reproducible = $true; secondBuildPath = $zipB }
        approvalChecklist = (Join-Path $root "docs\final-acceptance-approval-checklist-v0.8.0-rc.1.json")
        externalActionsExecuted = $false
    }
    $summaryPath = Join-Path $evidence "stage8-summary.json"
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    Pop-Location
}
Write-Output "Stage8 local RC lifecycle, three-market E2E, reproducible ZIP, and approval gates passed."
