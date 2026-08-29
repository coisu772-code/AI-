Set-StrictMode -Version Latest

$script:AivcpProductId = "ai-video-channel-production"
$script:AivcpMarketplaceName = "novel-manga-production"
$script:AivcpDefaultInstallFolder = "AIVCP"
$script:AivcpDefaultDataFolder = "AI Video Channel Production Data"
$script:AivcpRuntimeLocatorFolder = "AIVCP-Config"
$script:AivcpRuntimeLocatorFileName = "runtime-locator.json"
$script:AivcpRuntimeLocatorHistoryFileName = "runtime-locator-history.jsonl"
$script:AivcpCurrentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ([string]::IsNullOrWhiteSpace($script:AivcpCurrentUserSid)) { throw "Cannot resolve the current Windows user identity for the installation lock." }
$script:AivcpOperationMutexName = "Global\AIVCP-ChannelProduction-Installer-v1-$($script:AivcpCurrentUserSid)"
$script:AivcpLegacyPathBudget = 248

function Resolve-AivcpFullPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Test-AivcpSafeRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PathValue,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $full = Resolve-AivcpFullPath $PathValue
    if ($full -eq [System.IO.Path]::GetPathRoot($full) -or $full.Length -lt 12) {
        throw "$Label is too broad; refusing operation: $full"
    }
    return $full
}

function Get-AivcpDefaultInstallRoot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required to resolve the default program installation root."
    }
    return Resolve-AivcpFullPath (Join-Path $env:LOCALAPPDATA $script:AivcpDefaultInstallFolder)
}

function Get-AivcpRuntimeLocatorPath {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required to resolve the runtime locator."
    }
    return Resolve-AivcpFullPath (Join-Path (Join-Path $env:LOCALAPPDATA $script:AivcpRuntimeLocatorFolder) $script:AivcpRuntimeLocatorFileName)
}

function Enter-AivcpOperationLock {
    param([int]$TimeoutSeconds = 120)
    if ($TimeoutSeconds -lt 0) { throw "Operation lock timeout must not be negative." }
    $mutex = [System.Threading.Mutex]::new($false, $script:AivcpOperationMutexName)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw "Another AI Video Channel Production install, upgrade, repair, rollback, or uninstall operation is already running. Retry after it finishes."
        }
        return $mutex
    }
    catch {
        if (-not $acquired) { $mutex.Dispose() }
        throw
    }
}

function Exit-AivcpOperationLock {
    param([Parameter(Mandatory = $true)][System.Threading.Mutex]$Mutex)
    try { $Mutex.ReleaseMutex() } finally { $Mutex.Dispose() }
}

function Get-AivcpFileSnapshot {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    $full = Resolve-AivcpFullPath $PathValue
    $exists = Test-Path -LiteralPath $full -PathType Leaf
    return [ordered]@{ path=$full; exists=$exists; bytes=if ($exists) { [System.IO.File]::ReadAllBytes($full) } else { $null } }
}

function Restore-AivcpFileSnapshot {
    param([Parameter(Mandatory = $true)]$Snapshot)
    $path = Resolve-AivcpFullPath ([string]$Snapshot.path)
    if ([bool]$Snapshot.exists) {
        $parent = Split-Path -Parent $path
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        [System.IO.File]::WriteAllBytes($path, [byte[]]$Snapshot.bytes)
    }
    elseif (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}

function Assert-AivcpPathBudget {
    param(
        [Parameter(Mandatory = $true)][string]$PathValue,
        [Parameter(Mandatory = $true)][string]$Purpose
    )
    $full = Resolve-AivcpFullPath $PathValue
    if ($full.Length -gt $script:AivcpLegacyPathBudget) {
        throw "Install path budget exceeded before extraction for $Purpose ($($full.Length) characters; limit $script:AivcpLegacyPathBudget). Choose a shorter -InstallRoot, such as C:\AIVCP."
    }
    return $full
}

function Get-AivcpRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)][string]$FilePath
    )
    $rootWithSlash = $RootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $rootUri = [System.Uri]::new($rootWithSlash)
    $fileUri = [System.Uri]::new($FilePath)
    return [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString())
}

function Get-AivcpNormalizedFileBytes {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    $textExtensions = @(".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml")
    $extension = [System.IO.Path]::GetExtension($FilePath).ToLowerInvariant()
    if ($textExtensions -contains $extension) {
        $content = [System.IO.File]::ReadAllText($FilePath)
        $normalized = $content.Replace("`r`n", "`n").Replace("`r", "`n")
        return [System.Text.UTF8Encoding]::new($false).GetBytes($normalized)
    }
    return [System.IO.File]::ReadAllBytes($FilePath)
}

function Get-AivcpSha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-AivcpFileSha256 {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    return (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-AivcpTreeHash {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $rootFull = Resolve-AivcpFullPath $RootPath
    $lines = New-Object System.Collections.Generic.List[string]
    $relativePaths = New-Object System.Collections.Generic.List[string]
    $filesByRelativePath = [System.Collections.Generic.Dictionary[string,System.IO.FileInfo]]::new([System.StringComparer]::Ordinal)
    Get-ChildItem -LiteralPath $rootFull -File -Recurse |
        Where-Object { $_.Extension -ne ".pyc" -and $_.FullName -notmatch "[\\/]__pycache__[\\/]" } |
        ForEach-Object {
            $relative = Get-AivcpRelativePath $rootFull $_.FullName
            $relativePaths.Add($relative)
            $filesByRelativePath.Add($relative, $_)
        }
    $relativePaths.Sort([System.StringComparer]::Ordinal)
    foreach ($relative in $relativePaths) {
        $file = $filesByRelativePath[$relative]
        $fileBytes = Get-AivcpNormalizedFileBytes $file.FullName
        $hash = Get-AivcpSha256Hex $fileBytes
        $lines.Add("$relative`t$($fileBytes.Length)`t$hash`n")
    }
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($lines -join ""))
    return Get-AivcpSha256Hex $bytes
}

function Get-AivcpDefaultDataRoot {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $statePath = Join-Path $installFull "current\install-state.json"
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $dataProperty = $state.PSObject.Properties["userDataRoot"]
        if ($null -ne $dataProperty -and -not [string]::IsNullOrWhiteSpace([string]$dataProperty.Value)) {
            return Resolve-AivcpFullPath ([string]$dataProperty.Value)
        }
    }
    $legacy = Join-Path $installFull "data"
    if (Test-Path -LiteralPath $legacy -PathType Container) {
        return Resolve-AivcpFullPath $legacy
    }
    return Resolve-AivcpFullPath (Join-Path $env:LOCALAPPDATA $script:AivcpDefaultDataFolder)
}

function Resolve-AivcpDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [string]$RequestedDataRoot
    )
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $dataFull = if ([string]::IsNullOrWhiteSpace($RequestedDataRoot)) {
        Get-AivcpDefaultDataRoot $installFull
    }
    else {
        Resolve-AivcpFullPath $RequestedDataRoot
    }
    if ($dataFull -eq $installFull) {
        throw "User data root must not equal the program installation root."
    }
    $currentPrefix = (Join-Path $installFull "current").TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if ($dataFull.StartsWith($currentPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "User data root must not be placed inside the active program version."
    }
    return Test-AivcpSafeRoot $dataFull "DataRoot"
}

function Get-AivcpInstallation {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $marker = Join-Path $installFull "installation.json"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw "Installation marker is missing: $marker"
    }
    $installation = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$installation.productId -ne $script:AivcpProductId) {
        throw "Installation marker does not belong to this product."
    }
    return $installation
}

function Test-AivcpNoReparsePoints {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $rootFull = Resolve-AivcpFullPath $RootPath
    $reparse = Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction Stop |
        Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($null -ne $reparse) {
        throw "Reparse points are not allowed in this operation: $($reparse.FullName)"
    }
}

function Write-AivcpJsonFile {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$PathValue,
        [int]$Depth = 12
    )
    $json = $Value | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($PathValue, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

function Write-AivcpRuntimeBoundMcpDescriptor {
    param(
        [Parameter(Mandatory = $true)][string]$PluginRoot,
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$ProductVersion,
        [Parameter(Mandatory = $true)][string]$ReleaseManifestSha256,
        [string]$ComponentVerificationRoot
    )
    $pluginFull = Test-AivcpSafeRoot $PluginRoot "MCP PluginRoot"
    $installFull = Test-AivcpSafeRoot $InstallRoot "MCP InstallRoot"
    $dataFull = Test-AivcpSafeRoot $DataRoot "MCP DataRoot"
    if ($ReleaseManifestSha256 -notmatch "^[a-fA-F0-9]{64}$") { throw "Cannot bind MCP runtime because the release manifest SHA-256 is invalid." }
    $pluginManifestPath = Join-Path $pluginFull ".codex-plugin\plugin.json"
    if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) { throw "Cannot bind MCP runtime because plugin.json is missing." }
    $pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$pluginManifest.name -ne $script:AivcpProductId -or [string]$pluginManifest.version -ne $ProductVersion) {
        throw "Cannot bind MCP runtime because the plugin identity or version differs from the installation."
    }
    $voiceCatalogVerificationPath = Join-Path $pluginFull "assets\voice-catalog.json"
    if (-not (Test-Path -LiteralPath $voiceCatalogVerificationPath -PathType Leaf)) {
        throw "Cannot bind MCP runtime because the bundled pre-scanned voice catalog is missing."
    }
    try {
        $voiceCatalog = Get-Content -LiteralPath $voiceCatalogVerificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Cannot bind MCP runtime because the bundled pre-scanned voice catalog is unreadable."
    }
    if ([string]$voiceCatalog.schemaVersion -ne "1.0.0" -or @($voiceCatalog.engines).Count -eq 0) {
        throw "Cannot bind MCP runtime because the bundled pre-scanned voice catalog contract is invalid."
    }
    $youtubeRuntimeContractPath = Join-Path $pluginFull "assets\portable-youtube-runtime.json"
    $youtubeRuntimeContract = $null
    if (Test-Path -LiteralPath $youtubeRuntimeContractPath -PathType Leaf) {
        try {
            $youtubeRuntimeContract = Get-Content -LiteralPath $youtubeRuntimeContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw "Cannot bind MCP runtime because the portable YouTube runtime contract is unreadable."
        }
        if (
            [string]$youtubeRuntimeContract.schemaVersion -ne "1.1.0" -or
            [string]$youtubeRuntimeContract.collector.id -ne "yt-dlp" -or
            [string]::IsNullOrWhiteSpace([string]$youtubeRuntimeContract.collector.version) -or
            [string]::IsNullOrWhiteSpace([string]$youtubeRuntimeContract.collector.commandVersion) -or
            [string]$youtubeRuntimeContract.javascriptRuntime.id -ne "deno" -or
            [bool]$youtubeRuntimeContract.requiresSystemPath -ne $false -or
            @($youtubeRuntimeContract.collector.entryPointArguments).Count -ne 2 -or
            [string]$youtubeRuntimeContract.collector.entryPointArguments[0] -ne "-m" -or
            [string]$youtubeRuntimeContract.collector.entryPointArguments[1] -ne "yt_dlp"
        ) {
            throw "Cannot bind MCP runtime because the portable YouTube runtime contract is invalid."
        }
    }
    $activeRoot = Resolve-AivcpFullPath (Join-Path $installFull "current")
    $verificationRoot = if ([string]::IsNullOrWhiteSpace($ComponentVerificationRoot)) {
        $activeRoot
    }
    else {
        Test-AivcpSafeRoot $ComponentVerificationRoot "MCP ComponentVerificationRoot"
    }
    $workshopVerificationRoot = Join-Path $verificationRoot "apps\workshop"
    $workshopExecutables = @(Get-ChildItem -LiteralPath $workshopVerificationRoot -Filter "*.exe" -File -ErrorAction Stop)
    if ($workshopExecutables.Count -ne 1) {
        throw "Cannot bind MCP runtime because the managed workshop root must contain exactly one top-level executable."
    }
    $workshopRelativePath = Join-Path "apps\workshop" ([string]$workshopExecutables[0].Name)
    $managedFiles = [ordered]@{
        python = "runtime\python\python.exe"
        workshop = $workshopRelativePath
        ffmpeg = "apps\workshop\tools\ffmpeg\bin\ffmpeg.exe"
        ffprobe = "apps\workshop\tools\ffmpeg\bin\ffprobe.exe"
        publisherChannelList = "apps\publisher\channel-list.exe"
        publisherV2 = "apps\publisher\publish-package-v2.exe"
        publisherDesktop = "apps\publisher\youtube-publisher-center.exe"
    }
    if ($null -ne $youtubeRuntimeContract) {
        $managedFiles.youtubeCollectorModule = ([string]$youtubeRuntimeContract.collector.moduleRelativePath).Replace("/", "\")
        $managedFiles.youtubeEjsModule = ([string]$youtubeRuntimeContract.collector.ejsModuleRelativePath).Replace("/", "\")
        $managedFiles.youtubeJavascriptRuntime = ([string]$youtubeRuntimeContract.javascriptRuntime.executableRelativePath).Replace("/", "\")
    }
    foreach ($managed in $managedFiles.GetEnumerator()) {
        $verificationPath = Join-Path $verificationRoot ([string]$managed.Value)
        if (-not (Test-Path -LiteralPath $verificationPath -PathType Leaf)) {
            throw "Cannot bind MCP runtime because the managed $($managed.Key) component is missing: $verificationPath"
        }
    }
    $pythonPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.python)
    $workshopPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.workshop)
    $ffmpegPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.ffmpeg)
    $ffprobePath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.ffprobe)
    $publisherChannelListPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.publisherChannelList)
    $publisherV2Path = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.publisherV2)
    $publisherDesktopPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.publisherDesktop)
    $voiceCatalogPath = Resolve-AivcpFullPath (Join-Path $activeRoot "plugins\$($script:AivcpProductId)\assets\voice-catalog.json")
    $youtubeCollectorCommandJson = $null
    if ($null -ne $youtubeRuntimeContract) {
        $denoPath = Resolve-AivcpFullPath (Join-Path $activeRoot $managedFiles.youtubeJavascriptRuntime)
        $ffmpegDirectory = Resolve-AivcpFullPath (Split-Path -Parent $ffmpegPath)
        $youtubeCollectorCommandJson = ConvertTo-Json -InputObject @(
            $pythonPath,
            "-m",
            "yt_dlp",
            "--js-runtimes",
            ("deno:" + $denoPath),
            "--ffmpeg-location",
            $ffmpegDirectory
        ) -Compress
    }
    $workshopIsolationRoot = Resolve-AivcpFullPath (Join-Path $dataFull "workshop-isolation")
    if (-not (Test-Path -LiteralPath $workshopIsolationRoot -PathType Container)) {
        throw "Cannot bind MCP runtime because the managed workshop isolation root is missing: $workshopIsolationRoot"
    }
    $configRoot = Split-Path -Parent (Get-AivcpRuntimeLocatorPath)
    $descriptorPath = Join-Path $pluginFull ".mcp.json"
    $temporaryPath = Join-Path $pluginFull (".mcp-bound-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        $runtimeEnvironment = [ordered]@{
            AIVCP_DATA_ROOT = $dataFull
            AIVCP_CONFIG_ROOT = $configRoot
            AIVCP_INSTALL_ROOT = $installFull
            AIVCP_EXPECTED_PRODUCT_VERSION = $ProductVersion
            AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256 = $ReleaseManifestSha256.ToLowerInvariant()
            AIVCP_WORKSHOP_EXECUTABLE = $workshopPath
            AIVCP_WORKSHOP_ISOLATION_ROOT = $workshopIsolationRoot
            AIVCP_FFMPEG_PATH = $ffmpegPath
            AIVCP_FFPROBE_PATH = $ffprobePath
            AIVCP_PUBLISHER_CHANNEL_LIST_EXE = $publisherChannelListPath
            AIVCP_PUBLISHER_V2_CLI = $publisherV2Path
            AIVCP_PUBLISHER_DESKTOP_EXE = $publisherDesktopPath
            AIVCP_VOICE_CATALOG = $voiceCatalogPath
            AIVCP_PUBLISHER_TIMEOUT_SECONDS = "8"
            AIVCP_NETWORK_EXECUTION = "false"
            AIVCP_PUBLISHER_NETWORK_EXECUTION = "false"
            PYTHONUTF8 = "1"
            PYTHONDONTWRITEBYTECODE = "1"
        }
        if ($null -ne $youtubeCollectorCommandJson) {
            $runtimeEnvironment.AIVCP_YT_DLP_COMMAND_JSON = $youtubeCollectorCommandJson
        }
        Write-AivcpJsonFile -Value ([ordered]@{
            mcpServers = [ordered]@{
                "ai-video-channel-tools" = [ordered]@{
                    type = "stdio"
                    cwd = "."
                    command = $pythonPath
                    args = @("./mcp/server.py", "mcp")
                    env = $runtimeEnvironment
                    tool_timeout_sec = 60
                }
            }
        }) -PathValue $temporaryPath
        Move-Item -LiteralPath $temporaryPath -Destination $descriptorPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
    }
    $verified = Get-Content -LiteralPath $descriptorPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $server = $verified.mcpServers."ai-video-channel-tools"
    $youtubeBindingInvalid = $null -ne $youtubeRuntimeContract -and [string]$server.env.AIVCP_YT_DLP_COMMAND_JSON -ne $youtubeCollectorCommandJson
    if (
        [string]$server.type -ne "stdio" -or
        [string]$server.cwd -ne "." -or
        [string]$server.command -ne $pythonPath -or
        @($server.args).Count -ne 2 -or
        [string]$server.args[0] -ne "./mcp/server.py" -or
        [string]$server.args[1] -ne "mcp" -or
        [string]$server.env.AIVCP_DATA_ROOT -ne $dataFull -or
        [string]$server.env.AIVCP_CONFIG_ROOT -ne $configRoot -or
        [string]$server.env.AIVCP_INSTALL_ROOT -ne $installFull -or
        [string]$server.env.AIVCP_EXPECTED_PRODUCT_VERSION -ne $ProductVersion -or
        [string]$server.env.AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256 -ne $ReleaseManifestSha256.ToLowerInvariant() -or
        [string]$server.env.AIVCP_WORKSHOP_EXECUTABLE -ne $workshopPath -or
        [string]$server.env.AIVCP_WORKSHOP_ISOLATION_ROOT -ne $workshopIsolationRoot -or
        [string]$server.env.AIVCP_FFMPEG_PATH -ne $ffmpegPath -or
        [string]$server.env.AIVCP_FFPROBE_PATH -ne $ffprobePath -or
        [string]$server.env.AIVCP_PUBLISHER_CHANNEL_LIST_EXE -ne $publisherChannelListPath -or
        [string]$server.env.AIVCP_PUBLISHER_V2_CLI -ne $publisherV2Path -or
        [string]$server.env.AIVCP_PUBLISHER_DESKTOP_EXE -ne $publisherDesktopPath -or
        [string]$server.env.AIVCP_VOICE_CATALOG -ne $voiceCatalogPath -or
        [string]$server.env.AIVCP_PUBLISHER_TIMEOUT_SECONDS -ne "8" -or
        [string]$server.env.AIVCP_NETWORK_EXECUTION -ne "false" -or
        [string]$server.env.AIVCP_PUBLISHER_NETWORK_EXECUTION -ne "false" -or
        $youtubeBindingInvalid
    ) {
        throw "Runtime-bound MCP descriptor verification failed."
    }
    return $descriptorPath
}

function Get-AivcpRuntimeLocatorRecord {
    $locatorPath = Get-AivcpRuntimeLocatorPath
    if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf)) { return $null }
    $locator = Get-Content -LiteralPath $locatorPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$locator.schemaVersion -ne "1.0.0" -or [string]$locator.productId -ne $script:AivcpProductId) {
        throw "Runtime locator identity is invalid: $locatorPath"
    }
    $installFull = Test-AivcpSafeRoot ([string]$locator.installRoot) "Runtime locator InstallRoot"
    $markerPath = Join-Path $installFull "installation.json"
    $statePath = Join-Path $installFull "current\install-state.json"
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf) -or -not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Runtime locator points to an incomplete installation."
    }
    $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$locator.activeRoot -ne "current" -or
        [string]$locator.pythonRelativePath -ne "runtime/python/python.exe" -or
        [string]$marker.schemaVersion -ne "2.0.0" -or
        [string]$marker.productId -ne $script:AivcpProductId -or
        [string]$marker.activeVersion -ne [string]$locator.productVersion -or
        [string]$marker.activeRoot -ne "current" -or
        [string]$state.schemaVersion -ne "2.0.0" -or
        [string]$state.productId -ne $script:AivcpProductId -or
        [string]$state.productVersion -ne [string]$locator.productVersion -or
        [string]$state.releaseManifestSha256 -ne [string]$marker.releaseManifestSha256 -or
        -not [bool]$state.runtime.bundled -or
        [string]$state.runtime.python -ne "runtime/python/python.exe"
    ) {
        throw "Runtime locator and active installation state do not match."
    }
    $pythonPath = Join-Path $installFull "current\runtime\python\python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Runtime locator bundled Python is missing."
    }
    $stateDataRoot = Test-AivcpSafeRoot ([string]$state.userDataRoot) "Runtime locator DataRoot"
    $locatorDataRoot = Test-AivcpSafeRoot ([string]$locator.userDataRoot) "Runtime locator DataRoot"
    $markerDataRoot = Test-AivcpSafeRoot ([string]$marker.userDataRoot) "Runtime locator DataRoot"
    if (
        -not $stateDataRoot.Equals($locatorDataRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $stateDataRoot.Equals($markerDataRoot, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Runtime locator user data root does not match the active installation."
    }
    return [ordered]@{
        locatorPath = $locatorPath
        installRoot = $installFull
        pythonPath = Resolve-AivcpFullPath $pythonPath
        userDataRoot = $stateDataRoot
        productVersion = [string]$state.productVersion
    }
}

function Write-AivcpRuntimeLocator {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$ProductVersion,
        [Parameter(Mandatory = $true)][ValidateSet("install", "upgrade", "repair", "rollback", "idempotent")][string]$Operation,
        [switch]$AllowTakeover
    )
    $installFull = Test-AivcpSafeRoot $InstallRoot "Runtime locator InstallRoot"
    $dataFull = Test-AivcpSafeRoot $DataRoot "Runtime locator DataRoot"
    $locatorPath = Get-AivcpRuntimeLocatorPath
    $locatorParent = Split-Path -Parent $locatorPath
    $previousInstallRoot = $null
    if (Test-Path -LiteralPath $locatorPath -PathType Leaf) {
        try {
            $previousLocator = Get-Content -LiteralPath $locatorPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$previousLocator.productId -eq $script:AivcpProductId) {
                $previousInstallRoot = Resolve-AivcpFullPath ([string]$previousLocator.installRoot)
            }
        }
        catch {
            $previousInstallRoot = "INVALID_OR_UNREADABLE_LOCATOR"
        }
    }
    $takeover = -not [string]::IsNullOrWhiteSpace($previousInstallRoot) -and -not $previousInstallRoot.Equals($installFull, [System.StringComparison]::OrdinalIgnoreCase)
    if ($takeover -and -not $AllowTakeover) {
        throw "Runtime locator is owned by another installation ($previousInstallRoot). Explicit takeover is required."
    }
    if ($takeover) {
        Write-Warning "Runtime locator ownership is being transferred from $previousInstallRoot to $installFull by explicit $Operation operation."
    }
    New-Item -ItemType Directory -Path $locatorParent -Force | Out-Null
    $temporaryPath = Join-Path $locatorParent (".runtime-locator-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        Write-AivcpJsonFile -Value ([ordered]@{
            schemaVersion = "1.0.0"
            productId = $script:AivcpProductId
            productVersion = $ProductVersion
            installRoot = $installFull
            activeRoot = "current"
            pythonRelativePath = "runtime/python/python.exe"
            userDataRoot = $dataFull
            ownership = [ordered]@{
                operation = $Operation
                takeover = $takeover
                previousInstallRoot = $previousInstallRoot
            }
            updatedAt = (Get-Date).ToUniversalTime().ToString("o")
        }) -PathValue $temporaryPath
        Move-Item -LiteralPath $temporaryPath -Destination $locatorPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
    }
    $verified = Get-AivcpRuntimeLocatorRecord
    if ($null -eq $verified -or [string]$verified.installRoot -ne $installFull -or [string]$verified.userDataRoot -ne $dataFull) {
        throw "Runtime locator verification failed."
    }
    $historyPath = Join-Path $locatorParent $script:AivcpRuntimeLocatorHistoryFileName
    $historyRecord = [ordered]@{
        schemaVersion = "1.0.0"
        productId = $script:AivcpProductId
        operation = $Operation
        takeover = $takeover
        previousInstallRoot = $previousInstallRoot
        installRoot = $installFull
        productVersion = $ProductVersion
        recordedAt = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Compress
    [System.IO.File]::AppendAllText($historyPath, $historyRecord + "`n", [System.Text.UTF8Encoding]::new($false))
    return $locatorPath
}

function Remove-AivcpRuntimeLocatorIfOwned {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $locatorPath = Get-AivcpRuntimeLocatorPath
    if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf)) { return $false }
    if (-not (Test-AivcpRuntimeLocatorOwnedBy -InstallRoot $InstallRoot)) { return $false }
    Remove-Item -LiteralPath $locatorPath -Force
    return $true
}

function Test-AivcpRuntimeLocatorOwnedBy {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $installFull = Test-AivcpSafeRoot $InstallRoot "Runtime locator InstallRoot"
    $locatorPath = Get-AivcpRuntimeLocatorPath
    if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf)) { return $false }
    try {
        $locator = Get-Content -LiteralPath $locatorPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$locator.productId -ne $script:AivcpProductId) { return $false }
        $ownedRoot = Resolve-AivcpFullPath ([string]$locator.installRoot)
        if (-not $ownedRoot.Equals($installFull, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    catch {
        return $false
    }
    return $true
}

function Get-AivcpManifestHash {
    param([Parameter(Mandatory = $true)][string]$ManifestPath)
    return Get-AivcpFileSha256 (Resolve-AivcpFullPath $ManifestPath)
}

function Test-AivcpRelativeArchivePath {
    param([Parameter(Mandatory = $true)][string]$EntryName)
    $normalized = $EntryName.Replace("\", "/")
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.StartsWith("/") -or $normalized -match "^[A-Za-z]:") {
        throw "Unsafe ZIP entry path: $EntryName"
    }
    foreach ($part in $normalized.Split('/')) {
        if ($part -eq "..") { throw "Unsafe ZIP entry path: $EntryName" }
    }
    return $normalized
}

function Assert-AivcpArchivePathBudget {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$ExpectedRoot,
        [Parameter(Mandatory = $true)][string]$ExtractionRoot,
        [Parameter(Mandatory = $true)][string]$StagedInstallRoot,
        [Parameter(Mandatory = $true)][string]$ActiveInstallRoot,
        [Parameter(Mandatory = $true)][string]$AssetId
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-AivcpFullPath $ArchivePath))
    try {
        foreach ($entry in $archive.Entries) {
            $normalized = Test-AivcpRelativeArchivePath $entry.FullName
            $parts = $normalized.Split('/')
            if ($parts[0] -ne $ExpectedRoot) { throw "ZIP root mismatch: expected $ExpectedRoot, found $($parts[0])" }
            $relative = ($parts | Select-Object -Skip 1) -join [System.IO.Path]::DirectorySeparatorChar
            if ([string]::IsNullOrWhiteSpace($relative)) { continue }
            $null = Assert-AivcpPathBudget (Join-Path $ExtractionRoot $relative) "$AssetId extraction entry $normalized"
            $null = Assert-AivcpPathBudget (Join-Path $StagedInstallRoot $relative) "$AssetId staged entry $normalized"
            $null = Assert-AivcpPathBudget (Join-Path $ActiveInstallRoot $relative) "$AssetId active entry $normalized"
        }
    }
    finally { $archive.Dispose() }
}

function Expand-AivcpVerifiedZip {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$ExpectedRoot
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationFull = Resolve-AivcpFullPath $DestinationPath
    $null = Assert-AivcpPathBudget $destinationFull "ZIP extraction root"
    New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
    $prefix = $destinationFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-AivcpFullPath $ArchivePath))
    try {
        foreach ($entry in $archive.Entries) {
            $normalized = Test-AivcpRelativeArchivePath $entry.FullName
            if (-not $seen.Add($normalized)) { throw "Duplicate ZIP entry: $normalized" }
            $parts = $normalized.Split('/')
            if ($parts[0] -ne $ExpectedRoot) { throw "ZIP root mismatch: expected $ExpectedRoot, found $($parts[0])" }
            $unixMode = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if ($unixMode -eq 0xA000) { throw "ZIP symbolic links are not allowed: $normalized" }
            $relative = ($parts | Select-Object -Skip 1) -join [System.IO.Path]::DirectorySeparatorChar
            if ([string]::IsNullOrWhiteSpace($relative)) { continue }
            $target = Assert-AivcpPathBudget (Join-Path $destinationFull $relative) "ZIP extraction entry $normalized"
            if (-not $target.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "ZIP entry escapes extraction root: $normalized"
            }
            if ($entry.FullName.EndsWith("/") -or [string]::IsNullOrEmpty($entry.Name)) {
                New-Item -ItemType Directory -Path $target -Force | Out-Null
                continue
            }
            $targetParent = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
            $input = $entry.Open()
            $output = [System.IO.File]::Open($target, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    }
    finally {
        $archive.Dispose()
    }
    Test-AivcpNoReparsePoints $destinationFull
    return $destinationFull
}

function Copy-AivcpDirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $DestinationPath -Recurse -Force
    }
}

function Get-AivcpVerifiedAsset {
    param(
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$AssetRoot,
        [Parameter(Mandatory = $true)][string]$CacheRoot,
        [Parameter(Mandatory = $true)][ValidateSet("Auto", "Offline", "Online")][string]$InstallMode,
        [string]$DownloadBaseUrl
    )
    $fileName = [string]$Asset.fileName
    if ([System.IO.Path]::GetFileName($fileName) -ne $fileName) { throw "Asset filename is unsafe: $fileName" }
    $local = Join-Path $AssetRoot $fileName
    $candidate = $local
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        if ($InstallMode -eq "Offline") { throw "Offline asset is missing: $fileName" }
        if ([string]::IsNullOrWhiteSpace($DownloadBaseUrl)) { throw "Asset is missing and no download URL is configured: $fileName" }
        New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
        $candidate = Join-Path $CacheRoot $fileName
        $uri = $DownloadBaseUrl.TrimEnd('/') + '/' + [System.Uri]::EscapeDataString($fileName)
        Invoke-WebRequest -Uri $uri -OutFile $candidate -UseBasicParsing
    }
    $item = Get-Item -LiteralPath $candidate
    if ([int64]$item.Length -ne [int64]$Asset.sizeBytes) {
        throw "Asset size mismatch: $fileName (expected $($Asset.sizeBytes), got $($item.Length))"
    }
    $actual = Get-AivcpFileSha256 $candidate
    if ($actual -ne [string]$Asset.sha256) {
        throw "Asset SHA-256 mismatch: $fileName (expected $($Asset.sha256), got $actual)"
    }
    return $candidate
}

function Write-AivcpCodexSetupGuide {
    param(
        [Parameter(Mandatory = $true)][string]$CurrentRoot,
        [Parameter(Mandatory = $true)][string]$Reason
    )
    $guidePath = Join-Path $CurrentRoot "CODEX-PLUGIN-SETUP.txt"
    $lines = @(
        "AI Video Channel Production files are installed and healthy.",
        "Codex plugin registration status: MANUAL_ACTION_REQUIRED",
        "Reason: $Reason",
        "",
        "Register the repository marketplace with the CLI:",
        "  codex plugin marketplace add `"$CurrentRoot`"",
        "Then open Codex > Plugins, find the novel-manga-production marketplace, and install or enable ai-video-channel-production.",
        "If a future Codex CLI exposes 'codex plugin add', the Plugins UI step may be completed with:",
        "  codex plugin add ai-video-channel-production@novel-manga-production",
        "",
        "This uses the repository marketplace shipped with the product; it does not create or edit a personal marketplace file directly.",
        "Then restart Codex and create a new task. Existing tasks do not reload plugin changes."
    )
    [System.IO.File]::WriteAllLines($guidePath, $lines, [System.Text.UTF8Encoding]::new($false))
    return $guidePath
}
