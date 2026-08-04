[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$AssetRoot,
    [string]$DownloadBaseUrl,
    [ValidateSet("Auto", "Offline", "Online")][string]$InstallMode = "Auto",
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [switch]$SkipCodexRegistration
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($AssetRoot)) { $AssetRoot = Split-Path -Parent ([System.IO.Path]::GetFullPath($ManifestPath)) }
try {
    & (Join-Path $PSScriptRoot "Install-AIVideoChannelProduction.ps1") -ManifestPath $ManifestPath -AssetRoot $AssetRoot -DownloadBaseUrl $DownloadBaseUrl -InstallMode $InstallMode -InstallRoot $InstallRoot -DataRoot $DataRoot -SkipCodexRegistration:$SkipCodexRegistration -Force
}
catch { throw "Upgrade failed. The previous active version was restored automatically. $($_.Exception.Message)" }
