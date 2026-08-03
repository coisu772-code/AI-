[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$PluginRoot,
    [switch]$SkipServiceCheck,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$requiredSkills = @(
    "channel-production",
    "channel-onboarding",
    "source-library",
    "topic-selection",
    "manuscript-production",
    "publishing-assets"
)
$requiredContentTools = @(
    "content_capabilities",
    "content_project_start",
    "content_topic_checkpoint",
    "content_topic_finalize",
    "content_manuscript_finalize",
    "content_publishing_finalize",
    "content_project_get",
    "content_integrity_check",
    "content_handoff_check"
)

$installState = $null
if ([string]::IsNullOrWhiteSpace($PluginRoot)) {
    $currentRoot = [System.IO.Path]::GetFullPath((Join-Path $InstallRoot "current"))
    $PluginRoot = Join-Path $currentRoot "plugins\ai-video-channel-production"
    $installStatePath = Join-Path $currentRoot "install-state.json"
    if (-not (Test-Path -LiteralPath $installStatePath -PathType Leaf)) {
        throw "Installation health check failed: install-state.json is missing."
    }
    $installState = Get-Content -LiteralPath $installStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

$pluginFull = [System.IO.Path]::GetFullPath($PluginRoot)
$manifestPath = Join-Path $pluginFull ".codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Installation health check failed: plugin manifest is missing."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$manifest.name -ne "ai-video-channel-production") {
    throw "Installation health check failed: unexpected plugin identity."
}
if ($null -ne $installState -and [string]$installState.productVersion -ne [string]$manifest.version) {
    throw "Installation health check failed: install state and plugin versions differ."
}

$skillsRoot = Join-Path $pluginFull "skills"
$installedSkills = @(Get-ChildItem -LiteralPath $skillsRoot -Directory | ForEach-Object { $_.Name })
foreach ($skill in $requiredSkills) {
    if ($installedSkills -notcontains $skill) {
        throw "Installation health check failed: required Skill is missing: $skill"
    }
    $skillFile = Join-Path $skillsRoot "$skill\SKILL.md"
    $agentFile = Join-Path $skillsRoot "$skill\agents\openai.yaml"
    if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf) -or -not (Test-Path -LiteralPath $agentFile -PathType Leaf)) {
        throw "Installation health check failed: Skill metadata is incomplete: $skill"
    }
}

$routerText = Get-Content -LiteralPath (Join-Path $skillsRoot "channel-production\SKILL.md") -Raw -Encoding UTF8
foreach ($toolName in $requiredContentTools) {
    if (-not $routerText.Contains($toolName)) {
        throw "Installation health check failed: total router does not declare $toolName."
    }
}

$serviceChecked = $false
$contentCapabilitiesChecked = $false
if (-not $SkipServiceCheck) {
    $startScript = Join-Path $pluginFull "mcp\start.ps1"
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw "Installation health check failed: local tool launcher is missing."
    }
    $request = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
    $responseText = $request | powershell -NoProfile -ExecutionPolicy Bypass -File $startScript | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Installation health check failed: local tool service did not start."
    }
    $response = $responseText | ConvertFrom-Json
    $toolNames = @($response.result.tools | ForEach-Object { [string]$_.name })
    foreach ($toolName in $requiredContentTools) {
        if ($toolNames -notcontains $toolName) {
            throw "Installation health check failed: local tool is missing: $toolName"
        }
    }
    $capabilityRequest = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"content_capabilities","arguments":{}}}'
    $capabilityResponseText = $capabilityRequest | powershell -NoProfile -ExecutionPolicy Bypass -File $startScript | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Installation health check failed: content capabilities call did not complete."
    }
    $capabilityResponse = $capabilityResponseText | ConvertFrom-Json
    $capabilityPayload = $capabilityResponse.result.structuredContent
    if ($null -eq $capabilityPayload -or -not [bool]$capabilityPayload.ok -or $null -eq $capabilityPayload.result) {
        throw "Installation health check failed: content capabilities are not healthy."
    }
    $contentCapabilitiesChecked = $true
    $serviceChecked = $true
}

$result = [ordered]@{
    status = "PASS"
    productId = [string]$manifest.name
    productVersion = [string]$manifest.version
    pluginRoot = $pluginFull
    skillCount = $requiredSkills.Count
    contentToolCount = $requiredContentTools.Count
    serviceChecked = $serviceChecked
    contentCapabilitiesChecked = $contentCapabilitiesChecked
    boundaries = [ordered]@{
        workshop = "not_called"
        oauth = "not_called"
        upload = "not_called"
        analytics = "not_called"
        longTermLearningWrite = "not_called"
    }
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 5
}
else {
    Write-Output ("Health PASS: {0} {1}; Skills={2}; content tools={3}; serviceChecked={4}." -f @(
        $result.productId,
        $result.productVersion,
        $result.skillCount,
        $result.contentToolCount,
        $result.serviceChecked
    ))
}
