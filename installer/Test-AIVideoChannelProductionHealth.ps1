[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
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
    "channel-distillation",
    "video-copy-deconstruction",
    "original-imitation-writing",
    "topic-selection",
    "manuscript-production",
    "publishing-assets"
    "production-handoff"
    "publish-video"
    "data-center"
    "update-ai-video-system"
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
    "channel_distillation_capabilities"
    "channel_distillation_prepare"
    "channel_distillation_checkpoint"
    "channel_distillation_finalize"
    "channel_distillation_get"
    "channel_distillation_integrity_check"
    "video_deconstruction_capabilities"
    "video_deconstruction_prepare"
    "video_deconstruction_read_source"
    "video_deconstruction_checkpoint"
    "video_deconstruction_finalize"
    "video_deconstruction_get"
    "video_deconstruction_integrity_check"
    "original_imitation_capabilities"
    "original_imitation_prepare"
    "original_imitation_read_source"
    "original_imitation_source_checkpoint"
    "original_imitation_direction_checkpoint"
    "original_imitation_directions_finalize"
    "original_imitation_confirm"
    "original_imitation_get"
    "original_imitation_integrity_check"
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
$voiceCatalogPath = Join-Path $pluginFull "assets\voice-catalog.json"
if (-not (Test-Path -LiteralPath $voiceCatalogPath -PathType Leaf)) {
    throw "Installation health check failed: bundled pre-scanned voice catalog is missing."
}
try {
    $voiceCatalog = Get-Content -LiteralPath $voiceCatalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    throw "Installation health check failed: bundled pre-scanned voice catalog is unreadable."
}
if ([string]$voiceCatalog.schemaVersion -ne "1.0.0" -or @($voiceCatalog.engines).Count -eq 0) {
    throw "Installation health check failed: bundled pre-scanned voice catalog contract is invalid."
}
$youtubeRuntimeContractPath = Join-Path $pluginFull "assets\portable-youtube-runtime.json"
if (-not (Test-Path -LiteralPath $youtubeRuntimeContractPath -PathType Leaf)) {
    throw "Installation health check failed: portable YouTube runtime contract is missing."
}
try {
    $youtubeRuntimeContract = Get-Content -LiteralPath $youtubeRuntimeContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    throw "Installation health check failed: portable YouTube runtime contract is unreadable."
}
if (
    [string]$youtubeRuntimeContract.schemaVersion -ne "1.0.0" -or
    [string]$youtubeRuntimeContract.collector.id -ne "yt-dlp" -or
    [string]$youtubeRuntimeContract.javascriptRuntime.id -ne "deno" -or
    [bool]$youtubeRuntimeContract.requiresSystemPath -ne $false
) {
    throw "Installation health check failed: portable YouTube runtime contract is invalid."
}
foreach ($voiceEngine in @($voiceCatalog.engines)) {
    if ([string]::IsNullOrWhiteSpace([string]$voiceEngine.engineId) -or -not [bool]$voiceEngine.installed -or @($voiceEngine.voices).Count -eq 0) {
        throw "Installation health check failed: bundled pre-scanned voice catalog contains an unusable engine."
    }
}
$voiceCatalogCoverage = @(
    @($voiceCatalog.engines | ForEach-Object { [string]$_.engineId }) +
    @($voiceCatalog.enginePolicies | ForEach-Object { [string]$_.engineId })
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

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
$channelDistillationText = Get-Content -LiteralPath (Join-Path $skillsRoot "channel-distillation\SKILL.md") -Raw -Encoding UTF8
$videoDeconstructionText = Get-Content -LiteralPath (Join-Path $skillsRoot "video-copy-deconstruction\SKILL.md") -Raw -Encoding UTF8
$originalImitationText = Get-Content -LiteralPath (Join-Path $skillsRoot "original-imitation-writing\SKILL.md") -Raw -Encoding UTF8
$productionSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "production-handoff\SKILL.md") -Raw -Encoding UTF8
$publishSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "publish-video\SKILL.md") -Raw -Encoding UTF8
$dataCenterSkillText = Get-Content -LiteralPath (Join-Path $skillsRoot "data-center\SKILL.md") -Raw -Encoding UTF8
$dataCenterProtocolText = Get-Content -LiteralPath (Join-Path $skillsRoot "data-center\references\tool-protocol.md") -Raw -Encoding UTF8
$dataCenterHealthScript = Join-Path $skillsRoot "data-center\scripts\check_data_center_install.py"
if (-not (Test-Path -LiteralPath $dataCenterHealthScript -PathType Leaf)) {
    throw "Installation health check failed: data-center health script is missing."
}
$declaredToolText = $routerText + "`n" + $channelDistillationText + "`n" + $videoDeconstructionText + "`n" + $originalImitationText + "`n" + $productionSkillText + "`n" + $publishSkillText + "`n" + $dataCenterSkillText + "`n" + $dataCenterProtocolText
foreach ($toolName in $requiredContentTools) {
    if (-not $declaredToolText.Contains($toolName)) {
        throw "Installation health check failed: Skills do not declare $toolName."
    }
}

$serviceChecked = $false
$systemCapabilitiesChecked = $false
$contentCapabilitiesChecked = $false
$productionCapabilitiesChecked = $false
$dataCenterCapabilitiesChecked = $false
$voiceCatalogChecked = $false
$youtubeCollectorChecked = $false
if (-not $SkipServiceCheck) {
    $healthDataRoot = $null
    $healthEnvironment = [ordered]@{}
    if ($null -ne $installState) {
        $descriptorPath = Join-Path $pluginFull ".mcp.json"
        if (-not (Test-Path -LiteralPath $descriptorPath -PathType Leaf)) {
            throw "Installation health check failed: runtime-bound MCP descriptor is missing."
        }
        $descriptor = Get-Content -LiteralPath $descriptorPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $descriptorServer = $descriptor.mcpServers."ai-video-channel-tools"
        if ($null -eq $descriptorServer -or $null -eq $descriptorServer.env) {
            throw "Installation health check failed: runtime-bound MCP descriptor environment is missing."
        }
        foreach ($property in $descriptorServer.env.PSObject.Properties) {
            $healthEnvironment[[string]$property.Name] = [string]$property.Value
        }
        $installedActiveRoot = [System.IO.Path]::GetFullPath((Join-Path $InstallRoot "current"))
        $expectedPython = Join-Path $installedActiveRoot "runtime\python\python.exe"
        $expectedDeno = Join-Path $installedActiveRoot (([string]$youtubeRuntimeContract.javascriptRuntime.executableRelativePath).Replace("/", "\"))
        $expectedCollectorModule = Join-Path $installedActiveRoot (([string]$youtubeRuntimeContract.collector.moduleRelativePath).Replace("/", "\"))
        $expectedEjsModule = Join-Path $installedActiveRoot (([string]$youtubeRuntimeContract.collector.ejsModuleRelativePath).Replace("/", "\"))
        $expectedFFmpeg = Join-Path $installedActiveRoot "apps\workshop\tools\ffmpeg\bin\ffmpeg.exe"
        foreach ($requiredPath in @($expectedPython, $expectedDeno, $expectedCollectorModule, $expectedEjsModule, $expectedFFmpeg)) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
                throw "Installation health check failed: portable YouTube runtime file is missing: $requiredPath"
            }
        }
        try {
            $boundYoutubeCommand = @(([string]$descriptorServer.env.AIVCP_YT_DLP_COMMAND_JSON | ConvertFrom-Json))
        }
        catch {
            throw "Installation health check failed: portable YouTube collector command is unreadable."
        }
        $expectedYoutubeCommand = @(
            [System.IO.Path]::GetFullPath($expectedPython),
            "-m",
            "yt_dlp",
            "--js-runtimes",
            ("deno:" + [System.IO.Path]::GetFullPath($expectedDeno)),
            "--ffmpeg-location",
            [System.IO.Path]::GetFullPath((Split-Path -Parent $expectedFFmpeg))
        )
        if ($boundYoutubeCommand.Count -ne $expectedYoutubeCommand.Count -or (Compare-Object -ReferenceObject $expectedYoutubeCommand -DifferenceObject $boundYoutubeCommand -SyncWindow 0)) {
            throw "Installation health check failed: portable YouTube collector command is not bound to managed files."
        }
        $collectorVersionOutput = @(& $expectedPython -m yt_dlp --version 2>&1)
        $collectorVersionExit = $LASTEXITCODE
        $collectorVersion = $collectorVersionOutput | Select-Object -First 1
        if ($collectorVersionExit -ne 0 -or [string]$collectorVersion -ne [string]$youtubeRuntimeContract.collector.version) {
            throw "Installation health check failed: bundled yt-dlp version check failed."
        }
        $denoVersionOutput = @(& $expectedDeno --version 2>&1)
        $denoVersionExit = $LASTEXITCODE
        $denoVersionLine = $denoVersionOutput | Select-Object -First 1
        if ($denoVersionExit -ne 0 -or [string]$denoVersionLine -notlike ("deno " + [string]$youtubeRuntimeContract.javascriptRuntime.version + " *")) {
            throw "Installation health check failed: bundled Deno version check failed."
        }
        $youtubeCollectorChecked = $true
    }
    else {
        $healthDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-rc-health-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $healthDataRoot -Force | Out-Null
        $healthEnvironment["AIVCP_DATA_ROOT"] = $healthDataRoot
        $healthEnvironment["AIVCP_NETWORK_EXECUTION"] = "false"
        $healthEnvironment["AIVCP_PUBLISHER_NETWORK_EXECUTION"] = "false"
    }
    $environmentSnapshots = @{}
    foreach ($entry in $healthEnvironment.GetEnumerator()) {
        $previousValue = [Environment]::GetEnvironmentVariable([string]$entry.Key, "Process")
        $environmentSnapshots[[string]$entry.Key] = [ordered]@{ existed = $null -ne $previousValue; value = $previousValue }
        [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value, "Process")
    }
    try {
    $startScript = Join-Path $pluginFull "mcp\start.ps1"
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw "Installation health check failed: local tool launcher is missing."
    }
    $serverScript = Join-Path $pluginFull "mcp\server.py"
    function Invoke-AivcpHealthRequest([string]$RequestText) {
        $configuredPython = [Environment]::GetEnvironmentVariable("AIVCP_PYTHON", "Process")
        $installedPython = [System.IO.Path]::GetFullPath((Join-Path $pluginFull "..\..\runtime\python\python.exe"))
        $fileName = $null
        $useUv = $false
        if (-not [string]::IsNullOrWhiteSpace($configuredPython) -and (Test-Path -LiteralPath $configuredPython -PathType Leaf)) {
            $fileName = $configuredPython
        }
        elseif (Test-Path -LiteralPath $installedPython -PathType Leaf) {
            $fileName = $installedPython
        }
        else {
            $locatorRecord = Get-AivcpRuntimeLocatorRecord
            if ($null -ne $locatorRecord) {
                $fileName = [string]$locatorRecord.pythonPath
            }
            else {
                $uv = Get-Command uv -ErrorAction SilentlyContinue
                if ($null -eq $uv) { throw "Installation health check failed: no compatible Python runtime or uv was found." }
                $fileName = $uv.Source
                $useUv = $true
            }
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
    if ($null -ne $installState) {
        if (
            -not [bool]$productionPayload.result.workshopBridgeConfigured -or
            -not [bool]$productionPayload.result.ffmpegAvailable -or
            -not [bool]$productionPayload.result.ffprobeAvailable -or
            -not [bool]$productionPayload.result.workshopHealth.success -or
            -not [bool]$productionPayload.result.workshopHealth.ffmpegAvailable -or
            -not [bool]$productionPayload.result.workshopHealth.ffmpegPathSet -or
            -not [bool]$productionPayload.result.workshopHealth.ffprobePathSet -or
            @($productionPayload.result.workshopCapabilities.supportedPackageVersions) -notcontains "2.1" -or
            [bool]$productionPayload.result.workshopCapabilities.externalServiceProbeExecuted
        ) {
            throw "Installation health check failed: installed workshop, FFmpeg, ffprobe, or Production Package 2.1 bridge is not healthy."
        }
        $uncoveredVoiceEngines = @(
            @($productionPayload.result.workshopCapabilities.voiceEngines) |
                ForEach-Object { [string]$_.engine } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $voiceCatalogCoverage -notcontains $_ }
        )
        if ($uncoveredVoiceEngines.Count -gt 0) {
            throw "Installation health check failed: workshop voice engine coverage is missing from the catalog or an explicit no-list policy: $($uncoveredVoiceEngines -join ', ')"
        }
    }
    $productionCapabilitiesChecked = $true
    $systemRequest = '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"system_capabilities","arguments":{}}}'
    $systemResponseText = Invoke-AivcpHealthRequest $systemRequest
    $systemResponse = $systemResponseText | ConvertFrom-Json
    $systemPayload = $systemResponse.result.structuredContent
    if ($null -eq $systemPayload -or -not [bool]$systemPayload.ok -or $null -eq $systemPayload.result) {
        throw "Installation health check failed: system capabilities are not healthy."
    }
    if (
        -not [bool]$systemPayload.result.voiceCatalog.available -or
        -not [bool]$systemPayload.result.capabilities.preScannedVoiceCatalog
    ) {
        throw "Installation health check failed: pre-scanned voice catalog is not available to the local tool service."
    }
    if ($null -ne $installState -and (
        -not [bool]$systemPayload.result.publisherInterface.available -or
        -not [bool]$systemPayload.result.capabilities.publisherReadOnlyInterfaceConfigured -or
        -not [bool]$systemPayload.result.capabilities.publisherV2BridgeConfigured -or
        -not [bool]$systemPayload.result.publisherV2Bridge.configured -or
        [bool]$systemPayload.result.publisherV2Bridge.networkExecution
    )) {
        throw "Installation health check failed: installed publisher read-only or publish-package-v2 offline bridge is not configured."
    }
    $systemCapabilitiesChecked = $true
    $voiceCatalogRequest = '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"system_voice_catalog","arguments":{}}}'
    $voiceCatalogResponseText = Invoke-AivcpHealthRequest $voiceCatalogRequest
    $voiceCatalogResponse = $voiceCatalogResponseText | ConvertFrom-Json
    $voiceCatalogPayload = $voiceCatalogResponse.result.structuredContent
    if (
        $null -eq $voiceCatalogPayload -or
        -not [bool]$voiceCatalogPayload.ok -or
        [string]$voiceCatalogPayload.result.schemaVersion -ne "1.0.0" -or
        @($voiceCatalogPayload.result.engines).Count -eq 0
    ) {
        throw "Installation health check failed: pre-scanned voice catalog cannot be read safely."
    }
    $voiceCatalogChecked = $true
    $dataRequest = '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"data_center_capabilities","arguments":{}}}'
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
        foreach ($entry in $environmentSnapshots.GetEnumerator()) {
            $snapshot = $entry.Value
            if ([bool]$snapshot.existed) {
                [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$snapshot.value, "Process")
            }
            else {
                [Environment]::SetEnvironmentVariable([string]$entry.Key, $null, "Process")
            }
        }
        if ($null -ne $healthDataRoot -and (Test-Path -LiteralPath $healthDataRoot)) {
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
    systemCapabilitiesChecked = $systemCapabilitiesChecked
    contentCapabilitiesChecked = $contentCapabilitiesChecked
    productionCapabilitiesChecked = $productionCapabilitiesChecked
    dataCenterCapabilitiesChecked = $dataCenterCapabilitiesChecked
    voiceCatalogChecked = $voiceCatalogChecked
    youtubeCollectorChecked = $youtubeCollectorChecked
    userDataRoot = if ([string]::IsNullOrWhiteSpace($DataRoot)) { $null } else { Resolve-AivcpFullPath $DataRoot }
    userDataSeparatedFromActiveProgram = if ([string]::IsNullOrWhiteSpace($DataRoot)) { $null } else {
        $activeProgram = Resolve-AivcpFullPath (Join-Path (Resolve-AivcpFullPath $InstallRoot) "current")
        -not (Resolve-AivcpFullPath $DataRoot).StartsWith(($activeProgram.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar), [System.StringComparison]::OrdinalIgnoreCase)
    }
    boundaries = [ordered]@{
        workshop = if ($null -ne $installState) { "read_only_health_and_capabilities" } else { "not_called" }
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
