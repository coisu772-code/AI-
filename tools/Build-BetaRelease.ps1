[CmdletBinding()]
param(
    [string]$Version = "0.1.0-beta.2"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $root "dist"))
if (-not $distRoot.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected distribution path: $distRoot"
}

$archiveName = "ai-video-channel-production-v$Version.zip"
$archivePath = Join-Path $distRoot $archiveName
$checksumsPath = Join-Path $distRoot "SHA256SUMS.txt"
$stagingRoot = Join-Path $distRoot (".packaging-" + [guid]::NewGuid().ToString("N"))
$packageRoot = Join-Path $stagingRoot "ai-video-channel-production"
$payloadItems = @(
    ".agents",
    "plugins",
    "contracts",
    "installer",
    "release-manifests",
    "docs",
    "README.md",
    "CHANGELOG.md",
    "LICENSE.md"
)

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
try {
    foreach ($item in $payloadItems) {
        $source = Join-Path $root $item
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Release payload is missing: $item"
        }
        Copy-Item -LiteralPath $source -Destination $packageRoot -Recurse -Force
    }

    New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $archivePath -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $archiveName`n" | Set-Content -LiteralPath $checksumsPath -Encoding ascii -NoNewline
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

Write-Output "Built $archivePath"
Write-Output "SHA-256 $hash"
