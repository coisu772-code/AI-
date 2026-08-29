[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$server = Join-Path $PSScriptRoot "server.py"
$pluginRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pluginManifestPath = Join-Path $pluginRoot ".codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) {
    throw "The cached plugin manifest is missing. Reinstall the AI Video Channel Production plugin."
}
$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$pluginManifest.name -ne "ai-video-channel-production" -or [string]::IsNullOrWhiteSpace([string]$pluginManifest.version)) {
    throw "The cached plugin identity is invalid. Reinstall the AI Video Channel Production plugin."
}
$pluginVersion = [string]$pluginManifest.version
function Test-AivcpPluginVersionMatchesProduct([string]$PluginVersion, [string]$ProductVersion) {
    if ($PluginVersion -eq $ProductVersion) { return $true }
    $prefix = $ProductVersion + "+codex."
    if (-not $PluginVersion.StartsWith($prefix, [System.StringComparison]::Ordinal)) { return $false }
    return $PluginVersion.Substring($prefix.Length) -match '^[a-z0-9-]+$'
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$boundPython = $null
$boundDataRoot = $null
$boundConfigRoot = $null
$boundActiveRoot = $null
$boundInstallRoot = $null
$boundProductVersion = $null
$boundReleaseManifestSha256 = $null
$installedStatePath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\..\install-state.json"))
$installedRuntime = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\..\runtime\python\python.exe"))
if ((Test-Path -LiteralPath $installedStatePath -PathType Leaf) -and (Test-Path -LiteralPath $installedRuntime -PathType Leaf)) {
    $installedState = Get-Content -LiteralPath $installedStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$installedState.schemaVersion -ne "2.0.0" -or
        [string]$installedState.productId -ne "ai-video-channel-production" -or
        ([string]$installedState.productVersion -ne [string]$pluginManifest.version -and -not (Test-AivcpPluginVersionMatchesProduct $pluginVersion ([string]$installedState.productVersion))) -or
        -not [bool]$installedState.runtime.bundled -or
        [string]$installedState.runtime.python -ne "runtime/python/python.exe"
    ) {
        throw "The installed plugin, state, and bundled runtime versions do not match. Run installer repair."
    }
    $boundPython = $installedRuntime
    $boundActiveRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
    $boundInstallRoot = Split-Path -Parent $boundActiveRoot
    $boundProductVersion = [string]$installedState.productVersion
    $boundReleaseManifestSha256 = [string]$installedState.releaseManifestSha256
    $boundDataRoot = [System.IO.Path]::GetFullPath([string]$installedState.userDataRoot)
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $boundConfigRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "AIVCP-Config"))
    }
}
else {
    $locatorPath = if (-not [string]::IsNullOrWhiteSpace($env:AIVCP_RUNTIME_LOCATOR)) {
        [System.IO.Path]::GetFullPath($env:AIVCP_RUNTIME_LOCATOR)
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "AIVCP-Config\runtime-locator.json"))
    }
    else { $null }
    if ($null -ne $locatorPath -and (Test-Path -LiteralPath $locatorPath -PathType Leaf)) {
        $locator = Get-Content -LiteralPath $locatorPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (
            [string]$locator.schemaVersion -ne "1.0.0" -or
            [string]$locator.productId -ne "ai-video-channel-production" -or
            [string]$locator.activeRoot -ne "current" -or
            [string]$locator.pythonRelativePath -ne "runtime/python/python.exe"
        ) {
            throw "The AI Video Channel Production runtime locator identity is invalid. Run installer repair."
        }
        $installRoot = [System.IO.Path]::GetFullPath([string]$locator.installRoot)
        if ($installRoot -eq [System.IO.Path]::GetPathRoot($installRoot) -or $installRoot.Length -lt 12) {
            throw "The AI Video Channel Production runtime locator installation root is unsafe."
        }
        $installationPath = Join-Path $installRoot "installation.json"
        $statePath = Join-Path $installRoot "current\install-state.json"
        if (-not (Test-Path -LiteralPath $installationPath -PathType Leaf) -or -not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            throw "The AI Video Channel Production runtime locator points to an incomplete installation. Run installer repair."
        }
        $installation = Get-Content -LiteralPath $installationPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $locatorDataRoot = [System.IO.Path]::GetFullPath([string]$locator.userDataRoot)
        $stateDataRoot = [System.IO.Path]::GetFullPath([string]$state.userDataRoot)
        $installationDataRoot = [System.IO.Path]::GetFullPath([string]$installation.userDataRoot)
        if (
            [string]$installation.schemaVersion -ne "2.0.0" -or
            [string]$installation.productId -ne "ai-video-channel-production" -or
            [string]$installation.activeVersion -ne [string]$locator.productVersion -or
            [string]$installation.activeRoot -ne "current" -or
            [string]$state.schemaVersion -ne "2.0.0" -or
            [string]$state.productId -ne "ai-video-channel-production" -or
            [string]$state.productVersion -ne [string]$locator.productVersion -or
            ([string]$pluginManifest.version -ne [string]$locator.productVersion -and -not (Test-AivcpPluginVersionMatchesProduct $pluginVersion ([string]$locator.productVersion))) -or
            [string]$state.releaseManifestSha256 -ne [string]$installation.releaseManifestSha256 -or
            -not $locatorDataRoot.Equals($stateDataRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not $installationDataRoot.Equals($stateDataRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not [bool]$state.runtime.bundled -or
            [string]$state.runtime.python -ne "runtime/python/python.exe"
        ) {
            throw "The cached plugin version or runtime locator does not match the active installation. Restart Codex after plugin repair."
        }
        $boundPython = Join-Path $installRoot "current\runtime\python\python.exe"
        if (-not (Test-Path -LiteralPath $boundPython -PathType Leaf)) {
            throw "The AI Video Channel Production bundled Python runtime is missing. Run installer repair."
        }
        $boundDataRoot = $stateDataRoot
        $boundConfigRoot = Split-Path -Parent $locatorPath
        $boundActiveRoot = Join-Path $installRoot "current"
        $boundInstallRoot = $installRoot
        $boundProductVersion = [string]$state.productVersion
        $boundReleaseManifestSha256 = [string]$state.releaseManifestSha256
    }
}

if (-not [string]::IsNullOrWhiteSpace($boundDataRoot)) {
    $env:AIVCP_DATA_ROOT = $boundDataRoot
}
if (-not [string]::IsNullOrWhiteSpace($boundConfigRoot)) {
    $env:AIVCP_CONFIG_ROOT = $boundConfigRoot
}
if (-not [string]::IsNullOrWhiteSpace($boundPython)) {
    $boundDeno = Join-Path $boundActiveRoot "runtime\python\tools\deno.exe"
    $boundFFmpeg = Join-Path $boundActiveRoot "apps\workshop\tools\ffmpeg\bin\ffmpeg.exe"
    $boundFFprobe = Join-Path $boundActiveRoot "apps\workshop\tools\ffmpeg\bin\ffprobe.exe"
    $boundWorkshop = Join-Path $boundActiveRoot "apps\workshop\Z 漫剧工坊.exe"
    $boundPublisherChannelList = Join-Path $boundActiveRoot "apps\publisher\channel-list.exe"
    $boundPublisherV2 = Join-Path $boundActiveRoot "apps\publisher\publish-package-v2.exe"
    $boundVoiceCatalog = Join-Path $boundActiveRoot "plugins\ai-video-channel-production\assets\voice-catalog.json"
    $boundWorkshopIsolationRoot = Join-Path $boundDataRoot "workshop-isolation"
    $requiredFiles = @($boundDeno, $boundFFmpeg, $boundFFprobe, $boundWorkshop, $boundPublisherChannelList, $boundPublisherV2, $boundVoiceCatalog)
    if (
        [string]::IsNullOrWhiteSpace($boundInstallRoot) -or
        [string]::IsNullOrWhiteSpace($boundProductVersion) -or
        [string]::IsNullOrWhiteSpace($boundReleaseManifestSha256) -or
        @($requiredFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0 -or
        -not (Test-Path -LiteralPath $boundWorkshopIsolationRoot -PathType Container)
    ) {
        throw "The installed MCP runtime binding is incomplete. Run installer repair."
    }
    $env:AIVCP_INSTALL_ROOT = [System.IO.Path]::GetFullPath($boundInstallRoot)
    $env:AIVCP_EXPECTED_PRODUCT_VERSION = $boundProductVersion
    $env:AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256 = $boundReleaseManifestSha256
    $env:AIVCP_WORKSHOP_EXECUTABLE = [System.IO.Path]::GetFullPath($boundWorkshop)
    $env:AIVCP_WORKSHOP_ISOLATION_ROOT = [System.IO.Path]::GetFullPath($boundWorkshopIsolationRoot)
    $env:AIVCP_FFMPEG_PATH = [System.IO.Path]::GetFullPath($boundFFmpeg)
    $env:AIVCP_FFPROBE_PATH = [System.IO.Path]::GetFullPath($boundFFprobe)
    $env:AIVCP_PUBLISHER_CHANNEL_LIST_EXE = [System.IO.Path]::GetFullPath($boundPublisherChannelList)
    $env:AIVCP_PUBLISHER_V2_CLI = [System.IO.Path]::GetFullPath($boundPublisherV2)
    $env:AIVCP_VOICE_CATALOG = [System.IO.Path]::GetFullPath($boundVoiceCatalog)
    $env:AIVCP_NETWORK_EXECUTION = "false"
    $env:AIVCP_PUBLISHER_NETWORK_EXECUTION = "false"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:AIVCP_YT_DLP_COMMAND_JSON = ConvertTo-Json -InputObject @(
        [System.IO.Path]::GetFullPath($boundPython),
        "-m",
        "yt_dlp",
        "--js-runtimes",
        ("deno:" + [System.IO.Path]::GetFullPath($boundDeno)),
        "--ffmpeg-location",
        [System.IO.Path]::GetFullPath((Split-Path -Parent $boundFFmpeg))
    ) -Compress
    & $boundPython $server mcp
    exit $LASTEXITCODE
}

$configuredPython = [Environment]::GetEnvironmentVariable("AIVCP_PYTHON", "Process")
if (-not [string]::IsNullOrWhiteSpace($configuredPython) -and (Test-Path -LiteralPath $configuredPython -PathType Leaf)) {
    & $configuredPython $server mcp
    exit $LASTEXITCODE
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uv) {
    & $uv.Source run --no-project python $server mcp
    exit $LASTEXITCODE
}

throw "The local tool service needs a compatible bound Python runtime. Run installer repair."
