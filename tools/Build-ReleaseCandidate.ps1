[CmdletBinding()]
param(
    [string]$OutputRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\v0.8.0-rc.1")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$output = [System.IO.Path]::GetFullPath($OutputRoot)
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required to build the release candidate." }
New-Item -ItemType Directory -Path $output -Force | Out-Null
& $uv.Source run python (Join-Path $root "tools\build_release_candidate.py") --output $output
if ($LASTEXITCODE -ne 0) { throw "Release candidate build failed." }
$archive = Join-Path $output "ai-video-channel-production-v0.8.0-rc.1-windows.zip"
& $uv.Source run python (Join-Path $root "tools\scan_release_candidate.py") --archive $archive
if ($LASTEXITCODE -ne 0) { throw "Release candidate safety scan failed." }
Write-Output "Local RC built and verified at $archive"
