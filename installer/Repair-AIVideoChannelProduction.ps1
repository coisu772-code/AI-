[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$AssetRoot,
    [string]$DownloadBaseUrl,
    [ValidateSet("Auto", "Offline", "Online")][string]$InstallMode = "Auto",
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [string]$DataRoot,
    [switch]$SkipCodexRegistration
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$installation = Get-AivcpInstallation $installFull
if ([string]::IsNullOrWhiteSpace($DataRoot)) { $DataRoot = [string]$installation.userDataRoot }
if ([string]::IsNullOrWhiteSpace($ManifestPath)) { $ManifestPath = Join-Path $installFull "current\unified-release-manifest.json" }
if ([string]::IsNullOrWhiteSpace($AssetRoot)) { $AssetRoot = Split-Path -Parent (Resolve-AivcpFullPath $ManifestPath) }
& (Join-Path $PSScriptRoot "Install-AIVideoChannelProduction.ps1") -ManifestPath $ManifestPath -AssetRoot $AssetRoot -DownloadBaseUrl $DownloadBaseUrl -InstallMode $InstallMode -InstallRoot $installFull -DataRoot $DataRoot -SkipCodexRegistration:$SkipCodexRegistration -Force -LocatorOperation repair
if (-not $?) { throw "Repair failed; the previous active version was restored automatically." }
Write-Output "Repair completed; user data was preserved at $DataRoot"
