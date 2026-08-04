[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$RuntimeSource,
    [Parameter(Mandatory = $true)][string]$WorkshopAssetRoot,
    [Parameter(Mandatory = $true)][string]$PublisherAssetRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$uv = Get-Command uv -ErrorAction Stop
& $uv.Source run python (Join-Path $root "tools\build_unified_release.py") --output $OutputRoot --runtime-source $RuntimeSource --uv $uv.Source --workshop-dir $WorkshopAssetRoot --publisher-dir $PublisherAssetRoot
if ($LASTEXITCODE -ne 0) { throw "Unified release build failed." }
