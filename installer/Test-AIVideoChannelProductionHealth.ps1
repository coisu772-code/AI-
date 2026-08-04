[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [string]$PluginRoot,
    [switch]$SkipServiceCheck,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$requiredSkills = @(
    "channel-production",
    "channel-onboarding",
    "source-library",
    "topic-selection",
    "manuscript-production",
    "publishing-assets"
    "production-handoff"
    "publish-video"
    "data-center"
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
    "production_capabilities"
    "production_package_assemble"
    "production_task_start"
    "production_task_get"
    "production_task_run"
    "production_task_pause"
    "production_task_resume"
    "production_task_retry"
    "production_task_invalidate"
    "production_jianying_export_ingest"
    "production_result_validate"
    "assemble_publish_package_v2"
    "validate_publish_package_v2"
    "import_publish_package_v2"
    "get_publication_status"
    "get_publication_receipt"
    "data_center_capabilities"
    "data_video_register"
    "data_collection_run"
    "data_report_generate"
    "data_recommendations_list"
    "data_learning_decide"
    "data_progress_get"
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
    $stateDataProperty = $installState.PSObject.Properties["userDataRoot"]
    if ($null -ne $stateDataProperty -and -not [string]::IsNullOrWhiteSpace([string]$stateDataProperty.Value)) {
        $installedDataRoot = Resolve-AivcpFullPath ([string]$stateDataProperty.Value)
        if (-not [string]::IsNullOrWhiteSpace($DataRoot) -and $installedDataRoot -ne (Resolve-AivcpFullPath $DataRoot)) {
            throw "Installation health check failed: configured user data root differs from install state."
        }
        $DataRoot = $installedDataRoot
    }
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
if ($installedSkills.Count -ne $requiredSkills.Count) {
    throw "Installation health check failed: expected exactly $($requiredSkills.Count) Skills, found $($installedSkills.Count)."
}
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
$productionSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "production-handoff\SKILL.md") -Raw -Encoding UTF8
$publishSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "publish-video\SKILL.md") -Raw -Encoding UTF8
$dataCenterSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "data-center\SKILL.md") -Raw -Encoding UTF8
$dataCenterProtocolText = Get-Content -LiteralPath (Join-Path $skillsRoot "data-center\references\tool-protocol.md") -Raw -Encoding UTF8
$dataCenterHealthScript = Join-Path $skillsRoot "data-center\scripts\check_data_center_install.py"
if (-not (Test-Path -LiteralPath $dataCenterHealthScript -PathType Leaf)) {
    throw "Installation health check failed: data-center health script is missing."
}
$declaredToolText = $routerText + "`n" + $productionSkillText + "`n" + $publishSkillText + "`n" + $dataCenterSkillText + "`n" + $dataCenterProtocolText
foreach ($toolName in $requiredContentTools) {
    if (-not $declaredToolText.Contains($toolName)) {
        throw "Installation health check failed: Skills do not declare $toolName."
    }
}

$serviceChecked = $false
$contentCapabilitiesChecked = $false
$productionCapabilitiesChecked = $false
$dataCenterCapabilitiesChecked = $false
if (-not $SkipServiceCheck) {
    $healthDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-rc-health-" + [guid]::NewGuid().ToString("N"))
    $hadDataRoot = Test-Path Env:AIVCP_DATA_ROOT
    $previousDataRoot = $env:AIVCP_DATA_ROOT
    $hadNetworkExecution = Test-Path Env:AIVCP_NETWORK_EXECUTION
    $previousNetworkExecution = $env:AIVCP_NETWORK_EXECUTION
    New-Item -ItemType Directory -Path $healthDataRoot -Force | Out-Null
    $env:AIVCP_DATA_ROOT = $healthDataRoot
    $env:AIVCP_NETWORK_EXECUTION = "false"
    try {
    $startScript = Join-Path $pluginFull "mcp\start.ps1"
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw "Installation health check failed: local tool launcher is missing."
    }
    $serverScript = Join-Path $pluginFull "mcp\server.py"
    function Invoke-AivcpHealthRequest([string]$RequestText) {
        $configuredPython = [Environment]::GetEnvironmentVariable("AIVCP_PYTHON", "Process")
        $installedPython = [System.IO.Path]::GetFullPath((Join-Path $pluginFull "..\..\runtime\python\python.exe"))
        $legacyPython = Join-Path $env:LOCALAPPDATA "AI Video Channel Production\current\runtime\python\python.exe"
        $fileName = $null
        $useUv = $false
        if (-not [string]::IsNullOrWhiteSpace($configuredPython) -and (Test-Path -LiteralPath $configuredPython -PathType Leaf)) {
            $fileName = $configuredPython
        }
        elseif (Test-Path -LiteralPath $installedPython -PathType Leaf) {
            $fileName = $installedPython
        }
        elseif (Test-Path -LiteralPath $legacyPython -PathType Leaf) {
            $fileName = $legacyPython
        }
        else {
            $uv = Get-Command uv -ErrorAction SilentlyContinue
            if ($null -eq $uv) { throw "Installation health check failed: no compatible Python runtime or uv was found." }
            $fileName = $uv.Source
            $useUv = $true
        }

        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        $relayRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-mcp-file-relay-" + [guid]::NewGuid().ToString("N"))
        $requestPath = Join-Path $relayRoot "request.jsonl"
        $relayPath = Join-Path $relayRoot "relay.py"
        $relayCode = @'
import pathlib
import subprocess
import sys

payload = pathlib.Path(sys.argv[2]).read_bytes()
completed = subprocess.run(
    [sys.executable, sys.argv[1], "mcp"],
    input=payload,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)
sys.stdout.buffer.write(completed.stdout)
sys.stderr.buffer.write(completed.stderr)
raise SystemExit(completed.returncode)
'@
        New-Item -ItemType Directory -Path $relayRoot -Force | Out-Null
        try {
            [System.IO.File]::WriteAllText($requestPath, $RequestText + "`n", $utf8NoBom)
            [System.IO.File]::WriteAllText($relayPath, $relayCode, [System.Text.Encoding]::ASCII)
            $quotedRelay = '"' + $relayPath.Replace('"', '\"') + '"'
            $quotedServer = '"' + $serverScript.Replace('"', '\"') + '"'
            $quotedRequest = '"' + $requestPath.Replace('"', '\"') + '"'
            $argumentText = if ($useUv) {
                "run --no-project python $quotedRelay $quotedServer $quotedRequest"
            }
            else {
                "$quotedRelay $quotedServer $quotedRequest"
            }
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $fileName
            $info.Arguments = $argumentText
            $info.WorkingDirectory = $pluginFull
            $info.UseShellExecute = $false
            $info.CreateNoWindow = $true
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $info.StandardOutputEncoding = $utf8NoBom
            $info.StandardErrorEncoding = $utf8NoBom
            $process = New-Object System.Diagnostics.Process
            $process.StartInfo = $info
            if (-not $process.Start()) { throw "Installation health check failed: local tool relay process did not start." }
            $stdout = $process.StandardOutput.ReadToEnd()
            $stderr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) { throw "Installation health check failed: local tool relay exited with $($process.ExitCode): $($stderr.Substring(0, [Math]::Min(400, $stderr.Length)))" }
            return $stdout
        }
        finally {
            if (Test-Path -LiteralPath $relayRoot) {
                Remove-Item -LiteralPath $relayRoot -Recurse -Force
            }
        }
    }
    $request = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
    $responseText = Invoke-AivcpHealthRequest $request
    $response = $responseText | ConvertFrom-Json
    $toolNames = @($response.result.tools | ForEach-Object { [string]$_.name })
    foreach ($toolName in $requiredContentTools) {
        if ($toolNames -notcontains $toolName) {
            throw "Installation health check failed: local tool is missing: $toolName"
        }
    }
    $capabilityRequest = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"content_capabilities","arguments":{}}}'
    $capabilityResponseText = Invoke-AivcpHealthRequest $capabilityRequest
    $capabilityResponse = $capabilityResponseText | ConvertFrom-Json
    $capabilityPayload = $capabilityResponse.result.structuredContent
    if ($null -eq $capabilityPayload -or -not [bool]$capabilityPayload.ok -or $null -eq $capabilityPayload.result) {
        throw "Installation health check failed: content capabilities are not healthy."
    }
    $contentCapabilitiesChecked = $true
    $productionRequest = '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"production_capabilities","arguments":{}}}'
    $productionResponseText = Invoke-AivcpHealthRequest $productionRequest
    $productionResponse = $productionResponseText | ConvertFrom-Json
    $productionPayload = $productionResponse.result.structuredContent
    if ($null -eq $productionPayload -or -not [bool]$productionPayload.ok -or [string]$productionPayload.result.contracts.productionPackage -ne "2.1") {
        throw "Installation health check failed: Production Package v2.1 is not healthy."
    }
    $productionCapabilitiesChecked = $true
    $dataRequest = '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"data_center_capabilities","arguments":{}}}'
    $dataResponseText = Invoke-AivcpHealthRequest $dataRequest
    $dataResponse = $dataResponseText | ConvertFrom-Json
    $dataCapabilityPayload = $dataResponse.result.structuredContent
    if ($null -eq $dataCapabilityPayload -or -not [bool]$dataCapabilityPayload.ok -or $null -eq $dataCapabilityPayload.result) {
        throw "Installation health check failed: data-center capabilities are not healthy."
    }
    $authorization = $dataCapabilityPayload.result.analyticsAuthorization
    if (
        $null -eq $authorization -or
        [string]$authorization.status -ne "AUTH_REQUIRED" -or
        [bool]$authorization.available -or
        $null -eq $authorization.monetaryScope -or
        [bool]$authorization.monetaryScope.enabled -or
        [bool]$authorization.monetaryScope.available -or
        [bool]$authorization.oauthStarted
    ) {
        throw "Installation health check failed: Analytics must default to AUTH_REQUIRED, unavailable, no monetary scope, and no OAuth."
    }
    $dataCenterCapabilitiesChecked = $true
    $serviceChecked = $true
    }
    finally {
        if ($hadDataRoot) { $env:AIVCP_DATA_ROOT = $previousDataRoot } else { Remove-Item Env:AIVCP_DATA_ROOT -ErrorAction SilentlyContinue }
        if ($hadNetworkExecution) { $env:AIVCP_NETWORK_EXECUTION = $previousNetworkExecution } else { Remove-Item Env:AIVCP_NETWORK_EXECUTION -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $healthDataRoot) {
            Remove-Item -LiteralPath $healthDataRoot -Recurse -Force
        }
    }
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
    productionCapabilitiesChecked = $productionCapabilitiesChecked
    dataCenterCapabilitiesChecked = $dataCenterCapabilitiesChecked
    userDataRoot = if ([string]::IsNullOrWhiteSpace($DataRoot)) { $null } else { Resolve-AivcpFullPath $DataRoot }
    userDataSeparatedFromActiveProgram = if ([string]::IsNullOrWhiteSpace($DataRoot)) { $null } else {
        $activeProgram = Resolve-AivcpFullPath (Join-Path (Resolve-AivcpFullPath $InstallRoot) "current")
        -not (Resolve-AivcpFullPath $DataRoot).StartsWith(($activeProgram.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar), [System.StringComparison]::OrdinalIgnoreCase)
    }
    boundaries = [ordered]@{
        workshop = "not_called"
        oauth = "not_called"
        upload = "not_called"
        analyticsAuthorization = "AUTH_REQUIRED"
        analyticsPrivateApi = "not_called"
        token = "not_read"
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
