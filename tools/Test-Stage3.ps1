[CmdletBinding()]
param(
    [switch]$OnboardingOnly,
    [switch]$SourcePrepareOnly,
    [switch]$SourceConfirmOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$isolated = [System.IO.Path]::GetFullPath((Join-Path $root ".stage3-isolated"))
if (-not $isolated.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 3 test root."
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for isolated stage 3 validation." }

function Invoke-InstalledTool {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][hashtable]$Arguments,
        [Parameter(Mandatory = $true)][string]$Server,
        [Parameter(Mandatory = $true)][string]$Python
    )
    $requestJson = @{
        jsonrpc = "2.0"
        id = 1
        method = "tools/call"
        params = @{ name = $Name; arguments = $Arguments }
    } | ConvertTo-Json -Depth 24 -Compress
    $requestJson = [System.Text.RegularExpressions.Regex]::Replace(
        $requestJson,
        '[^\x00-\x7F]',
        [System.Text.RegularExpressions.MatchEvaluator]{
            param($match)
            return '\u' + ([int][char]$match.Value).ToString('x4')
        }
    )
    $startScript = Join-Path (Split-Path -Parent $Server) "start.ps1"
    $responseText = $requestJson | powershell -NoProfile -ExecutionPolicy Bypass -File $startScript | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Installed MCP transport failed for $Name. Output: $responseText" }
    $response = $responseText | ConvertFrom-Json
    $payload = $response.result.structuredContent
    if ($null -eq $payload -or -not $payload.ok) {
        $diagnostic = $payload | ConvertTo-Json -Depth 10 -Compress
        throw "Installed tool returned an error for $Name`: $diagnostic"
    }
    return $payload.result
}

Push-Location $root
try {
    if (Test-Path -LiteralPath $isolated) {
        Remove-Item -LiteralPath $isolated -Recurse -Force
    }
    New-Item -ItemType Directory -Path $isolated -Force | Out-Null
    $installRoot = Join-Path $isolated "install"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "installer\Install-AIVideoChannelProduction.ps1") -SourceRoot $root -InstallRoot $installRoot -SkipCodexRegistration
    if ($LASTEXITCODE -ne 0) { throw "Stage 3 candidate installation failed." }

    $installed = Join-Path $installRoot "current"
    $plugin = Join-Path $installed "plugins\ai-video-channel-production"
    $sourceSkill = Join-Path $plugin "skills\source-library\SKILL.md"
    $server = Join-Path $plugin "mcp\server.py"
    if (-not (Test-Path -LiteralPath $sourceSkill -PathType Leaf)) {
        throw "Installed source-library Skill is missing."
    }
    if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
        throw "Installed MCP server is missing."
    }

    $python = (& $uv.Source python find) | Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Project Python runtime could not be resolved."
    }

    $publisherFixture = Join-Path $isolated "publisher.json"
    $publisherJson = @{
        channels = @(@{
            publisherProfileId = "publisher_stage3_fixture"
            channelSerial = "01"
            youtubeChannelId = "UCSTAGE3FIXTURE00001"
            displayName = "Stage 3 Fixture Channel"
            enabled = $true
            authorizationStatus = "AUTHORIZED"
            defaultLanguage = "en-US"
            privacyStatus = "private"
            timeZone = "UTC"
            uploadPolicy = "REQUIRE_REVIEW"
        })
    } | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $publisherFixture,
        $publisherJson,
        (New-Object System.Text.UTF8Encoding($false))
    )

    $voiceFixture = Join-Path $isolated "voice-catalog.json"
    $voiceJson = @{
        schemaVersion = "1.0.0"
        generatedAt = "2026-08-04T00:00:00Z"
        engines = @(@{
            engineId = "fixture-tts"
            displayName = "Fixture TTS"
            installed = $true
            voices = @(@{
                voiceId = "fixture-multilingual-001"
                displayName = "Fixture Multilingual Voice"
                languages = @("ja-JP", "zh-CN", "en-US")
                recommended = $true
            })
        })
    } | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $voiceFixture,
        $voiceJson,
        (New-Object System.Text.UTF8Encoding($false))
    )

    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:AIVCP_DATA_ROOT = Join-Path $isolated "data"
    $env:AIVCP_ALLOW_TEST_FIXTURES = "1"
    $env:AIVCP_TEST_PUBLISHER_FIXTURE = $publisherFixture
    $env:AIVCP_VOICE_CATALOG = $voiceFixture
    $env:AIVCP_PYTHON = $python

    $listRequest = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
    $listResponseText = $listRequest | powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $plugin "mcp\start.ps1") | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Installed MCP tools/list failed." }
    $listResponse = $listResponseText | ConvertFrom-Json
    $toolNames = @($listResponse.result.tools | ForEach-Object { $_.name })
    foreach ($requiredTool in @("source_add_prepare", "source_add_confirm", "source_search", "source_get", "source_job_resume", "source_integrity_check")) {
        if ($toolNames -notcontains $requiredTool) { throw "Installed MCP tool is missing: $requiredTool" }
    }

    $taskId = "stage3-isolated-task"
    $started = Invoke-InstalledTool -Name "channel_onboarding_start" -Server $server -Python $python -Arguments @{
        taskId = $taskId
        channelSerial = "01"
        targetRegion = "Test"
        outputLanguage = "en-US"
    }
    if ($OnboardingOnly) {
        Write-Output "Targeted installed MCP onboarding call passed."
        return
    }
    $channelId = [string]$started.channel.channelProfileId
    $bindingProof = [string]$started.taskBinding.bindingProof
    $defaults = @{
        voice = @{ engineId = "fixture-tts"; voiceId = "fixture-multilingual-001" }
        manuscript = @{ mode = "auto_by_topic"; preferredCharacters = 12000; minCharacters = 8000; maxCharacters = 16000 }
        episodes = @{ mode = "auto_by_topic"; preferredCount = 8; minCount = 6; maxCount = 10 }
        deliveryMode = "auto_render"
        videoGeneration = @{ enabled = $false; selectionMode = "none"; fallbackPolicy = "pause" }
        uploadPolicy = "REQUIRE_REVIEW"
    }
    $null = Invoke-InstalledTool -Name "channel_onboarding_complete" -Server $server -Python $python -Arguments @{
        taskId = $taskId
        channelProfileId = $channelId
        bindingProof = $bindingProof
        defaults = $defaults
        executionMode = "review"
    }

    $fixtures = Join-Path $root "tests\fixtures\stage3\documents"
    $duplicate = Join-Path $isolated "same-content-different-name.txt"
    Copy-Item -LiteralPath (Join-Path $fixtures "en\short-story.txt") -Destination $duplicate
    $prepared = Invoke-InstalledTool -Name "source_add_prepare" -Server $server -Python $python -Arguments @{
        taskId = $taskId
        channelProfileId = $channelId
        bindingProof = $bindingProof
        inputs = @(
            @{ path = (Join-Path $fixtures "ja\short-story.txt"); language = "ja" },
            @{ path = (Join-Path $fixtures "zh\short-story.md"); language = "zh-CN" },
            @{ path = (Join-Path $fixtures "en\short-story.txt"); language = "en" },
            @{ path = $duplicate; language = "en" }
        )
    }
    if ($SourcePrepareOnly) {
        Write-Output "Targeted installed MCP source_add_prepare call passed for Japanese, Chinese, English, and duplicate inputs."
        return
    }
    if ($null -eq $prepared.notExecuted -or $prepared.notExecuted.Count -eq 0) {
        throw "Source confirmation card did not preserve the phase 3 boundary."
    }
    $completed = Invoke-InstalledTool -Name "source_add_confirm" -Server $server -Python $python -Arguments @{
        taskId = $taskId
        channelProfileId = $channelId
        bindingProof = $bindingProof
        acquisitionJobId = [string]$prepared.acquisitionJobId
        planHash = [string]$prepared.planHash
        confirmation = @{ confirmed = $true; choice = "confirm" }
    }
    if ([string]$completed.state -ne "COMPLETED") { throw "Installed source collection did not complete." }
    if ($SourceConfirmOnly) {
        Write-Output ("Targeted installed MCP confirmation completed: added={0}, reused={1}, updated={2}, partial={3}, failed={4}." -f @(
            [int]$completed.completionCard.success,
            [int]$completed.completionCard.reused,
            [int]$completed.completionCard.updated,
            [int]$completed.completionCard.partial,
            [int]$completed.completionCard.failed
        ))
        return
    }
    if ([int]$completed.completionCard.success -ne 3 -or [int]$completed.completionCard.reused -ne 1) {
        throw ("Installed source deduplication produced unexpected counts: added={0}, reused={1}." -f @(
            [int]$completed.completionCard.success,
            [int]$completed.completionCard.reused
        ))
    }
    if ($completed.completionCard.contentAnalysisStarted) {
        throw "Stage 3 source collection must not start content analysis."
    }

    # Each installed tool call starts a fresh service process, so this search also proves restart persistence.
    $search = Invoke-InstalledTool -Name "source_search" -Server $server -Python $python -Arguments @{
        channelProfileId = $channelId
        limit = 20
    }
    if ([int]$search.count -ne 3) { throw "Restarted installed service did not retain exactly three source packages." }
    $languages = @($search.sources | ForEach-Object { [string]$_.language })
    foreach ($language in @("ja", "zh-CN", "en")) {
        if ($languages -notcontains $language) { throw "Installed source search is missing language: $language" }
    }
    $detail = Invoke-InstalledTool -Name "source_get" -Server $server -Python $python -Arguments @{
        channelProfileId = $channelId
        sourcePackageId = [string]$search.sources[0].source_package_id
    }
    if ([string]$detail.manifest.schemaVersion -ne "1.0.0" -or [string]$detail.manifest.contractType -ne "source-package") {
        throw "Installed source package is not Source Package v1."
    }
    $integrity = Invoke-InstalledTool -Name "source_integrity_check" -Server $server -Python $python -Arguments @{
        channelProfileId = $channelId
    }
    if ([string]$integrity.status -ne "PASS") { throw "Installed source library integrity check failed." }
}
finally {
    foreach ($name in @(
        "AIVCP_DATA_ROOT", "AIVCP_ALLOW_TEST_FIXTURES", "AIVCP_TEST_PUBLISHER_FIXTURE",
        "AIVCP_VOICE_CATALOG", "AIVCP_PYTHON", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"
    )) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $isolated) {
        Remove-Item -LiteralPath $isolated -Recurse -Force
    }
    Pop-Location
}

Write-Output "Stage 3 Source Library, MCP, Skill installation, deduplication, persistence, and phase boundary validation passed in isolation."
