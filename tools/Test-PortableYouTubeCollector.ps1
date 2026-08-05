[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [Parameter(Mandatory = $true)][string]$FFmpegDirectory,
    [string]$ChannelUrl = "https://www.youtube.com/@kibou_isekai_anime/videos",
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runtimeFull = [System.IO.Path]::GetFullPath($RuntimeRoot)
$python = Join-Path $runtimeFull "python.exe"
$deno = Join-Path $runtimeFull "tools\deno.exe"
$ffmpegFull = [System.IO.Path]::GetFullPath($FFmpegDirectory)
foreach ($required in @($python, $deno, (Join-Path $ffmpegFull "ffmpeg.exe"), (Join-Path $ffmpegFull "ffprobe.exe"))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Portable YouTube collector test input is missing: $required"
    }
}

$pathSnapshot = $env:PATH
try {
    $systemRootValue = $env:SystemRoot
    $env:PATH = @(
        (Join-Path $systemRootValue "System32"),
        $systemRootValue,
        (Join-Path $systemRootValue "System32\WindowsPowerShell\v1.0")
    ) -join ";"
    if ($null -ne (Get-Command yt-dlp -ErrorAction SilentlyContinue)) {
        throw "Portable YouTube collector test did not isolate the system PATH."
    }

    $collectorVersionOutput = @(& $python -m yt_dlp --version 2>&1)
    $collectorVersionExit = $LASTEXITCODE
    $collectorVersion = $collectorVersionOutput | Select-Object -First 1
    if ($collectorVersionExit -ne 0 -or [string]::IsNullOrWhiteSpace([string]$collectorVersion)) {
        throw "Bundled yt-dlp did not start."
    }
    $denoVersionOutput = @(& $deno --version 2>&1)
    $denoVersionExit = $LASTEXITCODE
    $denoVersion = $denoVersionOutput | Select-Object -First 1
    if ($denoVersionExit -ne 0 -or [string]::IsNullOrWhiteSpace([string]$denoVersion)) {
        throw "Bundled Deno did not start."
    }

    $common = @(
        "-m", "yt_dlp",
        "--js-runtimes", ("deno:" + $deno),
        "--ffmpeg-location", $ffmpegFull,
        "--no-warnings"
    )
    $channelJson = & $python @common --dump-single-json --flat-playlist --playlist-end 1 --skip-download --ignore-errors $ChannelUrl
    if ($LASTEXITCODE -ne 0) { throw "Bundled collector could not read the public YouTube channel." }
    $channel = $channelJson | ConvertFrom-Json
    $entries = @($channel.entries)
    if ($entries.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$entries[0].id)) {
        throw "Bundled collector returned no verifiable public video from the channel."
    }

    $videoUrl = "https://www.youtube.com/watch?v=" + [string]$entries[0].id
    $videoJson = & $python @common --dump-single-json --skip-download --no-playlist $videoUrl
    if ($LASTEXITCODE -ne 0) { throw "Bundled collector could not read the selected public YouTube video." }
    $video = $videoJson | ConvertFrom-Json
    if ([string]$video.id -ne [string]$entries[0].id -or [string]::IsNullOrWhiteSpace([string]$video.title)) {
        throw "Bundled collector video identity is invalid."
    }

    $result = [ordered]@{
        status = "PASS"
        collectorVersion = [string]$collectorVersion
        javascriptRuntimeVersion = [string]$denoVersion
        systemPathCollectorVisible = $false
        channelId = [string]$channel.id
        channelTitle = [string]$channel.title
        videoId = [string]$video.id
        videoTitle = [string]$video.title
        captionLanguageCount = @($video.automatic_captions.PSObject.Properties).Count + @($video.subtitles.PSObject.Properties).Count
        cookiesUsed = $false
        oauthUsed = $false
        browserControlUsed = $false
    }
}
finally {
    $env:PATH = $pathSnapshot
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 4
}
else {
    Write-Output ("Portable YouTube collector PASS: {0}; {1}; video={2}" -f $result.collectorVersion, $result.javascriptRuntimeVersion, $result.videoId)
}
